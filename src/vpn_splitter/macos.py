"""macOS preview diagnostics. No Linux IPC or networking operations are permitted."""

from __future__ import annotations

import json
import os
import platform
import shutil
import sys

REQUIREMENTS = {
    "flow_selection": "Application and helper identification before traffic is emitted",
    "vpn_transport": "TCP/UDP relay to an unprivileged OpenConnect worker",
    "private_dns": "Selected applications resolve names through VPN DNS",
    "ipv6_protection": "Selected IPv6 is tunneled or blocked",
    "failure_protection": "No direct fallback after worker or extension failure",
    "signed_installation": "Provisioned and signed Network Extension installation",
}


def status() -> dict:
    return {
        "platform": "macos",
        "stage": "development-preview",
        "connected": False,
        "applications_protected": False,
        "unimplemented": REQUIREMENTS,
    }


def doctor() -> tuple[dict, bool]:
    report = {
        **status(),
        "architecture": platform.machine(),
        "macos_version": platform.mac_ver()[0],
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "swift": shutil.which("swift") is not None,
        "openconnect": shutil.which("openconnect") is not None,
        "native_preview": "make macos-app; open 'dist/VPN Splitter Preview.app'",
    }
    # Prerequisites alone never establish that network protection exists.
    return report, False


def main(command: str | None) -> int:
    if command == "doctor":
        report, ready = doctor()
        print(json.dumps(report, indent=2))
        return 0 if ready else 1
    if command == "status":
        print(json.dumps(status(), indent=2))
        return 0
    if os.geteuid() == 0:
        print("vpn-splitter: Run the macOS preview without sudo", file=sys.stderr)
        return 1
    print(
        "vpn-splitter: macOS is a configuration preview; VPN connection and protected "
        "launch are unavailable. Build the native app with 'make macos-app', then open "
        "'dist/VPN Splitter Preview.app'. See docs/v1-macos.md.",
        file=sys.stderr,
    )
    return 1
