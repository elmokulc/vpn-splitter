"""Desktop and command-line entry points; OpenConnect authentication stays unprivileged."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from . import __version__
from .ipc import SOCKET_PATH, Client
from .model import Application, Profile, ProfileStore, SplitterError


def openconnect_command(profile: Profile, socket_path: str) -> list[str]:
    from .linux import ENTRY

    profile.validate()
    hook = shlex.join(["/usr/bin/python3", "-I", str(ENTRY), "_hook", socket_path])
    argv = [
        "/usr/sbin/openconnect",
        "--protocol=anyconnect",
        "--script-tun",
        f"--script=exec {hook}",
        # vhost-net is optional and expects a kernel TUN backend. Our backend is
        # a userspace datagram relay; a queue below 16 disables that acceleration.
        "--queue-len=10",
        "--disable-ipv6",
        "--no-proxy",
        "--reconnect-timeout=60",
        "--csd-wrapper=/bin/false",
    ]
    for key in ("username", "authgroup", "cafile"):
        value = getattr(profile, key)
        if value:
            option = "user" if key == "username" else key
            argv.append(f"--{option}={value}")
    argv.append(profile.server)
    return argv


def connect(profile: Profile, client: Client) -> int:
    if os.geteuid() == 0:
        raise SplitterError("Start the connection as a regular user, without sudo")
    token = client.request("begin", profile=profile.id)["token"]
    process = None
    previous = signal.getsignal(signal.SIGTERM)

    def terminate(*_):
        if process is not None:
            process.terminate()

    signal.signal(signal.SIGTERM, terminate)
    try:
        print(
            "OpenConnect authentication: passwords and OTPs are not saved.",
            flush=True,
        )
        process = subprocess.Popen(
            openconnect_command(profile, client.path),
            env={**os.environ, "VPN_SPLITTER_TOKEN": token},
            close_fds=True,
        )
        try:
            return process.wait()
        except KeyboardInterrupt:
            process.send_signal(signal.SIGINT)
            try:
                return process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                return 130
    finally:
        signal.signal(signal.SIGTERM, previous)
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        try:
            client.request("end", token=token)
        except SplitterError:
            pass  # Existing isolated applications remain without a direct interface.


def doctor(client: Client) -> tuple[dict, bool]:
    from .linux import ENTRY

    checks = {
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "openconnect": bool(shutil.which("openconnect")),
        "iproute2": bool(shutil.which("ip")),
        "tun": Path("/dev/net/tun").exists(),
        "gtk_bindings": importlib.util.find_spec("gi") is not None,
        "installed_service": ENTRY.parent == Path("/usr/lib/vpn-splitter"),
    }
    try:
        checks["session"] = client.request("status")
        checks["service"] = True
    except SplitterError as error:
        checks["service"] = False
        checks["service_error"] = str(error)
    ready = all(checks[key] for key in ("openconnect", "iproute2", "tun", "service"))
    return checks, ready


def parser():
    result = argparse.ArgumentParser(description="Selective VPN — selected applications only")
    result.add_argument("--version", action="version", version=__version__)
    result.add_argument("--socket", default=SOCKET_PATH, help="System service socket")
    commands = result.add_subparsers(dest="command", metavar="COMMAND")
    commands.add_parser("gui", help="Open the platform interface")
    commands.add_parser("doctor", help="Check prerequisites and service access")
    commands.add_parser("status", help="Show the current user session status")
    commands.add_parser("disconnect", help="Disconnect the tunnel and keep applications isolated")
    commands.add_parser("reset", help="Remove an empty, disconnected session")
    commands.add_parser("service", help="System service (installed package only)")
    profiles = commands.add_parser("profiles", help="List local profiles")
    profiles.add_argument("--json", action="store_true")
    profile = commands.add_parser("profile", help="Create or update a profile without secrets")
    profile.add_argument("id")
    profile.add_argument("--name", required=True)
    profile.add_argument("--server", required=True)
    profile.add_argument("--username", default="")
    profile.add_argument("--authgroup", default="")
    profile.add_argument("--cafile", default="")
    for name in ("connect", "prepare"):
        sub = commands.add_parser(
            name,
            help="Connect to the VPN"
            if name == "connect"
            else "Prepare an isolated, blocked network",
        )
        sub.add_argument("profile")
    run = commands.add_parser("run", help="Launch a native application in the VPN")
    run.add_argument(
        "--blocked", action="store_true", help="Allow launching in a session without a tunnel"
    )
    run.add_argument("argv", nargs=argparse.REMAINDER)
    app = commands.add_parser("add-app", help="Save an application in a profile")
    app.add_argument("profile")
    app.add_argument("name")
    app.add_argument("argv", nargs=argparse.REMAINDER)
    hook = commands.add_parser("_hook")
    hook.add_argument("path")
    tun = commands.add_parser("_tun-fd")
    tun.add_argument("fd", type=int)
    isolated = commands.add_parser("_app")
    isolated.add_argument("uid", type=int)
    isolated.add_argument("runtime", type=Path)
    isolated.add_argument("fd", type=int)
    isolated.add_argument("argv_json")
    return result


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    if sys.platform == "darwin":
        from .macos import main as macos_main

        return macos_main(args.command)
    if sys.platform != "linux":
        print("vpn-splitter: This platform is not supported", file=sys.stderr)
        return 1
    client = Client(args.socket)
    store = ProfileStore()
    try:
        if args.command in (None, "gui"):
            if os.geteuid() == 0:
                raise SplitterError("Start the interface without sudo")
            from .gui import run

            return run(args.socket)
        if args.command == "service":
            from .service import serve

            serve()
        elif args.command == "_hook":
            from .bridge import hook

            hook(args.path)
        elif args.command == "_tun-fd":
            from .linux import provide_tun

            provide_tun(args.fd)
        elif args.command == "_app":
            from .linux import application_exec

            application_exec(args.uid, args.runtime, args.fd, json.loads(args.argv_json))
        elif args.command == "doctor":
            report, ready = doctor(client)
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 0 if ready else 1
        elif args.command == "profile":
            existing = []
            if (store.root / f"{args.id}.json").exists():
                existing = store.load(args.id).applications
            profile = Profile(
                args.id,
                args.name,
                args.server,
                args.username,
                args.authgroup,
                args.cafile,
                existing,
            )
            store.save(profile)
            print(f"Profile saved: {profile.id}")
        elif args.command == "profiles":
            profiles = store.list()
            if args.json:
                print(json.dumps([asdict(p) for p in profiles], indent=2, ensure_ascii=False))
            else:
                for profile in profiles:
                    print(f"{profile.id}\t{profile.name}\t{profile.server}")
        elif args.command in ("connect", "prepare"):
            profile = store.load(args.profile)
            if args.command == "connect":
                return connect(profile, client)
            print(json.dumps(client.request("prepare", profile=profile.id), indent=2))
        elif args.command in ("run", "add-app"):
            command = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
            if args.command == "add-app":
                profile = store.load(args.profile)
                profile.applications.append(Application(args.name, command).validate())
                store.save(profile)
                print("Application saved")
            else:
                from .linux import ALLOWED_ENVIRONMENT

                environment = {k: v for k, v in os.environ.items() if k in ALLOWED_ENVIRONMENT}
                print(
                    json.dumps(
                        client.request(
                            "launch", argv=command, environment=environment, blocked=args.blocked
                        ),
                        indent=2,
                    )
                )
        else:
            print(json.dumps(client.request(args.command), indent=2, ensure_ascii=False))
        return 0
    except (SplitterError, OSError, ValueError) as error:
        print(f"vpn-splitter : {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
