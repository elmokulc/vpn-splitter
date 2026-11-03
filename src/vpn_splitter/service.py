"""Root service with a narrow, per-UID Unix socket API."""

from __future__ import annotations

import grp
import json
import logging
import os
import pwd
import re
import secrets
import shutil
import signal
import socket
import threading
from dataclasses import dataclass
from pathlib import Path

from .ipc import credentials, receive, send
from .linux import ALLOWED_ENVIRONMENT, LinuxBackend, trusted_install
from .model import SplitterError, identifier, text, tunnel_config, validate_argv

LOG = logging.getLogger(__name__)


@dataclass
class Session:
    uid: int
    profile: str
    state: str = "blocked"
    channel: socket.socket | None = None
    token: str | None = None


def validate_config(config) -> dict:
    if (
        not isinstance(config, dict)
        or set(config) != {"address", "mtu", "dns"}
        or not isinstance(config["dns"], list)
        or not all(isinstance(v, str) for v in config["dns"])
        or not isinstance(config["mtu"], int)
    ):
        raise SplitterError("Invalid tunnel configuration")
    return tunnel_config(
        {
            "INTERNAL_IP4_ADDRESS": config["address"],
            "INTERNAL_IP4_MTU": str(config["mtu"]),
            "INTERNAL_IP4_DNS": " ".join(config["dns"]),
        }
    )


class Manager:
    def __init__(self, runtime: Path, backend=None):
        self.runtime = runtime
        self.backend = backend or LinuxBackend(runtime)
        self.sessions: dict[int, Session] = {}
        self.children: dict[int, list] = {}
        self.lock = threading.RLock()

    def restore(self):
        """Persisted namespaces are always blocked on restart, never assumed connected."""
        for path in (self.runtime / "sessions").glob("*/session.json"):
            if not path.parent.name.isdecimal():
                continue
            uid = int(path.parent.name)
            data = json.loads(path.read_text())
            profile = identifier(data["profile"])
            self.backend.block(uid)
            self.sessions[uid] = Session(uid, profile)

    def status(self, uid: int):
        session = self.sessions.get(uid)
        active = self.children.setdefault(uid, [])
        active[:] = [p for p in active if p.poll() is None]
        return {
            "state": session.state if session else "disconnected",
            "profile": session.profile if session else None,
            "namespace": f"vps-{uid}" if session else None,
            # Wrappers may have exited while browser/Electron descendants still run.
            "applications": self.backend.pids(uid) if session else [],
            "ipv6": "blocked",
            "dns": "vpn-only" if session else None,
        }

    def prepare(self, uid: int, profile: str):
        identifier(profile)
        session = self.sessions.get(uid)
        if session:
            if session.profile != profile:
                raise SplitterError("Reset the empty session before switching profiles")
            return self.status(uid)
        directory = self.runtime / "sessions" / str(uid)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        (directory / "resolv.conf").write_text(
            "# No tunnel: external name resolution disabled\noptions attempts:1 timeout:1\n"
        )
        source = Path("/etc/nsswitch.conf").read_text()
        source, count = re.subn(r"^hosts:.*$", "hosts: files dns", source, flags=re.MULTILINE)
        (directory / "nsswitch.conf").write_text(
            source if count else source + "\nhosts: files dns\n"
        )
        # The service uses umask 0077. Mounted resolver files must still be readable
        # after the application drops to its real UID; their parent stays private.
        for filename in ("resolv.conf", "nsswitch.conf"):
            (directory / filename).chmod(0o644)
        self.backend.create(uid)
        try:
            (directory / "session.json").write_text(json.dumps({"profile": profile}))
            (directory / "session.json").chmod(0o600)
        except Exception:
            self.backend.remove(uid)
            raise
        self.sessions[uid] = Session(uid, profile)
        return self.status(uid)

    def begin(self, uid: int, profile: str):
        self.prepare(uid, profile)
        session = self.sessions[uid]
        if session.token is not None or session.channel is not None:
            raise SplitterError("A connection is already active; disconnect before trying again")
        session.token = secrets.token_hex(24)
        session.state = "connecting"
        return {"token": session.token}

    def end(self, uid: int, token: str):
        session = self.sessions.get(uid)
        if session and session.token == token:
            self.disconnect(uid)
        return self.status(uid)

    def attach(self, uid: int, config: dict, token: str, channel: socket.socket):
        config = validate_config(config)
        session = self.sessions.get(uid)
        if not session:
            raise SplitterError("Prepare a session before connecting")
        if not isinstance(token, str) or session.token is None or session.token != token:
            raise SplitterError("Stale connection attempt")
        if session.channel is not None:
            raise SplitterError("A tunnel is already attached")
        try:
            fd = self.backend.configure(uid, config)
        except Exception:
            self.backend.block(uid)
            raise
        session.channel = channel
        session.state = "connected"
        return self.status(uid), fd

    def detach(self, uid: int, channel: socket.socket):
        session = self.sessions.get(uid)
        if session and session.channel is channel:
            session.state = "blocked"
            session.channel = None
            self.backend.block(uid)

    def disconnect(self, uid: int):
        session = self.sessions.get(uid)
        if session:
            self.backend.block(uid)
            session.state = "blocked"
            channel, session.channel = session.channel, None
            session.token = None
            if channel:
                try:
                    channel.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        return self.status(uid)

    def launch(self, uid: int, argv: list[str], environment: dict, blocked: bool):
        validate_argv(argv)
        if not isinstance(environment, dict) or set(environment) - ALLOWED_ENVIRONMENT:
            raise SplitterError("Invalid application environment")
        for value in environment.values():
            text(value, "Environment")
        session = self.sessions.get(uid)
        if not session or (session.state != "connected" and not blocked):
            raise SplitterError("The VPN is not connected; launch refused")
        process = self.backend.launch(uid, argv, environment)
        self.children.setdefault(uid, []).append(process)
        return {"pid": process.pid, "namespace": f"vps-{uid}"}

    def reset(self, uid: int):
        self.disconnect(uid)
        if uid in self.sessions:
            if self.backend.pids(uid):
                raise SplitterError("Close all isolated applications before resetting")
            self.backend.remove(uid)
            del self.sessions[uid]
            shutil.rmtree(self.runtime / "sessions" / str(uid))
        return self.status(uid)


