import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "packaging/release_version.py"
SPEC = importlib.util.spec_from_file_location("release_version", MODULE_PATH)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


class ReleaseVersionTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="vpn-splitter-release-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "src/vpn_splitter").mkdir(parents=True)
        self.write_versions()

    def write_versions(self, runtime="1.2.3", metadata="1.2.3"):
        (self.root / "src/vpn_splitter/__init__.py").write_text(f"__version__ = {runtime!r}\n")
        (self.root / "pyproject.toml").write_text(f'[project]\nversion = "{metadata}"\n')

    def test_accepts_matching_tag_with_optional_v_prefix_and_manual_build(self):
        for tag in ("", "1.2.3", "v1.2.3"):
            with self.subTest(tag=tag):
                self.assertEqual(release.release_version(self.root, tag), "1.2.3")

    def test_refuses_a_tag_that_would_mislabel_the_binaries(self):
        for tag in ("v1.2.4", "latest", "v1.2.3\n", "../v1.2.3", "v1.2.3-beta.1"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                release.release_version(self.root, tag)

    def test_refuses_inconsistent_runtime_and_package_versions(self):
        self.write_versions(metadata="1.2.4")
        with self.assertRaises(ValueError):
            release.release_version(self.root)

    def test_refuses_unsafe_or_non_numeric_version_output(self):
        for version in ("1.2.3\ninjected=value", "../1.2.3", "1.2", 123):
            self.write_versions(runtime=version)
            with self.subTest(version=version), self.assertRaises(ValueError):
                release.release_version(self.root)
