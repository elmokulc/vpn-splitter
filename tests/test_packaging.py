import io
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which("dpkg-deb"), "dpkg-deb is required to inspect the Debian package")
class PackagingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="vpn-splitter-package-")
        cls.addClassCleanup(cls.temporary.cleanup)
        root = Path(__file__).resolve().parents[1]
        subprocess.run(
            [
                sys.executable,
                str(root / "packaging/build_deb.py"),
                "--output-dir",
                cls.temporary.name,
            ],
            check=True,
            capture_output=True,
        )
        package = next(Path(cls.temporary.name).glob("*.deb"))
        archive = subprocess.run(
            ["dpkg-deb", "--fsys-tarfile", str(package)], check=True, capture_output=True
        ).stdout
        with tarfile.open(fileobj=io.BytesIO(archive)) as contents:
            cls.members = {item.name.removeprefix("./"): item for item in contents.getmembers()}

    def test_privileged_code_is_root_owned_without_writable_paths_or_symlinks(self):
        root = self.members.get(".") or self.members.get("")
        self.assertEqual(root.mode, 0o755)
        code = [
            item for name, item in self.members.items() if name.startswith("usr/lib/vpn-splitter")
        ]
        self.assertGreater(len(code), 5)
        for item in code:
            with self.subTest(path=item.name):
                self.assertEqual((item.uid, item.gid), (0, 0))
                self.assertFalse(item.issym() or item.islnk())
                self.assertEqual(item.mode & 0o022, 0)

    def test_package_contains_executable_launcher_service_desktop_entry_and_documentation(self):
        self.assertTrue(self.members["usr/bin/vpn-splitter"].mode & 0o111)
        for name in (
            "usr/lib/systemd/system/vpn-splitter.service",
            "usr/share/applications/vpn-splitter.desktop",
            "usr/share/doc/vpn-splitter/docs/v1-linux.md",
            "usr/share/doc/vpn-splitter/docs/validation-linux.md",
            "usr/share/doc/vpn-splitter/docs/research-and-design.md",
            "usr/share/doc/vpn-splitter/docs/issues.md",
            "usr/share/doc/vpn-splitter/docs/incident-recovery.md",
            "usr/share/doc/vpn-splitter/architecture.md",
            "usr/share/doc/vpn-splitter/LICENSE",
            "usr/share/doc/vpn-splitter/copyright",
        ):
            self.assertIn(name, self.members)

    def test_package_excludes_bytecode_and_user_profiles(self):
        for name in self.members:
            with self.subTest(path=name):
                self.assertNotIn("__pycache__", name)
                self.assertFalse(name.endswith((".pyc", ".json")))
