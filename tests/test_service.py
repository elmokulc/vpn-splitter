import os
import socket
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from vpn_splitter.model import SplitterError
from vpn_splitter.service import Manager

CONFIG = {"address": "10.0.0.7", "mtu": 1406, "dns": ["10.0.0.1"]}


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.backend = MagicMock()
        self.backend.pids.return_value = []
        self.manager = Manager(Path(self.temp.name), self.backend)

    def begin(self, uid=1000):
        return self.manager.begin(uid, "work")["token"]

    def attach(self, uid=1000, token=None):
        token = token or self.begin(uid)
        channel, peer = socket.socketpair()
        self.addCleanup(channel.close)
        self.addCleanup(peer.close)
        fd = os.open("/dev/null", os.O_RDWR)
        self.addCleanup(os.close, fd)
        self.backend.configure.return_value = fd
        self.manager.attach(uid, CONFIG, token, channel)
        return channel

    def test_selected_app_blocks_when_tunnel_drops(self):
        channel = self.attach()
        self.assertEqual(self.manager.status(1000)["state"], "connected")
        self.manager.detach(1000, channel)
        self.assertEqual(self.manager.status(1000)["state"], "blocked")
        self.backend.block.assert_called_with(1000)
        with self.assertRaises(SplitterError):
            self.manager.launch(1000, ["/bin/true"], {}, False)

    def test_failed_prepare_never_creates_an_active_session(self):
        self.backend.create.side_effect = SplitterError("no capability")
        with self.assertRaises(SplitterError):
            self.manager.prepare(1000, "work")
        self.assertEqual(self.manager.status(1000)["state"], "disconnected")

    def test_resolver_mounts_remain_readable_under_the_service_umask(self):
        previous = os.umask(0o077)
        try:
            self.manager.prepare(1000, "work")
        finally:
            os.umask(previous)
        directory = Path(self.temp.name) / "sessions/1000"
        self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        for filename in ("resolv.conf", "nsswitch.conf"):
            self.assertEqual(stat.S_IMODE((directory / filename).stat().st_mode), 0o644)
        self.assertEqual(stat.S_IMODE((directory / "session.json").stat().st_mode), 0o600)

    def test_failed_configure_is_blocked(self):
        token = self.begin()
        self.backend.configure.side_effect = SplitterError("setup failed")
        with self.assertRaises(SplitterError):
            self.manager.attach(1000, CONFIG, token, MagicMock())
        self.backend.block.assert_called_once_with(1000)
        self.assertIsNone(self.manager.sessions[1000].channel)

    def test_users_cannot_access_each_others_session(self):
        self.attach(1000)
        self.assertEqual(self.manager.status(1001)["state"], "disconnected")
        self.manager.disconnect(1001)
        self.assertEqual(self.manager.status(1000)["state"], "connected")

    def test_reset_refuses_live_or_orphaned_namespace_processes(self):
        self.manager.prepare(1000, "work")
        self.backend.pids.return_value = [42]
        with self.assertRaises(SplitterError):
            self.manager.reset(1000)
        self.backend.remove.assert_not_called()

    def test_status_reports_orphaned_processes_after_the_launcher_has_exited(self):
        self.manager.prepare(1000, "work")
        self.backend.pids.return_value = [901, 902]
        self.manager.children[1000] = []
        self.assertEqual(self.manager.status(1000)["applications"], [901, 902])

    def test_restore_is_always_blocked(self):
        self.manager.prepare(1000, "work")
        second = Manager(Path(self.temp.name), self.backend)
        second.restore()
        self.assertEqual(second.status(1000)["state"], "blocked")
        self.backend.block.assert_called_with(1000)

    def test_stale_connection_cannot_disconnect_a_new_attempt(self):
        old_token = self.begin()
        self.manager.disconnect(1000)
        current_token = self.begin()
        self.manager.end(1000, old_token)
        self.assertEqual(self.manager.sessions[1000].token, current_token)

    def test_parallel_attempt_is_refused(self):
        self.begin()
        with self.assertRaises(SplitterError):
            self.begin()

    def test_stale_attachment_cannot_connect_after_disconnect(self):
        token = self.begin()
        self.manager.disconnect(1000)
        with self.assertRaises(SplitterError):
            self.manager.attach(1000, CONFIG, token, MagicMock())
        self.backend.configure.assert_not_called()

    def test_launch_rejects_privileged_environment(self):
        self.attach()
        with self.assertRaises(SplitterError):
            self.manager.launch(1000, ["/bin/true"], {"LD_PRELOAD": "/tmp/bad"}, False)
        self.backend.launch.assert_not_called()

    def test_explicit_offline_launch_stays_in_its_namespace(self):
        self.manager.prepare(1000, "work")
        self.backend.launch.return_value.pid = 1234
        result = self.manager.launch(1000, ["/bin/true"], {}, True)
        self.assertEqual(result["namespace"], "vps-1000")
        self.backend.launch.assert_called_once_with(1000, ["/bin/true"], {})

    def test_disconnect_revokes_bridge_and_retains_namespace(self):
        self.attach()
        self.manager.disconnect(1000)
        self.assertIsNone(self.manager.sessions[1000].channel)
        self.assertEqual(self.manager.status(1000)["state"], "blocked")
        self.backend.remove.assert_not_called()
