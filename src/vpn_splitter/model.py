"""Validated, secret-free user configuration."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


class SplitterError(Exception):
    """An error safe to display to the user."""


def text(value, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise SplitterError(f"Invalid {label}")
    return value


def identifier(value) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,47}", value):
        raise SplitterError("Invalid identifier (letters, digits, hyphens or underscores)")
    return value


def validate_server(value: str) -> str:
    value = text(value, "VPN address", 2048)
    try:
        url = urlsplit(value)
        port = url.port
    except ValueError as error:
        raise SplitterError("Invalid VPN address") from error
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise SplitterError("Use an HTTPS URL without credentials, query parameters or a fragment")
    if any(c.isspace() for c in value):
        raise SplitterError("The VPN address must not contain whitespace")
    return value


@dataclass
class Application:
    name: str
    argv: list[str]

    def validate(self):
        text(self.name, "Application name", 120)
        validate_argv(self.argv)
        return self


def validate_argv(argv) -> list[str]:
    if not isinstance(argv, list) or not 1 <= len(argv) <= 128:
        raise SplitterError("Invalid application command")
    for arg in argv:
        text(arg, "Argument", 4096)
    if not argv[0].startswith("/") or len(json.dumps(argv)) > 24000:
        raise SplitterError("The executable path must be absolute")
    return argv


@dataclass
class Profile:
    id: str
    name: str
    server: str
    username: str = ""
    authgroup: str = ""
    cafile: str = ""
    applications: list[Application] = field(default_factory=list)

    def validate(self):
        identifier(self.id)
        text(self.name, "Profile name", 120)
        validate_server(self.server)
        text(self.username, "Username", 256)
        text(self.authgroup, "Group", 256)
        text(self.cafile, "Certificate authority")
        if self.cafile and not self.cafile.startswith("/"):
            raise SplitterError("The CA certificate path must be absolute")
        if len(self.applications) > 100:
            raise SplitterError("Too many applications")
        for app in self.applications:
            app.validate()
        return self

    @classmethod
    def from_dict(cls, data):
        try:
            data = dict(data)
            data["applications"] = [Application(**a) for a in data.get("applications", [])]
            return cls(**data).validate()
        except (TypeError, ValueError, KeyError) as error:
            raise SplitterError("Invalid profile") from error


class ProfileStore:
    def __init__(self, root: Path | None = None):
        self.root = (
            root
            or Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "vpn-splitter"
        )

    def load(self, profile_id: str) -> Profile:
        try:
            data = json.loads((self.root / f"{identifier(profile_id)}.json").read_text())
            profile = Profile.from_dict(data)
        except (OSError, json.JSONDecodeError) as error:
            raise SplitterError("Cannot read the profile") from error
        if profile.id != profile_id:
            raise SplitterError("The file identifier does not match the profile")
        return profile

    def list(self) -> list[Profile]:
        return [self.load(p.stem) for p in sorted(self.root.glob("*.json"))]

    def save(self, profile: Profile):
        profile.validate()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(prefix=".profile-", dir=self.root)
        try:
            with os.fdopen(fd, "w") as output:
                json.dump(asdict(profile), output, ensure_ascii=False, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.root / f"{profile.id}.json")
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def tunnel_config(environment) -> dict:
    """Treat gateway-supplied values as untrusted input, never as shell fragments."""
    try:
        address = ipaddress.IPv4Address(environment["INTERNAL_IP4_ADDRESS"])
        mtu = int(environment.get("INTERNAL_IP4_MTU") or "1406")
        dns = [
            str(ipaddress.IPv4Address(v)) for v in environment.get("INTERNAL_IP4_DNS", "").split()
        ]
    except (KeyError, ValueError, TypeError) as error:
        raise SplitterError("Invalid VPN IPv4 settings") from error
    if (
        address.is_unspecified
        or address.is_multicast
        or address.is_loopback
        or not 576 <= mtu <= 9000
    ):
        raise SplitterError("Unsupported VPN address or MTU")
    if not dns or len(dns) > 8:
        raise SplitterError("The VPN must supply between one and eight IPv4 DNS servers")
    for value in dns:
        parsed = ipaddress.IPv4Address(value)
        if parsed.is_unspecified or parsed.is_multicast or parsed.is_loopback:
            raise SplitterError("Unsupported VPN DNS server")
    return {"address": str(address), "mtu": mtu, "dns": dns}
