"""Real OpenConnect/ocserv test in disposable rootless namespaces.

Usage: unshare --user --map-root-user --mount --net python3 tests/integration/ocserv_check.py \
    --ocserv /path/to/ocserv --ocpasswd /path/to/ocpasswd [--library-path /path/to/libs]

No host routes, system services, real VPN credentials or privileged installation are used.
The rootless harness dispatches its hook to UID 1000 directly; production peer-UID
authorization and dropping application privileges are covered separately by unit tests.
ocserv's redundant setgroups(0) call is shimmed only in its disposable process:
an unprivileged single-GID user namespace forbids that call. This does not test
ocserv privilege separation. The shim is never installed or used by VPN Splitter.
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from vpn_splitter.cli import openconnect_command
from vpn_splitter.ipc import receive, send
from vpn_splitter.linux import IP, command, in_namespace
from vpn_splitter.model import Profile
from vpn_splitter.service import Manager


def main(args):
    mappings = Path("/proc/self/uid_map").read_text().split()
    if (
        os.getuid() != 0
        or len(mappings) != 3
        or mappings[0] != "0"
        or mappings[2] != "1"
        or mappings[1] == "0"
    ):
        raise SystemExit("Run with unshare as an ordinary user, never sudo")
    original_dns = Path("/etc/resolv.conf").read_bytes()
    target = Path("/etc/resolv.conf").resolve()
    command(["/usr/bin/mount", "--make-rprivate", "/"])
    command(["/usr/bin/mount", "-t", "tmpfs", "tmpfs", "/run"])
    if target.is_relative_to("/run"):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(original_dns)
    command([IP, "link", "set", "lo", "up"])
    environment = dict(os.environ)
    if args.library_path:
        environment["LD_LIBRARY_PATH"] = args.library_path
    with tempfile.TemporaryDirectory(prefix="vpn-splitter-ocserv-") as temporary:
        path = Path(temporary)
        shim = path / "rootless-ocserv.c"
        shim.write_text(
            "#include <sys/types.h>\n#include <grp.h>\n"
            "int setgroups(size_t size, const gid_t *groups) { return 0; }\n"
        )
        command(
            ["/usr/bin/cc", "-shared", "-fPIC", "-o", str(path / "rootless-ocserv.so"), str(shim)]
        )
        environment["LD_PRELOAD"] = str(path / "rootless-ocserv.so")
        command(
            [
                "/usr/bin/openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-keyout",
                str(path / "key.pem"),
                "-out",
                str(path / "cert.pem"),
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost,IP:127.0.0.1",
            ]
        )
        subprocess.run(
            [args.ocpasswd, "-c", str(path / "passwd"), "tester"],
            input="test-only-password\ntest-only-password\n",
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=True,
            env=environment,
        )
        (path / "ocserv.conf").write_text(f"""
