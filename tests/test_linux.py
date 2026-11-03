import socket
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from vpn_splitter.linux import application_exec, in_namespace, trusted_install
from vpn_splitter.model import SplitterError


class LinuxTest(unittest.TestCase):
    def test_rejects_namespace_path_injection(self):
        for name in ("../host", "vps-1000;id", "default", "-a"):
            with self.subTest(name=name), self.assertRaises(SplitterError):
                in_namespace(name, "/bin/true")

    def test_root_service_refuses_a_user_checkout(self):
        with self.assertRaises(SplitterError):
            trusted_install()

    def test_application_drops_groups_gid_uid_and_privilege_escalation_before_exec(self):
        parent, child = socket.socketpair()
        self.addCleanup(parent.close)
        fd = child.detach()
        calls = []
        account = SimpleNamespace(
            pw_name="alice", pw_gid=1000, pw_dir="/home/alice", pw_shell="/bin/bash"
        )
        with (
            patch("vpn_splitter.linux.pwd.getpwuid", return_value=account),
            patch("vpn_splitter.linux.mount_application_dns") as mounts,
            patch(
                "vpn_splitter.linux.os.initgroups",
                side_effect=lambda *a: calls.append(("groups", a)),
            ),
            patch("vpn_splitter.linux.os.setgid", side_effect=lambda *a: calls.append(("gid", a))),
            patch("vpn_splitter.linux.os.setuid", side_effect=lambda *a: calls.append(("uid", a))),
            patch("vpn_splitter.linux.syscall", side_effect=lambda *a: calls.append(("prctl", a))),
            patch("vpn_splitter.linux.os.chdir"),
            patch(
                "vpn_splitter.linux.prepare_instance",
                side_effect=lambda a, h, e: calls.append(("instance", h)) or (a, e),
            ),
            patch(
                "vpn_splitter.linux.os.execve", side_effect=RuntimeError("stop before exec")
            ) as execute,
        ):
            with self.assertRaises(RuntimeError):
                application_exec(1000, Path("/run/vpn-splitter"), fd, ["/usr/bin/true"])
        self.assertEqual([name for name, _ in calls], ["groups", "gid", "uid", "prctl", "instance"])
        self.assertEqual(calls[2][1], (1000,))
        self.assertEqual(calls[3][1][:2], ("prctl", 38))
        mounts.assert_called_once_with(Path("/run/vpn-splitter/sessions/1000"))
        environment = execute.call_args.args[2]
        self.assertEqual(environment["USER"], "alice")
        self.assertEqual(
            environment["DBUS_SESSION_BUS_ADDRESS"], "unix:path=/run/vpn-splitter/no-session-bus"
        )
        self.assertNotIn("LD_PRELOAD", environment)
        self.assertIn(b"Cannot prepare or launch the isolated application", parent.recv(3000))
