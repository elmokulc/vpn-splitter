#!/usr/bin/python3
"""Kernel smoke test in a disposable user/mount/network namespace; no host routes changed.

Run from the source tree:
  unshare --user --map-root-user --mount --net python3 tests/integration/network_check.py
"""

from __future__ import annotations

import ipaddress
import json
import os
import select
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(
    0, str(SOURCE if (SOURCE / "vpn_splitter").is_dir() else Path(__file__).resolve().parent)
)

from vpn_splitter.linux import IP, LinuxBackend, command, in_namespace


def checksum(data):
    if len(data) % 2:
        data += b"\0"
    total = sum(struct.unpack(f"!{len(data) // 2}H", data))
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


def reply(packet):
    header_length = (packet[0] & 15) * 4
    assert packet[9] == 17, "UDP expected"
    source, destination = packet[12:16], packet[16:20]
    source_port, destination_port, _, _ = struct.unpack(
        "!HHHH", packet[header_length : header_length + 8]
    )
    payload = packet[header_length + 8 :]
    udp = struct.pack("!HHHH", destination_port, source_port, len(payload) + 8, 0) + payload
    header = struct.pack(
        "!BBHHHBBH4s4s", 0x45, 0, 20 + len(udp), 1, 0, 64, 17, 0, destination, source
    )
    header = header[:10] + struct.pack("!H", checksum(header)) + header[12:]
    return header + udp


PROBE = """
import json, socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.settimeout(0.5)
try:
    s.sendto(b'vpn-splitter-test', ('198.18.0.1', 9999))
    data = s.recv(512)
    print(json.dumps({'reply': data.decode()}))
except OSError:
    print(json.dumps({'blocked': True}))
"""


def main():
    # Require a fresh rootless namespace, not root in the host's initial user namespace.
    mappings = Path("/proc/self/uid_map").read_text().split()
    if (
        os.getuid() != 0
        or len(mappings) != 3
        or mappings[0] != "0"
        or mappings[2] != "1"
        or mappings[1] == "0"
    ):
        raise SystemExit(
            "Use the unshare command above as an ordinary user; never run this with sudo"
        )
    host_routes = command([IP, "-j", "route", "show", "table", "all"]).stdout
    original_dns = Path("/etc/resolv.conf").read_bytes()
    dns_target = Path("/etc/resolv.conf").resolve()
    command(["/usr/bin/mount", "--make-rprivate", "/"])
    command(["/usr/bin/mount", "-t", "tmpfs", "tmpfs", "/run"])
    # Preserve a host resolv.conf symlink into /run in this disposable mount tree.
    if dns_target.is_relative_to("/run"):
        dns_target.parent.mkdir(parents=True, exist_ok=True)
        dns_target.write_bytes(original_dns)
    with tempfile.TemporaryDirectory(prefix="vpn-splitter-kernel-") as root:
        runtime = Path(root)
        directory = runtime / "sessions/1000"
        directory.mkdir(parents=True)
        (directory / "resolv.conf").touch()
        backend = LinuxBackend(runtime)
        fd = None
        backend.create(1000)
        try:
            fd = backend.configure(
                1000, {"address": "10.77.0.2", "mtu": 1400, "dns": ["10.77.0.1"]}
            )
            process = subprocess.Popen(
                in_namespace("vps-1000", "/usr/bin/python3", "-c", PROBE),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            readable, _, _ = select.select([fd], [], [], 5)
            assert readable, "Application traffic never reached the TUN interface"
            packet = os.read(fd, 65535)
            assert str(ipaddress.ip_address(packet[16:20])) == "198.18.0.1"
            os.write(fd, reply(packet))
            output, error = process.communicate(timeout=5)
            assert process.returncode == 0, error
            assert json.loads(output)["reply"] == "vpn-splitter-test"
            backend.block(1000)
            result = command(in_namespace("vps-1000", "/usr/bin/python3", "-c", PROBE))
            assert json.loads(result.stdout)["blocked"] is True
            result = command(
                in_namespace("vps-1000", "/usr/sbin/sysctl", "-n", "net.ipv6.conf.all.disable_ipv6")
            )
            assert result.stdout.strip() == "1"
            assert "nameserver 10.77.0.1" in (directory / "resolv.conf").read_text()
            assert Path("/etc/resolv.conf").read_bytes() == original_dns
            assert command([IP, "-j", "route", "show", "table", "all"]).stdout == host_routes
            print(
                "PASS: kernel TUN UDP roundtrip, tunnel-down blocking, "
                "IPv6 disabled, host routes/DNS unchanged"
            )
        finally:
            if fd is not None:
                os.close(fd)
            backend.remove(1000)


if __name__ == "__main__":
    main()
