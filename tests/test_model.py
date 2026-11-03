import json
import stat
import tempfile
import unittest
from pathlib import Path

from vpn_splitter.cli import openconnect_command
from vpn_splitter.model import Application, Profile, ProfileStore, SplitterError, tunnel_config


class ProfilesTest(unittest.TestCase):
    def test_profile_roundtrip_preserves_argv_and_restricts_permissions(self):
        with tempfile.TemporaryDirectory() as root:
            store = ProfileStore(Path(root) / "profiles")
            profile = Profile(
                "work",
                "Work",
                "https://vpn.example.test",
                applications=[
                    Application("Browser", ["/usr/bin/firefox", "--profile", "/tmp/with spaces"]),
                ],
            )
            store.save(profile)
            self.assertEqual(store.load("work"), profile)
            self.assertEqual(stat.S_IMODE((store.root / "work.json").stat().st_mode), 0o600)
            self.assertNotIn("password", (store.root / "work.json").read_text())
            store.save(profile)
            self.assertEqual(len(list(store.root.iterdir())), 1)

    def test_rejects_secret_fields_and_path_traversal(self):
        for change in ({"password": "not-a-real-password"}, {"id": "../../etc/shadow"}):
            with self.subTest(change=change), self.assertRaises(SplitterError):
                Profile.from_dict(
                    {"id": "work", "name": "Work", "server": "https://vpn.test", **change}
                )

    def test_rejects_insecure_and_credential_bearing_urls(self):
        for server in (
            "http://vpn.test",
            "https://u:p@vpn.test",
            "--script=/tmp/bad",
            "https://vpn.test?cookie=bad",
            "https://vpn.test\n",
            "https://vpn.test:99999",
        ):
            with self.subTest(server=server), self.assertRaises(SplitterError):
                Profile("work", "Work", server).validate()

    def test_rejects_malformed_applications(self):
        for argv in ([], ["firefox"], ["/bin/echo", "bad\x00arg"], "/bin/sh"):
            with self.subTest(argv=argv), self.assertRaises(SplitterError):
                Application("app", argv).validate()

    def test_rejects_profile_id_mismatch(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            (path / "work.json").write_text(
                json.dumps({"id": "other", "name": "x", "server": "https://vpn.test"})
            )
            with self.assertRaises(SplitterError):
                ProfileStore(path).load("work")

    def test_openconnect_runs_without_password_arguments_or_host_vpnc_script(self):
        argv = openconnect_command(
            Profile("work", "Work", "https://vpn.test", "-someone", "group"), "/run/test.sock"
        )
        self.assertIn("--script-tun", argv)
        self.assertIn("--disable-ipv6", argv)
        self.assertIn("--user=-someone", argv)
        self.assertNotIn("--passwd-on-stdin", argv)
        self.assertFalse(any("vpnc-script" in value for value in argv))
        self.assertEqual(argv[-1], "https://vpn.test")

    def test_script_tunnel_disables_optional_vhost_acceleration(self):
        argv = openconnect_command(Profile("work", "Work", "https://vpn.test"), "/run/test.sock")
        queues = [int(arg.split("=", 1)[1]) for arg in argv if arg.startswith("--queue-len=")]
        self.assertEqual(len(queues), 1)
        self.assertGreater(queues[0], 0)
        self.assertLess(queues[0], 16)
        self.assertIn("--script-tun", argv)


class ConfigurationTest(unittest.TestCase):
    def test_normalizes_gateway_config(self):
        result = tunnel_config(
            {"INTERNAL_IP4_ADDRESS": "10.0.0.7", "INTERNAL_IP4_DNS": "10.0.0.1 10.0.0.2"}
        )
        self.assertEqual(
            result, {"address": "10.0.0.7", "mtu": 1406, "dns": ["10.0.0.1", "10.0.0.2"]}
        )

    def test_rejects_unsafe_or_missing_gateway_values(self):
        base = {"INTERNAL_IP4_ADDRESS": "10.0.0.7", "INTERNAL_IP4_DNS": "10.0.0.1"}
        for override in (
            {"INTERNAL_IP4_ADDRESS": "10.0.0.7;id"},
            {"INTERNAL_IP4_ADDRESS": "127.0.0.1"},
            {"INTERNAL_IP4_DNS": "127.0.0.53"},
            {"INTERNAL_IP4_DNS": ""},
            {"INTERNAL_IP4_DNS": "::1"},
            {"INTERNAL_IP4_MTU": "99999"},
        ):
            with self.subTest(override=override), self.assertRaises(SplitterError):
                tunnel_config({**base, **override})
