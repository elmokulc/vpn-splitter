import tempfile
import unittest
from pathlib import Path

from vpn_splitter.instances import instance_plan, prepare_instance
from vpn_splitter.model import SplitterError


class InstancesTest(unittest.TestCase):
    def test_chrome_gets_a_persistent_vpn_data_directory_distinct_from_personal_profile(self):
        home = Path("/home/alice")
        argv, environment, root = instance_plan(["/usr/bin/google-chrome", "--new-window"], home)
        self.assertIn(f"--user-data-dir={root}/user-data", argv)
        self.assertNotEqual(root / "user-data", home / ".config/google-chrome")
        self.assertEqual(argv[-1], "--new-window")
        self.assertEqual(instance_plan(["/usr/bin/google-chrome"], home)[2], root)
        self.assertEqual(environment["XDG_CONFIG_HOME"], str(root / "config"))

    def test_chrome_aliases_use_the_same_vpn_profile(self):
        home = Path("/home/alice")
        roots = [
            instance_plan([path], home)[2]
            for path in (
                "/usr/bin/google-chrome",
                "/usr/bin/google-chrome-stable",
                "/opt/google/chrome/chrome",
            )
        ]
        self.assertEqual(len(set(roots)), 1)

    def test_code_uses_a_separate_instance_even_with_a_new_window_argument(self):
        argv, _, root = instance_plan(
            ["/usr/bin/code", "--new-window", "/home/alice/project"], Path("/home/alice")
        )
        self.assertIn(f"--user-data-dir={root}/user-data", argv)
        self.assertEqual(argv[-1], "/home/alice/project")

    def test_refuses_an_explicit_normal_browser_profile_instead_of_reusing_it(self):
        for options in (
            ["--user-data-dir=/home/alice/.config/google-chrome"],
            ["--user-data-dir", "/home/alice/.config/google-chrome"],
            ["--user-data-dir"],
        ):
            with self.subTest(options=options), self.assertRaises(SplitterError):
                instance_plan(["/usr/bin/google-chrome", *options], Path("/home/alice"))

    def test_chatgpt_gets_private_xdg_configuration_without_unsupported_flags(self):
        argv, environment, root = instance_plan(["/usr/lib/chatgpt/ChatGPT"], Path("/home/alice"))
        self.assertEqual(argv, ["/usr/lib/chatgpt/ChatGPT"])
        self.assertEqual(root.name, "chatgpt")
        self.assertEqual(environment["XDG_CONFIG_HOME"], str(root / "config"))

    def test_different_applications_do_not_share_singleton_configuration(self):
        a = instance_plan(["/opt/app-a/program"], Path("/home/alice"))[2]
        b = instance_plan(["/opt/app-b/program"], Path("/home/alice"))[2]
        self.assertNotEqual(a, b)

    def test_creates_only_vpn_configuration_and_preserves_the_normal_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            personal = home / ".config/google-chrome"
            personal.mkdir(parents=True)
            marker = personal / "Preferences"
            marker.write_text("unchanged")
            argv, environment = prepare_instance(
                ["/usr/bin/google-chrome"], home, {"DISPLAY": ":0"}
            )
            self.assertEqual(marker.read_text(), "unchanged")
            self.assertEqual(environment["DISPLAY"], ":0")
            self.assertTrue(Path(environment["XDG_CONFIG_HOME"]).is_dir())
            self.assertNotIn(str(personal), " ".join(argv))
