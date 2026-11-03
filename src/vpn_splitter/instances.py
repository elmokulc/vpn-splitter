"""Keep application singleton state separate from the user's normal desktop."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .model import SplitterError, validate_argv

CHROMIUM_NAMES = {
    "google-chrome": "google-chrome",
    "google-chrome-stable": "google-chrome",
    "google-chrome-beta": "google-chrome-beta",
    "google-chrome-unstable": "google-chrome-unstable",
    "chromium": "chromium",
    "chromium-browser": "chromium",
}
CODE_NAMES = {"code", "code-insiders", "codium", "vscodium"}


def application_kind(executable: str) -> tuple[str, bool]:
    path = Path(executable)
    name = path.name.lower()
    if name in CHROMIUM_NAMES:
        return CHROMIUM_NAMES[name], True
    if name == "chrome" and path.parent.parent.name == "google":
        return f"google-{path.parent.name}", True
    if name in CODE_NAMES:
        return name, True
    if name == "chatgpt":
        return "chatgpt", False
    return f"app-{hashlib.sha256(executable.encode()).hexdigest()[:16]}", False


def instance_plan(argv: list[str], home: Path) -> tuple[list[str], dict[str, str], Path]:
    """Pure plan; never read, copy or alter the normal application's profile."""
    validate_argv(argv)
    key, managed_user_data = application_kind(argv[0])
    root = home / ".local/share/vpn-splitter/instances" / key
    environment = {
        "XDG_CONFIG_HOME": str(root / "config"),
        "XDG_DATA_HOME": str(root / "data"),
        "XDG_CACHE_HOME": str(root / "cache"),
        "XDG_STATE_HOME": str(root / "state"),
    }
    arguments = list(argv)
    if managed_user_data:
        # A profile-directory or a new window alone still shares Chrome's singleton.
        # Refuse conflicting custom data roots instead of opening a personal profile.
        data = str(root / "user-data")
        kept = [argv[0]]
        index = 1
        while index < len(argv):
            value = argv[index]
            if value == "--":
                kept.extend(argv[index:])
                break
            if value == "--user-data-dir":
                index += 1
                if index == len(argv) or argv[index] != data:
                    raise SplitterError(
                        "Remove --user-data-dir: VPN Splitter manages a separate VPN directory."
                    )
            elif value.startswith("--user-data-dir="):
                if value.split("=", 1)[1] != data:
                    raise SplitterError(
                        "Remove --user-data-dir: VPN Splitter manages a separate VPN directory."
                    )
            else:
                kept.append(value)
            index += 1
        arguments = [kept[0], f"--user-data-dir={data}", *kept[1:]]
    validate_argv(arguments)
    return arguments, environment, root


def prepare_instance(argv: list[str], home: Path, environment: dict) -> tuple[list[str], dict]:
    """Called only after dropping root, so profile directories belong to the user."""
    arguments, overrides, root = instance_plan(argv, home)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    for directory in overrides.values():
        Path(directory).mkdir(mode=0o700, exist_ok=True)
    return arguments, {**environment, **overrides}
