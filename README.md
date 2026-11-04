# VPN Splitter

Launch selected native applications through an **OpenConnect / Cisco AnyConnect VPN** while other applications keep their direct connection.

The working VPN implementation uses **Python 3.11+, GTK 3/VTE and a privileged Linux namespace service**. A **native macOS Apple Silicon configuration preview** is under development; it does not yet connect or protect applications. See the [macOS development guide](docs/v1-macos.md), [current architecture](architecture.md), [Linux guide](docs/v1-linux.md), [validation record](docs/validation-linux.md) and [known issues](docs/issues.md). The [original cross-platform study](docs/research-and-design.md) describes prospective Tauri/Rust work.

## Release downloads

Publishing a GitHub release runs the **Release packages** workflow. After both platform builds pass, the release receives the Debian `.deb`, the Apple Silicon preview `.app.zip`, and `SHA256SUMS`. The ZIP contains `VPN Splitter Preview.app` with executable permissions and macOS metadata preserved. The macOS artifact remains a configuration preview, ad-hoc signed and not notarized; it does not provide VPN protection.

The workflow can also be run manually from **Actions → Release packages → Run workflow** to download build artifacts without publishing a release. See the [release guide](docs/releases.md) for version/tag requirements, checksums and build limits.

## macOS Apple Silicon development preview

The SwiftUI preview edits local VPN profiles, validates and rechecks the signatures of selected `.app` bundles and shows prerequisites. A separate, compile-only Network Extension laboratory is available for development. The OpenConnect relay and network protection are **not implemented**; saving an application selection does not change its network access. See the [macOS laboratory](docs/macos-laboratory.md) for its scope and signing requirements.

On a Mac with full Xcode 15+, Swift 5.9+ and Python 3.11+ (standalone Command Line Tools do not include XCTest, required by the native tests):

```sh
make macos-app
open 'dist/VPN Splitter Preview.app'
```

