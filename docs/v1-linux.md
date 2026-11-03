# Linux V1: implementation and validation

## Implementation decision

The Debian/Ubuntu V1 uses Python 3.11+, GTK 3/VTE and the OpenConnect 9+ executable. This provides a native interface and a package without Rust compilation or pip runtime dependencies. The original Tauri/Rust design remains a future proposal; the separation between interface, service and platform adapter is preserved. See [architecture.md](../architecture.md).

OpenConnect runs as the desktop user and handles password/OTP forms in a terminal. With `--script-tun`, a hook receives IP packets over a Unix datagram socket and relays them to a TUN descriptor supplied by the service. Packet boundaries are preserved. See [non-root OpenConnect](https://www.infradead.org/openconnect/nonroot.html) and its [script-tun implementation](https://gitlab.com/openconnect/openconnect/-/blob/master/tun.c).

## Protection and lifecycle

The root service accepts requests only on `/run/vpn-splitter/control.sock`. Unix group permissions restrict access and `SO_PEERCRED` supplies the real UID; client-supplied UIDs are not accepted. The client also verifies the service's root identity. Connection attempts carry a token preventing an old connection from revoking a newer one.

Each user receives a `vps-UID` network namespace containing only `lo` and `vps0`. No host veth, NAT, route or DNS configuration is installed. IPv6 is disabled in the namespace. OpenConnect's TLS/DTLS sockets stay in the host network and feed the isolated TUN through the packet bridge.

The launch helper enters this network before executing the application. A private mount namespace supplies `resolv.conf` and `nsswitch.conf`; name resolution uses `files dns`, nscd is masked and session D-Bus delegation is disabled. The helper drops supplementary groups, root GID/UID and enables `no_new_privs` before execution. User applications never execute as root.

Since 0.1.2, applications receive private XDG directories, and Chrome/Chromium and VS Code receive a dedicated user-data directory. These directories are created **after** privileges are dropped. The helper does not copy or modify normal profiles. This prevents profile-singleton reuse for the managed applications; applications ignoring those paths need individual validation. Codex/ChatGPT support remains unvalidated; see [known issues](issues.md).

Disconnect closes the bridge and disables TUN. Service disappearance also closes the bridge control socket. Existing applications remain isolated with no direct interface added. Restored sessions are always blocked on service restart.

The hook asks the kernel to terminate it when its parent OpenConnect process disappears. This covers SIGKILL even when no packets are flowing through the datagram socket.

Applications are detached and their stdout is discarded. Use a native terminal inside the VPN for interactive commands. Existing processes cannot be moved into the network; a new window can reuse a singleton unless the application profile is separate.

## Installation and prerequisites

Intended targets: Debian 12+ and Ubuntu 24.04+, with systemd, network/mount namespaces and `/dev/net/tun`. Build with `python3 packaging/build_deb.py`, install using apt and add authorized users to `vpn-splitter`. The Debian Maintainer field currently uses a placeholder address.

The service requires a root-owned installation under `/usr/lib/vpn-splitter`, without user-writable paths. It refuses privileged execution from a user checkout. Rebuild and reinstall to change the backend. The interface and unprivileged tests work from source. Package upgrades restart the service: recover any communication applications still depending on the VPN first.

## Target-machine checks

Existing results are in the [validation record](validation-linux.md).

1. Run `vpn-splitter doctor`, create a profile and connect without sudo. Test password and OTP against the target gateway.
2. Start `vpn-splitter run -- /usr/bin/xterm`. Check `id`, internal DNS and allowed resources. The account must be the desktop user.
3. Compare the same destination from normal and isolated terminals using a controlled server or capture. Confirm that host routes and DNS stay unchanged.
4. Start a transfer inside the VPN and run `vpn-splitter disconnect`. Confirm blocking and continued direct-app connectivity.
5. Reconnect, stop OpenConnect and restart the service. Confirm no direct fallback and a blocked restored session.
6. Confirm that protected applications cannot use IPv6 even on an IPv6-capable host. Test UDP and child processes.
7. Close protected applications and run `vpn-splitter reset`. Confirm session removal.

An ocserv laboratory automates authentication and transport but does not certify every Cisco configuration. Synthetic packet checks are not real-world AnyConnect compatibility tests.

From source, with `ocserv`, `ocpasswd` and `cc` available:

```sh
unshare --user --map-root-user --mount --net python3 tests/integration/ocserv_check.py
```

The laboratory creates a certificate and dummy credentials and establishes a real tunnel without changing host networking. In its single-GID user namespace, a temporary shim replaces ocserv's forbidden `setgroups` call. That shim is laboratory-only and is never installed or used by the product. The laboratory tests transport and DNS, not ocserv privilege separation or VPN Splitter system installation.

Run the GUI check using `python3 tests/integration/gui_smoke.py` with `Xvfb` available. Existing user profiles are neither read nor modified.

## Troubleshooting and recovery

- Service inaccessible: check `id -nG`, `systemctl status vpn-splitter` and `journalctl -u vpn-splitter`. Log in again after joining the group.
- Missing TUN: check `test -c /dev/net/tun` and TUN module availability. Containers require explicit capabilities.
- Connection failure: inspect the OpenConnect terminal. Configure a private CA when needed; do not disable TLS validation.
- `Failed to open /dev/vhost-net: Permission denied` on 0.1.0: OpenConnect attempted optional acceleration before falling back. Since 0.1.1, `--queue-len=10` avoids it for the userspace relay. This may affect high-load performance and requires no extra permissions. See the [OpenConnect manual](https://www.infradead.org/openconnect/manual.html) and [ISSUE-001](issues.md#issue-001--optional-vhost-net-permission-warning).
- Profile change: disconnect, close applications from the previous profile and run `vpn-splitter reset` before connecting another profile.
- Orphaned authentication session: run `vpn-splitter disconnect`, then reconnect.
- Reset refused: `sudo ip netns pids vps-$(id -u)` includes orphan descendants. Close them before retrying.
- Normal application seems to depend on the VPN: it may reuse an older process with its personal profile in the VPN namespace. Closing windows is not always enough. Use the [targeted recovery procedure](incident-recovery.md); do not stop the service while your only communication application depends on it.
- Reserved namespace without metadata: an administrator must inspect it and confirm no remaining processes before any manual removal.
- After uninstall: namespaces are deliberately retained for remaining applications. An administrator can remove an empty namespace with `sudo ip netns delete vps-UID`. Never silently move protected applications into the host network for cleanup.

Secrets remain in OpenConnect's terminal/process and are not stored by VPN Splitter. Service logs do not repeat requests or application output. Treat manually collected logs and captures as sensitive.
