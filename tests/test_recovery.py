import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "recover_desktop", Path(__file__).resolve().parents[1] / "tools/recover_desktop.py"
)
RECOVERY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECOVERY)


class RecoveryTest(unittest.TestCase):
    def test_selects_only_the_vpn_main_process_and_preserves_normal_instances(self):
        with tempfile.TemporaryDirectory() as temporary:
            proc = Path(temporary)
            vpn = proc / "vpn-net"
            direct = proc / "direct-net"
            vpn.touch()
            direct.touch()
            for pid, parent, executable, namespace in (
                (100, 1, "/usr/lib/chatgpt/ChatGPT", vpn),
                (101, 100, "/usr/lib/chatgpt/ChatGPT", vpn),
                (102, 101, "/usr/lib/chatgpt/ChatGPT", vpn),
                (200, 1, "/usr/lib/chatgpt/ChatGPT", direct),
                (300, 1, "/opt/google/chrome/chrome", vpn),
            ):
                entry = proc / str(pid)
                (entry / "ns").mkdir(parents=True)
                (entry / "exe").symlink_to(executable)
                os.link(namespace, entry / "ns/net")
                (entry / "status").write_text(f"PPid:\t{parent}\n")
            result = RECOVERY.vpn_main_processes(
                "/usr/lib/chatgpt/ChatGPT", vpn.stat().st_ino, proc
            )
            self.assertEqual(result, [100])

    def test_recovery_does_not_guess_other_apps_when_the_target_is_absent(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(RECOVERY.vpn_main_processes("/absent/app", 123, Path(temporary)), [])
