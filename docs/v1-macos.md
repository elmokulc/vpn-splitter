# macOS Apple Silicon: development preview

## Current implementation

This is a native macOS development preview with an initial network laboratory, not a working VPN release. The working network backend remains Linux-only. No applications are protected on macOS by the preview. It installs no extension, opens no tunnel, launches no selected application and changes no routes, DNS or firewall settings.

Implemented source:

- SwiftUI profile editor with HTTPS gateway, username, optional VPN group and CA path.
- Application picker using Security framework signature validation before recording the signing identifier and designated requirement. Unsigned and ad-hoc signed applications are refused. This is static inspection, not runtime flow classification, notarization verification or a compatibility claim.
- **Verify saved identities** rechecks current application files against the saved signing identifier and requirement off the UI thread. Missing executables, invalid signatures and replaced identities are reported per application. Verification does not launch applications or enable protection.
- Versioned local storage, validated fields, bounded profile/application counts, atomic replacement, private directory/file permissions and refusal of unknown fields. Passwords, OTPs and cookies have no configuration fields. A load error disables saving until the original file is backed up/repaired and the app reopened.
- Diagnostics and a backend that explicitly refuses connection, even with a valid profile. It never reports applications as blocked or protected.
- Python CLI macOS dispatch before Linux service use. `doctor` returns JSON and exit status 1 because protection is unavailable; `status` reports the development stage. Other commands return an actionable unsupported message without launching applications, OpenConnect or privileged helpers. `--version` and `--help` remain available.
- An arm64 `.app` bundle builder, Swift unit tests and a GitHub Actions macOS workflow. The workflow is configured, not evidence of an executed or passing build.
- A separate transparent-proxy laboratory provider restricted to numeric loopback TCP/UDP on port 49600, with audit-token UID/code validation, explicit blocked/control identities and startup/stop handling. `make macos-lab` compiles it and tests its policy. It is not packaged, installed, activated or included in the preview bundle; live interception remains unverified. See the [laboratory guide](macos-laboratory.md).

The native package has no third-party dependencies. SwiftUI/AppKit operations live in the app, Security operations in `VPNSplitterMacRuntime`, and NetworkExtension operations in the laboratory adapter. A small C target wraps Darwin audit-token APIs. Linux retains its existing Python/GTK implementation. Introducing Swift for Apple's native APIs does not introduce the prospective Rust/Tauri workspace.

## Build and run on a Mac

The deployment target is macOS 13+ on Apple Silicon (M-series), with Swift 5.9+, full Xcode 15+ and Python 3.11+. The native tests use XCTest, which is included in full Xcode but absent from the standalone Command Line Tools package. These are build targets, not an already validated support matrix. A newer SDK may be used. The builder always requests arm64; the running host architecture does not determine the output architecture.

```sh
xcode-select --print-path  # Check which developer tools are active
make macos-test
make macos-app          # Repeats the native tests before building
open 'dist/VPN Splitter Preview.app'
```

Install full Xcode if needed, open it once and complete its initial setup. If `xcode-select --print-path` reports `/Library/Developer/CommandLineTools`, a direct `swift test` fails with `no such module 'XCTest'`; the Makefile detects the missing test tool and reports setup instructions instead. Select Xcode in **Xcode > Settings > Locations > Command Line Tools**, or override the developer directory for one build without changing the system default:

```sh
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer make macos-app
```

Adjust the path if Xcode is installed elsewhere. The override applies to both the tests and the release build. For a direct test run, use `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcrun swift test --package-path native/macos`. See Apple's [command-line tools settings](https://developer.apple.com/documentation/xcode/configuring-command-line-tools-settings).

`make macos-app` produces `dist/VPN Splitter Preview.app`, signs it ad-hoc for local development and verifies that signature. It refuses to overwrite an existing bundle: quit the app and move the old bundle aside before rebuilding. It does not require sudo, a Developer ID certificate or OpenConnect for the configuration preview. Do not disable macOS security settings to run it.

The bundle identifier `org.vpnsplitter.preview` is a development placeholder. A distributable app/extension needs identifiers controlled by the project owner, provisioning, appropriate entitlements, Developer ID signing and notarization. Local ad-hoc signing does not meet those requirements.

Alternatively, open `native/macos/Package.swift` in Xcode to inspect/build the targets. The SwiftPM executable product is `VPNSplitterPreview`. Building a Swift package does not install a Network Extension.

The optional Python CLI can be used with a Python 3.11+ interpreter:

```sh
python3 bin/vpn-splitter doctor  # Expected exit 1 in this milestone
python3 bin/vpn-splitter status
```

## Configuration and selection boundaries

Native settings live in `~/Library/Application Support/VPN Splitter/profiles.json`, under schema version 1. The parent directory is mode 0700; the file is mode 0600. Linux profiles are not migrated or modified. CA paths and application selections can become stale after files are moved or replaced; the future connection/launch adapter must revalidate them at use time.

Select a profile in the sidebar, or use **New profile**, then **Save profile**. Application additions/removals are saved with the profile. Switching profiles or creating a new draft discards unsaved edits. The preview has no password/OTP prompt because authentication is not connected yet.

An on-disk designated requirement records the identity to verify later. A bundle path or editable `CFBundleIdentifier` must never authorize a flow on its own. The laboratory uses NetworkExtension's source-app audit token to check the user and running code against a saved requirement. Actual source-app attribution, helper processes and shared services still require live extension validation. The preview does not assume that selecting a parent bundle covers Chromium helpers, XPC services, WebKit or shared DNS resolution. No application is listed as network-compatible yet, including Codex/ChatGPT.

