#!/usr/bin/python3
"""Restart one authorized desktop app outside VPN, without changing its profile.

Dry-run by default. --restart explicitly authorizes SIGTERM of that app's VPN
instances only. ChatGPT restart interrupts the chat hosted by that application.
"""

from __future__ import annotations

import argparse
import os
import select
import signal
import subprocess
import time
import uuid
from pathlib import Path

APPLICATIONS = {
    "chrome": ("/opt/google/chrome/chrome", ["/usr/bin/google-chrome", "--new-window"]),
    "code": ("/usr/share/code/code", ["/usr/bin/code", "--new-window"]),
    "chatgpt": ("/usr/lib/chatgpt/ChatGPT", ["/usr/lib/chatgpt/ChatGPT"]),
}


def vpn_main_processes(executable: str, inode: int, proc: Path = Path("/proc")) -> list[int]:
    candidates = set()
    for entry in proc.iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            if entry.stat().st_uid != os.getuid() or os.readlink(entry / "exe") != executable:
                continue
            if (entry / "ns/net").stat().st_ino != inode:
                continue
            candidates.add(int(entry.name))
        except OSError:
            continue
    roots = []
    for pid in sorted(candidates):
        current = pid
        seen = {pid}
        while current:
            try:
                status = (proc / str(current) / "status").read_text()
                current = int(
                    next(
                        line.split()[1] for line in status.splitlines() if line.startswith("PPid:")
                    )
                )
            except (OSError, ValueError, StopIteration):
                current = 0
            if current in candidates:
                break
            if current in seen:
                current = 0
            seen.add(current)
        if not current:
            roots.append(pid)
    return roots


def worker(application: str, restart: bool, delay: int, log_path: Path):
    with log_path.open("a") as log:

        def report(message):
            print(message, file=log, flush=True)

        if os.geteuid() == 0:
            raise RuntimeError("Run as a regular user, without sudo")
        namespace = Path(f"/run/netns/vps-{os.getuid()}")
        target = namespace.stat().st_ino
        normal = Path("/proc/self/ns/net").stat().st_ino
        if target == normal:
            raise RuntimeError("The user service manager is still in the VPN: stop refused")
        executable, command = APPLICATIONS[application]
        targets = vpn_main_processes(executable, target)
        report(f"Application: {application}; VPN processes: {targets}; normal network: {normal}")
        if not restart:
            report("Diagnostic only: no processes stopped")
            return
        time.sleep(delay)
        descriptors = []
        try:
            for pid in targets:
                try:
                    fd = os.pidfd_open(pid)
                except ProcessLookupError:
                    continue
                entry = Path(f"/proc/{pid}")
                try:
                    if (
                        entry.stat().st_uid != os.getuid()
                        or os.readlink(entry / "exe") != executable
                        or (entry / "ns/net").stat().st_ino != target
                    ):
                        os.close(fd)
                        continue
                    signal.pidfd_send_signal(fd, signal.SIGTERM)
                    descriptors.append(fd)
                except OSError:
                    os.close(fd)
            deadline = time.monotonic() + 10
            for fd in descriptors:
                poll = select.poll()
                poll.register(fd, select.POLLIN)
                remaining = max(0, int((deadline - time.monotonic()) * 1000))
                if not poll.poll(remaining):
                    report("Shutdown did not complete: no SIGKILL or forced restart")
                    return
        finally:
            for fd in descriptors:
                os.close(fd)
        subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        report("Application relaunched on the normal network; user profile preserved")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("application", choices=APPLICATIONS)
    parser.add_argument(
        "--restart", action="store_true", help="Authorize targeted shutdown and restart"
    )
    parser.add_argument("--delay", type=int, default=0, choices=range(0, 61), metavar="0..60")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--log", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        worker(args.application, args.restart, args.delay, args.log)
        return
    output = Path(__file__).resolve().parents[1] / "build"
    output.mkdir(exist_ok=True)
    log = output / f"recovery-{args.application}-{uuid.uuid4().hex[:8]}.log"
    log.touch(mode=0o600)
    environment = dict(os.environ)
    environment["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{os.getuid()}/bus"
    environment["XDG_RUNTIME_DIR"] = f"/run/user/{os.getuid()}"
    command = ["/usr/bin/systemd-run", "--user", "--collect", "--property=ExitType=cgroup"]
    for key in ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY"):
        if key in os.environ:
            command.append(f"--setenv={key}={os.environ[key]}")
    command.extend(
        [
            "/usr/bin/python3",
            str(Path(__file__).resolve()),
            args.application,
            "--worker",
            "--log",
            str(log),
            "--delay",
            str(args.delay),
        ]
    )
    if args.restart:
        command.append("--restart")
    subprocess.run(command, env=environment, check=True)
    print(f"Log: {log}", flush=True)


if __name__ == "__main__":
    main()
