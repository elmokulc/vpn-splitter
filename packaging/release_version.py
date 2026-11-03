#!/usr/bin/env python3
"""Reject release tags that would mislabel the Debian package or macOS bundle."""

from __future__ import annotations

import argparse
import re
import runpy
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def release_version(root: Path, tag: str = "") -> str:
    version = runpy.run_path(str(root / "src/vpn_splitter/__init__.py"))["__version__"]
    metadata = tomllib.loads((root / "pyproject.toml").read_text())
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("Release versions must use the numeric MAJOR.MINOR.PATCH format")
    if metadata["project"]["version"] != version:
        raise ValueError("pyproject.toml and vpn_splitter.__version__ must match")
    if tag and tag not in (version, f"v{version}"):
        raise ValueError(f"Release tag must be {version} or v{version}, got {tag!r}")
    return version


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="", help="Published release tag; empty for a CI dry run")
    args = parser.parse_args()
    try:
        print(release_version(ROOT, args.tag))
        return 0
    except (OSError, ValueError, KeyError) as error:
        print(f"Release version: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
