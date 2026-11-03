import contextlib
import io
import json
import subprocess
import sys
import unittest
from unittest.mock import patch

from vpn_splitter import cli, macos


class MacOSPreviewTest(unittest.TestCase):
    def test_prerequisites_never_report_network_protection(self):
        with patch.object(macos.shutil, "which", return_value="/opt/homebrew/bin/tool"):
            report, ready = macos.doctor()
        self.assertFalse(ready)
        self.assertFalse(report["connected"])
        self.assertFalse(report["applications_protected"])
        self.assertTrue(report["openconnect"])
        self.assertIn("private_dns", report["unimplemented"])
        self.assertIn("failure_protection", report["unimplemented"])

    def test_macos_refuses_network_and_internal_linux_commands_before_ipc(self):
        commands = (
            ["connect", "work"],
            ["prepare", "work"],
            ["disconnect"],
            ["reset"],
            ["run", "--", "/usr/bin/curl", "https://example.test"],
            ["service"],
            ["_hook", "/tmp/not-a-socket"],
            ["_tun-fd", "3"],
            ["_app", "1000", "/tmp", "3", "[]"],
        )
        with patch.object(cli.sys, "platform", "darwin"), patch.object(cli, "Client") as client:
            for command in commands:
                with self.subTest(command=command), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(cli.main(command), 1)
            client.assert_not_called()

    def test_darwin_doctor_is_json_and_never_opens_the_linux_service(self):
        output = io.StringIO()
        with patch.object(cli.sys, "platform", "darwin"), patch.object(cli, "Client") as client:
            with contextlib.redirect_stdout(output):
                self.assertEqual(cli.main(["doctor"]), 1)
            client.assert_not_called()
        self.assertFalse(json.loads(output.getvalue())["applications_protected"])

    def test_status_reports_unavailable_without_claiming_apps_are_blocked(self):
        output = io.StringIO()
        with patch.object(cli.sys, "platform", "darwin"), contextlib.redirect_stdout(output):
            self.assertEqual(cli.main(["status"]), 0)
        self.assertEqual(json.loads(output.getvalue())["stage"], "development-preview")

    def test_cli_import_does_not_load_the_linux_adapter(self):
        # A fresh process catches eager imports hidden by the rest of the test suite.
        subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; import vpn_splitter.cli; "
                "assert 'vpn_splitter.linux' not in sys.modules",
            ],
            check=True,
            capture_output=True,
        )

    def test_linux_launch_still_filters_environment_after_lazy_adapter_loading(self):
        with patch.object(cli.sys, "platform", "linux"), patch.object(cli, "Client") as client:
            client.return_value.request.return_value = {"pid": 123}
            with patch.dict(cli.os.environ, {"DISPLAY": ":99", "LD_PRELOAD": "/tmp/bad.so"}):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.main(["run", "--", "/usr/bin/true"]), 0)
            values = client.return_value.request.call_args.kwargs
            self.assertEqual(values["argv"], ["/usr/bin/true"])
            self.assertEqual(values["environment"]["DISPLAY"], ":99")
            self.assertNotIn("LD_PRELOAD", values["environment"])