auth = "plain[passwd={path}/passwd]"
tcp-port = 4443
udp-port = 4443
run-as-user = root
run-as-group = root
socket-file = {path}/ocserv.sock
pid-file = {path}/ocserv.pid
server-cert = {path}/cert.pem
server-key = {path}/key.pem
device = ocvpn
ipv4-network = 10.88.0.0
ipv4-netmask = 255.255.255.0
dns = 10.88.0.1
route = default
max-clients = 4
max-same-clients = 4
try-mtu-discovery = false
isolate-workers = false
keepalive = 10
dpd = 10
""")
        manager = Manager(path / "runtime")
        token = manager.begin(1000, "lab")["token"]
        sockpath = str(path / "control.sock")
        failures = []
        attached = threading.Event()
        with (
            socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as listener,
            (path / "server.log").open("w+") as server_log,
            (path / "client.log").open("w+") as client_log,
        ):
            listener.bind(sockpath)
            listener.listen(1)
            listener.settimeout(20)

            def accept_hook():
                try:
                    channel, _ = listener.accept()
                    with channel:
                        request, _ = receive(channel)
                        with manager.lock:
                            result, fd = manager.attach(
                                1000, request["config"], request["token"], channel
                            )
                        try:
                            send(channel, {"ok": True, "result": result}, fd)
                        finally:
                            os.close(fd)
                        attached.set()
                        channel.recv(1)
                        with manager.lock:
                            manager.detach(1000, channel)
                except Exception as error:
                    failures.append(error)
                    attached.set()

            receiver = threading.Thread(target=accept_hook, daemon=True)
            receiver.start()
            server = subprocess.Popen(
                [
                    args.ocserv,
                    "--foreground",
                    "--log-stderr",
                    "--debug=1",
                    "--config",
                    str(path / "ocserv.conf"),
                ],
                stdout=server_log,
                stderr=server_log,
                env=environment,
                start_new_session=True,
            )
            client = None
            try:
                for _ in range(100):
                    if server.poll() is not None:
                        server_log.seek(0)
                        raise AssertionError(server_log.read())
                    with socket.socket() as probe:
                        probe.settimeout(0.1)
                        if probe.connect_ex(("127.0.0.1", 4443)) == 0:
                            break
                    time.sleep(0.05)
                profile = Profile(
                    "lab", "Lab", "https://127.0.0.1:4443", "tester", cafile=str(path / "cert.pem")
                )
                argv = openconnect_command(profile, sockpath)
                argv.insert(-1, "--passwd-on-stdin")
                client = subprocess.Popen(
                    argv,
                    stdin=subprocess.PIPE,
                    stdout=client_log,
                    stderr=client_log,
                    env={**os.environ, "VPN_SPLITTER_TOKEN": token},
                    start_new_session=True,
                    text=True,
                )
                client.stdin.write("test-only-password\n")
                client.stdin.close()
                assert attached.wait(15), "OpenConnect did not attach its packet hook"
                if failures:
                    raise failures[0]
                assert manager.status(1000)["state"] == "connected"
                client_log.flush()
                client_log.seek(0)
                assert "Failed to open /dev/vhost-net" not in client_log.read()
                # Both clients contact the same destination. Their source addresses
                # distinguish the tunnel path from the outer namespace's direct path.
                with socket.socket() as http:
                    http.bind(("10.88.0.1", 8080))
                    http.listen(2)
                    http.settimeout(5)
                    code = (
                        "import socket;s=socket.create_connection(('10.88.0.1',8080),3);"
                        "s.sendall(b'GET / HTTP/1.0\\r\\n\\r\\n');"
                        "assert s.recv(1024).endswith(b'OK');print('TCP_OK')"
                    )
                    browser = subprocess.Popen(
                        in_namespace("vps-1000", "/usr/bin/python3", "-c", code),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    tunneled, selected_peer = http.accept()
                    with tunneled:
                        tunneled.recv(1024)
                        tunneled.sendall(b"HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\nOK")
                    output, error = browser.communicate(timeout=5)
                    assert browser.returncode == 0 and "TCP_OK" in output, error
                    with socket.create_connection(("10.88.0.1", 8080), 3) as direct:
                        normal, direct_peer = http.accept()
                        with normal:
                            direct.sendall(b"direct")
                            assert normal.recv(10) == b"direct"
                    assert selected_peer[0] != direct_peer[0], (selected_peer, direct_peer)
                # UDP echo endpoint exists only in the VPN server's network.
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as echo:
                    echo.bind(("10.88.0.1", 9999))
                    echo.settimeout(5)
                    probe_code = (
                        "import socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); "
                        "s.settimeout(3); "
                        "s.sendto(b'via-openconnect',('10.88.0.1',9999)); "
                        "assert s.recv(100)==b'via-openconnect'; print('UDP_OK')"
                    )
                    probe = subprocess.Popen(
                        in_namespace("vps-1000", "/usr/bin/python3", "-c", probe_code),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    packet, peer = echo.recvfrom(1000)
                    echo.sendto(packet, peer)
                    output, error = probe.communicate(timeout=5)
                    assert probe.returncode == 0 and "UDP_OK" in output, error
                # Exercise the actual per-application DNS bind mounts and NSS path.
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as dns:
                    dns.bind(("10.88.0.1", 53))
                    dns.settimeout(5)
                    code = (
                        f"import sys;sys.path.insert(0,{str(ROOT / 'src')!r});"
                        "from pathlib import Path;"
                        "from vpn_splitter.linux import mount_application_dns;"
                        "mount_application_dns(Path("
                        f"{str(path / 'runtime/sessions/1000')!r}));"
                        "import socket;assert socket.gethostbyname('intranet.test')=='10.88.0.42';"
                        "print('DNS_OK')"
                    )
                    resolver = subprocess.Popen(
                        in_namespace("vps-1000", "/usr/bin/python3", "-c", code),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    query, peer = dns.recvfrom(4096)
                    question = query[12:]
                    answer = query[:2] + struct.pack("!HHHHH", 0x8180, 1, 1, 0, 0) + question
                    answer += (
                        b"\xc0\x0c"
                        + struct.pack("!HHIH", 1, 1, 60, 4)
                        + socket.inet_aton("10.88.0.42")
                    )
                    dns.sendto(answer, peer)
                    output, error = resolver.communicate(timeout=5)
                    assert resolver.returncode == 0 and "DNS_OK" in output, error
                # No graceful cleanup: the hook must revoke an idle dead peer too.
                client.kill()
                client.wait(timeout=5)
                receiver.join(timeout=5)
                assert not receiver.is_alive()
                assert manager.status(1000)["state"] == "blocked"
                assert Path("/etc/resolv.conf").read_bytes() == original_dns
                print(
                    "PASS: password auth, real OpenConnect/ocserv tunnel, "
                    "TCP tunnel/direct comparison, UDP echo, private NSS/DNS resolution, "
                    "SIGKILL fail-closed behavior"
                )
            except Exception:
                server_log.flush()
                server_log.seek(0)
                print(server_log.read(), file=sys.stderr)
                client_log.flush()
                client_log.seek(0)
                print(client_log.read(), file=sys.stderr)
                raise
            finally:
                if client is not None and client.poll() is None:
                    os.killpg(client.pid, signal.SIGTERM)
                    try:
                        client.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(client.pid, signal.SIGKILL)
                        client.wait()
                if server.poll() is None:
                    os.killpg(server.pid, signal.SIGTERM)
                    try:
                        server.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(server.pid, signal.SIGKILL)
                        server.wait()
                manager.backend.remove(1000)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ocserv", default="/usr/sbin/ocserv")
    parser.add_argument("--ocpasswd", default="/usr/bin/ocpasswd")
    parser.add_argument("--library-path")
    main(parser.parse_args())
