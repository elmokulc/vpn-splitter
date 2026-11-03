"""Privileged Linux operations. No routes, DNS or forwarding on the host are changed."""

from __future__ import annotations

import ctypes
import fcntl
import os
import pwd
import re
import socket
import stat
import struct
import subprocess
from pathlib import Path

from .instances import prepare_instance
from .ipc import receive, send
from .model import SplitterError, validate_argv

ENTRY = Path(__file__).resolve().parent.parent / "entry.py"
IP = "/usr/sbin/ip"
MOUNT = "/usr/bin/mount"
INTERFACE = "vps0"
LIBC = ctypes.CDLL(None, use_errno=True)
CLONE_NEWNS = 0x00020000
CLONE_NEWNET = 0x40000000


def command(argv: list[str], **kwargs):
    try:
        return subprocess.run(
            argv, check=True, capture_output=True, text=True, timeout=10, **kwargs
        )
    except (OSError, subprocess.SubprocessError) as error:
        # Never copy arbitrary child output into logs or IPC responses.
        raise SplitterError(f"System operation failed: {Path(argv[0]).name}") from error


def in_namespace(name: str, *argv: str) -> list[str]:
    if not re.fullmatch(r"vps-[1-9][0-9]{2,9}", name):
        raise SplitterError("Invalid namespace")
    return [IP, "netns", "exec", name, *argv]


def syscall(name: str, *args):
    if getattr(LIBC, name)(*args) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def trusted_install():
    """Root must never import executable code from a user-writable checkout."""
    root = ENTRY.parent
    if root != Path("/usr/lib/vpn-splitter"):
        raise SplitterError(
            "The privileged service must use the package installed in /usr/lib/vpn-splitter"
        )
    paths = [root, *root.parents, *root.rglob("*")]
    for path in paths:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise SplitterError("The installation contains a writable or untrusted path")


class LinuxBackend:
    def __init__(self, runtime: Path):
        self.runtime = runtime

    def create(self, uid: int):
        name = f"vps-{uid}"
        if (Path("/run/netns") / name).exists():
            raise SplitterError("A reserved namespace already exists; use the recovery procedure")
        command([IP, "netns", "add", name])
        try:
            command([IP, "-n", name, "link", "set", "lo", "up"])
            command([IP, "-n", name, "tuntap", "add", "dev", INTERFACE, "mode", "tun"])
            command(
                in_namespace(
                    name,
                    "/usr/sbin/sysctl",
                    "-q",
                    "-w",
                    "net.ipv6.conf.all.disable_ipv6=1",
                    "net.ipv6.conf.default.disable_ipv6=1",
                )
            )
        except Exception:
            command([IP, "netns", "delete", name])
            raise

    def block(self, uid: int):
        command([IP, "-n", f"vps-{uid}", "link", "set", INTERFACE, "down"])

    def configure(self, uid: int, config: dict):
        name = f"vps-{uid}"
        self.block(uid)
        command([IP, "-n", name, "address", "flush", "dev", INTERFACE])
        command([IP, "-n", name, "address", "add", f"{config['address']}/32", "dev", INTERFACE])
        command([IP, "-n", name, "link", "set", INTERFACE, "mtu", str(config["mtu"]), "up"])
        command([IP, "-n", name, "route", "replace", "default", "dev", INTERFACE])
        # Keep this inode: running applications have this file bind-mounted.
        path = self.runtime / "sessions" / str(uid) / "resolv.conf"
        with path.open("w") as output:
            output.write("# VPN Splitter — Tunnel DNS only\n")
            output.writelines(f"nameserver {ip}\n" for ip in config["dns"])
            output.write("options timeout:2 attempts:2\n")
        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        try:
            parent.settimeout(5)
            process = subprocess.Popen(
                in_namespace(
                    name, "/usr/bin/python3", "-I", str(ENTRY), "_tun-fd", str(child.fileno())
                ),
                pass_fds=(child.fileno(),),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin"},
            )
            child.close()
            try:
                response, fd = receive(parent, expect_fd=True)
                if process.wait(timeout=5) != 0 or response.get("ok") is not True:
                    if fd is not None:
                        os.close(fd)
                    raise SplitterError("Cannot open the TUN device")
                return fd
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
        finally:
            parent.close()
            child.close()

    def launch(self, uid: int, argv: list[str], environment: dict):
        import json

        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        try:
            parent.settimeout(8)
            process = subprocess.Popen(
                in_namespace(
                    f"vps-{uid}",
                    "/usr/bin/python3",
                    "-I",
                    str(ENTRY),
                    "_app",
                    str(uid),
                    str(self.runtime),
                    str(child.fileno()),
                    json.dumps(argv),
                ),
                pass_fds=(child.fileno(),),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", **environment},
            )
            child.close()
            try:
                # CLOEXEC closes the handshake socket only after exec succeeds.
                failure = parent.recv(4096)
                if failure:
                    process.wait(timeout=2)
                    raise SplitterError(failure.decode("utf-8", errors="replace"))
                return process
            except Exception:
                if process.poll() is None:
                    process.kill()
                process.wait()
                raise
        finally:
            parent.close()
            child.close()

    def pids(self, uid: int):
        result = command([IP, "netns", "pids", f"vps-{uid}"])
        return [int(value) for value in result.stdout.split()]

    def remove(self, uid: int):
        command([IP, "netns", "delete", f"vps-{uid}"])


