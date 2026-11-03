import os
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from vpn_splitter.ipc import MAX_PACKET, Client, credentials, receive, send
from vpn_splitter.model import SplitterError
from vpn_splitter.service import Manager, handle


class ProtocolTest(unittest.TestCase):
    def pair(self):
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        return left, right

    def test_receives_kernel_credentials(self):
        left, _ = self.pair()
        self.assertEqual(credentials(left), (os.getpid(), os.getuid(), os.getgid()))

    def test_roundtrip_transfers_a_noninheritable_descriptor(self):
        left, right = self.pair()
        fd = os.open("/dev/null", os.O_RDWR)
        self.addCleanup(os.close, fd)
        send(left, {"ok": True}, fd)
        result, transferred = receive(right, expect_fd=True)
        self.addCleanup(os.close, transferred)
        self.assertTrue(result["ok"])
        self.assertFalse(os.get_inheritable(transferred))
        self.assertEqual(os.fstat(fd).st_rdev, os.fstat(transferred).st_rdev)

    def test_rejects_oversized_datagrams(self):
        left, right = self.pair()
        left.send(b" " * (MAX_PACKET + 1))
        with self.assertRaises(SplitterError):
            receive(right)

    def test_unexpected_fd_is_closed(self):
        left, right = self.pair()
        fd = os.open("/dev/null", os.O_RDONLY)
        self.addCleanup(os.close, fd)
        before = len(list(Path("/proc/self/fd").iterdir()))
        send(left, {"ok": True}, fd)
        with self.assertRaises(SplitterError):
            receive(right)
        self.assertEqual(len(list(Path("/proc/self/fd").iterdir())), before)

    def test_rejects_nonobject_or_invalid_json(self):
        for payload in (b"[]", b"{", b"\xff"):
            with self.subTest(payload=payload):
                left, right = self.pair()
                left.send(payload)
                with self.assertRaises(SplitterError):
                    receive(right)

    def test_rejects_uid_spoofing_in_request(self):
        left, right = self.pair()
        manager = Manager(Path("/unused"), MagicMock())
        send(left, {"version": 1, "op": "status", "uid": 1001})
        with (
            patch("vpn_splitter.service.credentials", return_value=(123, 1000, 1000)),
            patch("vpn_splitter.service.pwd.getpwuid") as user,
        ):
            user.return_value.pw_shell = "/bin/bash"
            handle(right, manager)
        result, _ = receive(left)
        self.assertFalse(result["ok"])
        self.assertEqual(manager.sessions, {})

    def test_client_rejects_a_service_with_wrong_owner(self):
        with tempfile.TemporaryDirectory() as root:
            path = str(Path(root) / "sock")
            with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as listener:
                listener.bind(path)
                listener.listen(1)
                with self.assertRaises(SplitterError):
                    Client(path, expected_uid=os.getuid() + 1).request("status")

    def test_real_local_protocol_dispatches_status(self):
        with tempfile.TemporaryDirectory() as root:
            path = str(Path(root) / "sock")
            manager = Manager(Path(root), MagicMock())
            with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as listener:
                listener.bind(path)
                listener.listen(1)

                def server():
                    connection, _ = listener.accept()
                    with (
                        patch("vpn_splitter.service.credentials", return_value=(123, 1000, 1000)),
                        patch("vpn_splitter.service.pwd.getpwuid") as user,
                    ):
                        user.return_value.pw_shell = "/bin/bash"
                        handle(connection, manager)

                worker = threading.Thread(target=server)
                worker.start()
                result = Client(path, expected_uid=os.getuid()).request("status")
                worker.join(timeout=2)
                self.assertFalse(worker.is_alive())
                self.assertEqual(result["state"], "disconnected")
