"""Bounded local protocol; kernel credentials authenticate both ends."""

from __future__ import annotations

import array
import json
import os
import socket
import struct

from .model import SplitterError

SOCKET_PATH = "/run/vpn-splitter/control.sock"
MAX_PACKET = 65536


def credentials(sock: socket.socket) -> tuple[int, int, int]:
    return struct.unpack("3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))


def send(sock, data: dict, fd: int | None = None):
    payload = json.dumps(data, ensure_ascii=False).encode()
    if len(payload) > MAX_PACKET:
        raise SplitterError("Message too large")
    ancillary = (
        [] if fd is None else [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [fd]))]
    )
    sock.sendmsg([payload], ancillary)


def receive(sock, expect_fd: bool = False):
    packet, ancillary, flags, _ = sock.recvmsg(MAX_PACKET, socket.CMSG_SPACE(4 * 8))
    fds = []
    try:
        for level, kind, data in ancillary:
            if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                values = array.array("i")
                values.frombytes(data[: len(data) - len(data) % values.itemsize])
                fds.extend(values)
        if flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC):
            raise SplitterError("Truncated message")
        if not packet:
            raise SplitterError("Service connection interrupted")
        data = json.loads(packet)
        if not isinstance(data, dict):
            raise SplitterError("Invalid message")
        if len(fds) != (1 if expect_fd else 0):
            if not (expect_fd and not fds and data.get("ok") is False):
                raise SplitterError("Unexpected file descriptors")
        result_fd = fds[0] if fds else None
        if result_fd is not None:
            os.set_inheritable(result_fd, False)
            fds.pop()
        return data, result_fd
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise SplitterError("Invalid JSON message") from error
    finally:
        for fd in fds:
            os.close(fd)


class Client:
    def __init__(self, path: str = SOCKET_PATH, expected_uid: int = 0):
        self.path = path
        self.expected_uid = expected_uid

    def request(self, operation: str, *, keep=False, **values):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        retained = False
        fd = None
        try:
            sock.settimeout(15)
            sock.connect(self.path)
            if credentials(sock)[1] != self.expected_uid:
                raise SplitterError("The service is not owned by root")
            send(sock, {"version": 1, "op": operation, **values})
            response, fd = receive(sock, expect_fd=keep)
            if response.get("ok") is not True:
                raise SplitterError(response.get("error", "Service error"))
            result = response.get("result")
            if not isinstance(result, dict):
                raise SplitterError("Invalid service response")
            if keep:
                sock.settimeout(None)
                retained = True
                return result, fd, sock
            return result
        except OSError as error:
            raise SplitterError(
                "Service unavailable: install/start vpn-splitter and check group membership"
            ) from error
        finally:
            if not retained:
                if fd is not None:
                    os.close(fd)
                sock.close()
