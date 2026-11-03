#!/usr/bin/python3
"""Build a Debian package without root, pip, network access or Rust."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from vpn_splitter import __version__


def build(output: Path) -> Path:
    staging = ROOT / "build" / f"vpn-splitter_{__version__}_all"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    staging.chmod(0o755)

    def install(source, destination, executable=False):
        target = staging / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / source, target)
        target.chmod(0o755 if executable else 0o644)

    install("bin/vpn-splitter", "usr/bin/vpn-splitter", True)
    install("src/entry.py", "usr/lib/vpn-splitter/entry.py")
    for source in sorted((ROOT / "src/vpn_splitter").glob("*.py")):
        install(source, f"usr/lib/vpn-splitter/vpn_splitter/{source.name}")
    install("packaging/vpn-splitter.service", "usr/lib/systemd/system/vpn-splitter.service")
    install("packaging/vpn-splitter.desktop", "usr/share/applications/vpn-splitter.desktop")
    install("packaging/vpn-splitter.svg", "usr/share/icons/hicolor/scalable/apps/vpn-splitter.svg")
    install("README.md", "usr/share/doc/vpn-splitter/README.md")
    install("architecture.md", "usr/share/doc/vpn-splitter/architecture.md")
    install("LICENSE", "usr/share/doc/vpn-splitter/LICENSE")
    install("LICENSE", "usr/share/doc/vpn-splitter/copyright")
    for document in sorted((ROOT / "docs").glob("*.md")):
        install(str(document.relative_to(ROOT)), f"usr/share/doc/vpn-splitter/docs/{document.name}")
    install("tests/integration/network_check.py", "usr/lib/vpn-splitter/network_check.py")
    control = staging / "DEBIAN"
    control.mkdir()
    (control / "control").write_text(
        f"Package: vpn-splitter\nVersion: {__version__}\nArchitecture: all\n"
        "Maintainer: VPN Splitter contributors <noreply@example.invalid>\n"
        "Section: net\nPriority: optional\n"
        "Depends: python3 (>= 3.11), python3-gi, gir1.2-gtk-3.0, gir1.2-vte-2.91, "
        "openconnect (>= 9.0), iproute2, util-linux, mount, procps, adduser, systemd\n"
        "Description: Selective OpenConnect VPN for native Linux applications\n"
        " Runs selected applications in a dedicated network namespace.\n"
        " Includes a GTK interface, CLI and privileged local service.\n"
    )
    for script in ("postinst", "prerm"):
        install(f"packaging/{script}", f"DEBIAN/{script}", True)
    for directory in staging.rglob("*"):
        if directory.is_dir():
            directory.chmod(0o755)
    output.mkdir(parents=True, exist_ok=True)
    artifact = output.resolve() / f"vpn-splitter_{__version__}_all.deb"
    subprocess.run(
        ["dpkg-deb", "--root-owner-group", "--build", str(staging), str(artifact)], check=True
    )
    return artifact


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    print(build(parser.parse_args().output_dir))