def provide_tun(fd: int):
    with socket.socket(fileno=fd) as channel:
        tun = os.open("/dev/net/tun", os.O_RDWR | os.O_CLOEXEC)
        try:
            fcntl.ioctl(tun, 0x400454CA, struct.pack("16sH", INTERFACE.encode(), 0x0001 | 0x1000))
            send(channel, {"ok": True}, tun)
        finally:
            os.close(tun)


ALLOWED_ENVIRONMENT = {
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "XAUTHORITY",
    "XDG_RUNTIME_DIR",
    "LANG",
    "LC_ALL",
}


def mount_application_dns(session: Path):
    syscall("unshare", CLONE_NEWNS)
    command([MOUNT, "--make-rprivate", "/"])
    for filename in ("resolv.conf", "nsswitch.conf"):
        command([MOUNT, "--bind", str(session / filename), f"/etc/{filename}"])
        command([MOUNT, "-o", "remount,bind,ro", f"/etc/{filename}"])
    # nscd can resolve via a host Unix socket, bypassing the private DNS settings.
    if Path("/run/nscd").is_dir():
        command([MOUNT, "-t", "tmpfs", "-o", "nosuid,nodev,noexec,size=4k", "tmpfs", "/run/nscd"])


def application_exec(uid: int, runtime: Path, ready_fd: int, argv: list[str]):
    channel = socket.socket(fileno=ready_fd)
    try:
        validate_argv(argv)
        account = pwd.getpwuid(uid)
        mount_application_dns(runtime / "sessions" / str(uid))
        environment = {
            key: value for key, value in os.environ.items() if key in ALLOWED_ENVIRONMENT
        }
        environment.update(
            {
                "HOME": account.pw_dir,
                "USER": account.pw_name,
                "LOGNAME": account.pw_name,
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "SHELL": account.pw_shell,
                "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/vpn-splitter/no-session-bus",
                "NO_AT_BRIDGE": "1",
                "GTK_USE_PORTAL": "0",
            }
        )
        os.initgroups(account.pw_name, account.pw_gid)
        os.setgid(account.pw_gid)
        os.setuid(uid)
        syscall("prctl", 38, 1, 0, 0, 0)  # PR_SET_NO_NEW_PRIVS
        argv, environment = prepare_instance(argv, Path(account.pw_dir), environment)
        os.chdir(account.pw_dir)
        channel.set_inheritable(False)
        os.execve(argv[0], argv, environment)
    except Exception as error:
        message = (
            str(error)
            if isinstance(error, SplitterError)
            else "Cannot prepare or launch the isolated application"
        )
        channel.send(message.encode("utf-8")[:3000])
        raise
    finally:
        channel.close()
