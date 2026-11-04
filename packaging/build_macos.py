#!/usr/bin/env python3
"""Build an arm64 macOS configuration preview; no network extension is installed."""

from __future__ import annotations

import argparse
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from vpn_splitter import __version__


def build(output: Path) -> Path:
    if sys.platform != "darwin":
        raise RuntimeError("The macOS preview requires macOS 13+ and Xcode 15+ or its CLI tools")
    package = ROOT / "native/macos"
    command = [
        "xcrun",
        "swift",
        "build",
        "--package-path",
        str(package),
        "--configuration",
        "release",
        "--arch",
        "arm64",
        "--product",
        "VPNSplitterPreview",
    ]
    subprocess.run(command, check=True)
    binary_directory = Path(
        subprocess.run(
            [*command, "--show-bin-path"], check=True, capture_output=True, text=True
        ).stdout.strip()
    )
    output.mkdir(parents=True, exist_ok=True)
    target = output.resolve() / "VPN Splitter Preview.app"
    if target.exists() or target.is_symlink():
        raise RuntimeError(f"Output already exists: {target}. Move it aside before rebuilding.")
    # Assemble and sign in a temporary directory, then expose only a complete bundle.
    with tempfile.TemporaryDirectory(prefix=".macos-preview-", dir=output) as temporary:
        app = Path(temporary) / target.name
        contents = app / "Contents"
        executable = contents / "MacOS/VPNSplitterPreview"
        executable.parent.mkdir(parents=True)
        shutil.copyfile(binary_directory / "VPNSplitterPreview", executable)
        executable.chmod(0o755)
        with (contents / "Info.plist").open("wb") as stream:
            plistlib.dump(
                {
                    "CFBundleIdentifier": "org.vpnsplitter.preview",
                    "CFBundleName": "VPN Splitter Preview",
                    "CFBundleDisplayName": "VPN Splitter Preview",
                    "CFBundleExecutable": "VPNSplitterPreview",
                    "CFBundlePackageType": "APPL",
                    "CFBundleShortVersionString": __version__,
                    "CFBundleVersion": "1",
                    "LSMinimumSystemVersion": "13.0",
                    "NSHighResolutionCapable": True,
                    "NSPrincipalClass": "NSApplication",
                },
                stream,
            )
        # Ad-hoc signing is for local development only, not Developer ID distribution.
        subprocess.run(["codesign", "--sign", "-", "--options", "runtime", str(app)], check=True)
        subprocess.run(["codesign", "--verify", "--strict", str(app)], check=True)
        app.rename(target)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    try:
        print(build(args.output_dir))
        return 0
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"macOS build: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