FIELDS = {
    "status": set(),
    "prepare": {"profile"},
    "begin": {"profile"},
    "end": {"token"},
    "attach": {"config", "token"},
    "disconnect": set(),
    "reset": set(),
    "launch": {"argv", "environment", "blocked"},
}


def handle(channel: socket.socket, manager: Manager):
    attached = False
    uid = None
    try:
        channel.settimeout(10)
        _, uid, _ = credentials(channel)
        if uid < 1000 or pwd.getpwuid(uid).pw_shell in ("/usr/sbin/nologin", "/bin/false"):
            raise SplitterError("The client must be a non-root desktop user")
        request, _ = receive(channel)
        operation = request.get("op")
        if (
            request.get("version") != 1
            or operation not in FIELDS
            or set(request) != {"version", "op"} | FIELDS[operation]
        ):
            raise SplitterError("Unknown request or unexpected fields")
        with manager.lock:
            if operation == "attach":
                result, fd = manager.attach(uid, request["config"], request["token"], channel)
                attached = True
                try:
                    send(channel, {"ok": True, "result": result}, fd)
                finally:
                    os.close(fd)
            else:
                if operation == "launch" and not isinstance(request["blocked"], bool):
                    raise SplitterError("Invalid launch option")
                values = {key: request[key] for key in FIELDS[operation]}
                result = getattr(manager, operation)(uid, **values)
                send(channel, {"ok": True, "result": result})
        if attached:
            channel.settimeout(None)
            channel.recv(1)  # EOF or any unexpected data revokes this attachment.
    except (SplitterError, OSError, ValueError, TypeError, KeyError) as error:
        message = (
            str(error) if isinstance(error, SplitterError) else "Operation refused or interrupted"
        )
        try:
            send(channel, {"ok": False, "error": message})
        except OSError:
            pass
    except Exception:
        LOG.exception("Unexpected service failure")
        try:
            send(channel, {"ok": False, "error": "Internal service error"})
        except OSError:
            pass
    finally:
        if attached:
            try:
                with manager.lock:
                    manager.detach(uid, channel)
            except Exception:
                LOG.exception("Failed to bring down isolated tunnel")
        channel.close()


def serve():
    if os.geteuid() != 0:
        raise SplitterError("The service requires system privileges")
    trusted_install()
    runtime = Path("/run/vpn-splitter")
    runtime.mkdir(mode=0o750, exist_ok=True)
    group = grp.getgrnam("vpn-splitter").gr_gid
    os.chown(runtime, 0, group)
    os.chmod(runtime, 0o750)
    (runtime / "sessions").mkdir(mode=0o700, exist_ok=True)
    manager = Manager(runtime)
    manager.restore()
    path = runtime / "control.sock"
    path.unlink(missing_ok=True)
    stopped = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stopped.set())
    slots = threading.BoundedSemaphore(24)
    with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as listener:
        listener.bind(str(path))
        os.chown(path, 0, group)
        os.chmod(path, 0o660)
        listener.listen(16)
        listener.settimeout(0.5)
        while not stopped.is_set():
            try:
                channel, _ = listener.accept()
            except socket.timeout:
                continue
            if not slots.acquire(blocking=False):
                channel.close()
                continue

            def worker(connection=channel):
                try:
                    handle(connection, manager)
                finally:
                    slots.release()

            threading.Thread(target=worker, daemon=True).start()
        with manager.lock:
            for uid in manager.sessions:
                manager.disconnect(uid)
    path.unlink(missing_ok=True)