## Network implementation decision and gates

The initial investigation targets a transparent-proxy Network Extension packaged as a system extension for direct distribution. Apple's deployment table permits that macOS packaging; it is not a drop-in replacement for Linux network namespaces. See [TN3134: Network Extension provider deployment](https://developer.apple.com/documentation/technotes/tn3134-network-extension-provider-deployment) and the [Network Extension entitlement](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.networking.networkextension).

Two documented properties prevent treating a basic proxy as the finished backend:

- Returning `false` from a transparent proxy's new-flow handlers permits direct communication. A selected flow must never use that result as an error/unsupported fallback.
- Transparent proxy settings ignore supplied DNS settings, and matching flows continue using system DNS settings. Intercepting transport alone therefore does not demonstrate private per-application DNS.

These behaviors are documented in [NETransparentProxyProvider](https://developer.apple.com/documentation/networkextension/netransparentproxyprovider). A complementary filter/resolver strategy must be investigated and tested. It is not implemented here. Extension crash/disable behavior is also an unresolved protection requirement; an in-process “block” decision does not prove persistent kernel enforcement.

Next implementation stages, in order:

1. Build/run this native preview on Apple Silicon and validate UI, storage and signatures. Establish the app/system-extension signing targets using owner-controlled identifiers and provisioning.
2. Package and activate the initial [loopback laboratory provider](macos-laboratory.md) with valid signing/provisioning. Demonstrate selected versus control TCP/UDP flows without a global VPN route. Its policy and network-rule construction are currently unit-tested; kernel interception is not. Refuse unsupported identities before any protected launch is offered.
3. Prove a private DNS strategy and IPv6 blocking/tunneling. Prove protection after extension/worker failure, disablement, sleep and network changes. Decide whether a complementary content filter is necessary and feasible.
4. Implement the flow-to-packet TCP/UDP relay and an unprivileged OpenConnect worker. OpenConnect `--script-tun` handles IP packets, whereas transparent proxy providers expose flows; those interfaces cannot simply be wired together. Keep authentication in an unprivileged process, preserve TLS validation and keep secrets out of arguments, stored settings and diagnostics.
5. Add authenticated, versioned control IPC with kernel-backed caller identity, reconnect/lifecycle management, separate application instances and a launcher that refuses execution unless all required protection is active. There is no privileged arbitrary-exec endpoint in this milestone.
6. Validate ocserv transport, then real Cisco/OTP separately, and produce the signed/notarized installer only after the failure tests pass.

No `connected` or protected status should be introduced until selection, transport, DNS, IPv6, failure protection and signed installation are all implemented and verified. No fallback to a global OpenConnect route, proxy environment variables or PF-only application selection is authorized by the intended network contract.

## Validation record and acceptance

Initially authored November 3, 2026 on Linux, where native compilation, tests and GUI checks were unavailable. No macOS binary was built on Linux.

On November 4, 2026, the expanded suite of 21 native XCTest tests passed on an Apple Silicon Mac using Xcode's Swift 6.2.3 toolchain. This includes real static signature inspection/revalidation of TextEdit, rejection of an ad-hoc signed fixture, kernel self-audit-token extraction, policy rejection paths, closure of both flow directions and startup/stop transitions. The laboratory CLI also inspected TextEdit and generated a two-app configuration using Calculator. `make macos-lab` compiled both laboratory executables. An updated arm64 preview bundle was built and ad-hoc signed in `build/macos-development-final/`, with architecture and signature verification passing. The active standalone Command Line Tools lacked XCTest; the Makefile now reports that prerequisite before invoking Swift. Visual UI validation and actual extension/networking behavior remain pending.

`native/macos/Tests/VPNSplitterCoreTests/` covers URL/field validation, application metadata validation, configuration round trips and permissions, duplicate rejection, preservation on invalid saves, corrupt/future/secret-bearing documents and refusal to claim protection. `.github/workflows/macos.yml` runs native tests and builds/verifies the arm64 bundle on a macOS 15 runner. GitHub documents [runner labels and architectures](https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/choose-the-runner-for-a-job). The workflow has not been triggered by this change locally.

The separate **Release packages** workflow also builds this preview on macOS and packages it into a downloadable `.app.zip`, alongside the Linux `.deb`. It can run manually before publication or attach assets automatically when a release is published. See the [release guide](releases.md). Native compilation/tests succeeded in the initial [macOS CI run](https://github.com/elmokulc/vpn-splitter/actions/runs/41724389792); that run failed only at the incorrectly ordered `lipo` invocation, corrected in the release workflow change. GUI and network validation remain pending.

Before calling the preview build validated on a Mac:

1. Run native tests, build the bundle, verify arm64 and launch without sudo.
2. Save/reopen a profile, choose a signed application and CA file, remove selections, and verify file/directory permissions. Confirm no passwords/cookies are stored.
3. Try invalid HTTPS URLs, malformed signatures, missing application executables and corrupt settings. Confirm the original corrupt file is preserved and not overwritten by a new draft.
4. Inspect layout on a normal and scaled display; retain screenshots for UI review. Confirm the disabled connection control and explicit absence of network protection.
5. Compare host routes/DNS before and after every preview action. They must remain unchanged.

A future working VPN release additionally requires captures proving separate selected/direct paths to the same endpoint; TCP/UDP/QUIC, private DNS and IPv6 checks; worker/extension crashes and disablement; sleep/network changes; signature/IPC authorization failures; app updates/helpers/singletons; and install/upgrade/uninstall behavior preserving protection. These network checks are pending, not satisfied by configuration tests.