If the active developer directory is `/Library/Developer/CommandLineTools`, use `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer make macos-app`. See the [toolchain setup](docs/v1-macos.md#build-and-run-on-a-mac) for details.

The bundle targets arm64 and macOS 13+. Its ad-hoc signature is for local development, not distribution. Native tests and bundle compilation have passed on an Apple Silicon Mac; GUI and network validation remain pending. See the [build instructions, implementation stages and acceptance checks](docs/v1-macos.md).

## Build and install on Debian / Ubuntu

```sh
make check
python3 packaging/build_deb.py
sudo apt install ./dist/vpn-splitter_0.1.5_all.deb
sudo usermod -aG vpn-splitter "$USER"
```

Log out and back in after first joining the group. Installation starts a root service; only members of `vpn-splitter` can ask it to prepare their own isolated network. **Run the interface and OpenConnect without sudo.** Before upgrading, quit the old interface and close protected applications; package installation restarts the service.

```sh
vpn-splitter doctor
vpn-splitter gui
```

**About** shows the version loaded by the running interface. Quit and reopen after upgrading to load the new version.

Create an HTTPS VPN profile, enter the username and optional group/CA, then connect. Enter the password and optional OTP in the embedded terminal. Add applications using absolute executable paths, then choose **Launch in VPN**.

The window close button hides the interface and keeps the tunnel running. Run `vpn-splitter gui` to show it again; a tray icon is available on desktops supporting notification icons. **Quit** checks for remaining VPN processes, including background descendants, and warns before disconnecting. Applications left running stay isolated and blocked.

## Command line

```sh
vpn-splitter profile work --name Work --server https://vpn.example.org --username alice
vpn-splitter connect work
# In another terminal:
vpn-splitter run -- /usr/bin/curl https://intranet.example.org
vpn-splitter status
vpn-splitter disconnect
```

Launched applications are detached and their terminal output is discarded. For an interactive shell, launch a native terminal inside the VPN, such as `vpn-splitter run -- /usr/bin/xterm`, then run SSH/curl there. Install `xterm` if needed.

## Separate application instances

Chrome/Chromium and VS Code automatically receive a persistent VPN-only `--user-data-dir`. Their usual desktop instances can keep using their normal profiles. Personal accounts, cookies, settings and extensions are not copied. Sign in and configure the VPN instance separately; those settings persist across VPN launches. Supplying a conflicting `--user-data-dir` is refused.

VPN application directories live under `~/.local/share/vpn-splitter/instances/`. Private XDG directories also separate configuration for applications respecting XDG. Applications overriding those paths or sharing external services require separate validation. A new tab, `--new-window`, incognito mode or a Chrome sub-profile alone does not create an independent network process. See the [Chromium documentation](https://chromium.googlesource.com/chromium/src/+/HEAD/docs/user_data_dir.md) and [VS Code CLI](https://code.visualstudio.com/docs/configure/command-line).

**Codex/ChatGPT desktop isolation is not validated. Do not launch the application hosting your active support conversation through VPN Splitter.** See [ISSUE-003](docs/issues.md#issue-003--codexchatgpt-desktop-isolation-is-not-validated).

For native Firefox, create a dedicated profile and force a separate instance:

```sh
firefox -CreateProfile vpn-work
vpn-splitter add-app work "Work Firefox" -- /usr/bin/firefox --no-remote -P vpn-work
```

VPN connection profiles are stored in `~/.config/vpn-splitter/` (or `$XDG_CONFIG_HOME/vpn-splitter/`) without passwords or authentication cookies. VPN application data is separate from these connection profiles and may contain the accounts/cookies saved by those applications. No VPN service or account is supplied by this project.

## Scope and limitations

- One active tunnel/profile per user; applications are selected when launched. Existing processes and connections cannot be moved.
- IPv4 TCP/UDP; IPv6 is disabled inside the isolated network. The gateway must supply IPv4 DNS servers.
- Password and OTP forms through OpenConnect. Browser SSO, client certificates and posture checks are outside V1.
- Native applications only. Snap, Flatpak, shared portals/services and some desktop features are unsupported. Session D-Bus access is disabled for protected applications.
- The gateway must allow the destination. An enterprise VPN without Internet egress cannot provide it through this client.
- “Tunnel attached” means the packet bridge is ready. OpenConnect reconnection details remain visible in the terminal.
- Network isolation is not a sandbox against hostile applications. Applications keep the user's filesystem permissions.

## Development and validation

Use the system Python; GTK bindings come from distribution packages.

```sh
make check  # Standard-library unit tests and Python compilation
make run    # GTK interface from source
make deb    # Check and build the Debian package
# Kernel test, without sudo, in disposable namespaces:
unshare --user --map-root-user --mount --net python3 tests/integration/network_check.py
```

For optional linting, install development dependencies in a virtual environment (`pip install -e '.[dev]'`), then run `make lint`. GTK requires `python3-gi`, `gir1.2-gtk-3.0` and `gir1.2-vte-2.91`. The privileged service must use a root-owned installed package; never run it from a user-writable checkout.

The kernel check requires TUN, iproute2 and user namespaces, and refuses execution as root in the host namespace. It does not validate Cisco compatibility or service installation by itself. See the [Linux guide](docs/v1-linux.md) for ocserv, GUI checks and real-gateway testing. This is an early release with the [validation limits](docs/validation-linux.md) stated explicitly.

## Recover an application launched by an older version

Closing windows may leave a background process using its normal profile inside the VPN. Reopening from the desktop can reuse it. **Keep the VPN connected if your communication application depends on it.**

The recovery tool starts a worker through the user systemd manager to return the chosen application to the normal network. It diagnoses only by default:

```sh
python3 tools/recover_desktop.py chrome
# After saving work and agreeing to close the selected application:
python3 tools/recover_desktop.py chrome --restart
```

Targets are `chrome`, `code` and `chatgpt` at their standard native paths. The tool only stops the chosen application's main processes belonging to the current user and VPN namespace. It uses SIGTERM, never SIGKILL, and does not edit profile data. **The `chatgpt` target can also close Codex and this conversation's active tools**, depending on the installed package. Plan recovery before running it. Logs are written to `build/`. See the [incident recovery guide](docs/incident-recovery.md).

## License

Original project code and documentation are available under the [MIT License](LICENSE). Runtime dependencies, including OpenConnect and GTK/VTE, retain their own licenses. They are not relicensed by this repository.
