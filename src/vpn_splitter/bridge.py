"""OpenConnect script-tun hook: forward complete IP datagrams, without root."""

from __future__ import annotations

import os
import selectors
import signal
import socket

from .ipc import Client
from .linux import syscall
from .model import SplitterError, tunnel_config


def relay(vpn_fd: int, tun_fd: int, control: socket.socket):
    """VPNFD is SOCK_DGRAM: each read/write must preserve one whole IP packet."""
    os.set_blocking(vpn_fd, False)
    os.set_blocking(tun_fd, False)
    with selectors.DefaultSelector() as selector:
        selector.register(vpn_fd, selectors.EVENT_READ, tun_fd)
        selector.register(tun_fd, selectors.EVENT_READ, vpn_fd)
        selector.register(control, selectors.EVENT_READ, None)
        while True:
            for key, _ in selector.select():
                if key.data is None:
                    return  # The daemon disconnected/revoked this tunnel. Fail closed.
                try:
                    packet = os.read(key.fd, 65535)
                except BlockingIOError:
                    continue
                if not packet:
                    return
                # IPv6 is deliberately unsupported by V1, including on the packet bridge.
                if packet[0] >> 4 != 4:
                    continue
                try:
                    written = os.write(key.data, packet)
                except BlockingIOError:
                    continue  # Drop under backpressure; never block revocation or split packets.
                if written != len(packet):
                    raise SplitterError("Incomplete packet write")


def hook(socket_path: str):
    # SOCK_DGRAM does not reliably report a dead peer while idle. Kill the hook
    # when OpenConnect dies, including SIGKILL, so the service revokes attachment.
    parent = os.getppid()
    syscall("prctl", 1, signal.SIGTERM, 0, 0, 0)  # PR_SET_PDEATHSIG
    if parent <= 1 or os.getppid() != parent:
        raise SplitterError("The OpenConnect process has exited")
    try:
        vpn_fd = int(os.environ["VPNFD"])
    except (KeyError, ValueError) as error:
        raise SplitterError("This program must be called by OpenConnect --script-tun") from error
    _, tun_fd, control = Client(socket_path).request(
        "attach",
        keep=True,
        config=tunnel_config(os.environ),
        token=os.environ.get("VPN_SPLITTER_TOKEN", ""),
    )
    try:
        relay(vpn_fd, tun_fd, control)
    finally:
        os.close(tun_fd)
        control.close()
