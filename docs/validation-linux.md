# Linux validation record

Date: November 3, 2026. Environment: Ubuntu 24.04, Python 3.12, OpenConnect 9.12, GTK 3/VTE. Some test tools were extracted under `/tmp` without system installation. Distinguish the initial laboratory results from subsequent installation, incident recovery and user checks.

## Initial implementation (0.1.0)

| Check | Result |
| --- | --- |
| Standard-library unit tests | 38 passed: profiles, validation, IPC identities, descriptor handling, packets, session state, package permissions and privilege-drop ordering |
| Ruff | Source, CLI, packaging and tests checked |
| Kernel TUN check | Real UDP round trip, blocking after disable, IPv6 disabled, outer network unchanged |
| OpenConnect / ocserv 1.2.4 laboratory | Password authentication with verified TLS; tunneled TCP versus direct TCP to the same destination; UDP; private NSS/DNS; blocking after SIGKILL of OpenConnect |
| GTK on Xvfb | Window, profile/application rendering, VTE launch/exit and missing-service error |
| Debian package | Built without root; metadata and contents inspected |
| systemd unit | Syntax checked using `systemd-analyze verify` |

Network laboratories use disposable user, mount and network namespaces. The ocserv laboratory replaces its forbidden `setgroups` call only within that test environment. Product transport and resolver mounts are exercised; service authentication and privilege dropping are checked separately by unit tests. These tests did not initially install the service on the host.

## 0.1.1: vhost-net warning

The OpenConnect queue is set to ten packets, below its vhost-net activation threshold. A regression test checks this and preserves `--script-tun`. `make check` passed 39 tests and the Debian package was rebuilt. The ocserv laboratory was not rerun for this revision; high-load performance remains unmeasured.

## 0.1.2: instance isolation and desktop recovery

Chrome and the installed ChatGPT/Codex main process were observed in the VPN namespace using their usual profiles. Reopening from the desktop could reuse them after their windows closed. VS Code has a similar reuse mechanism, but was not running when the incident was diagnosed.

Recovery used the normal user systemd manager without editing personal profiles. The user confirmed Chrome and VS Code connectivity; the later ChatGPT/Codex recovery log and namespace inspection confirmed its normal-network launch. See the [incident record](incident-recovery.md).

The fix supplies private XDG directories after dropping privileges, dedicated Chrome/Chromium and VS Code user-data directories, namespace-wide process counting and a quit warning. There is still no direct fallback on disconnect.

Validation: 49 unit tests, Ruff, Debian package build and GTK/Xvfb checks for quit cancellation and disconnect-before-exit. Instance planning and personal-profile preservation are covered by unit tests. These are not full application coexistence tests.

## 0.1.3: About and user Chrome check

The About button displays the version loaded by the current GUI process. GTK/Xvfb opens it through the button, verifies its version and parent window, and closes it before continuing existing checks. All 49 unit tests and Ruff passed; the Debian package was rebuilt.

The user reported that the separate Chrome instance worked and noticed that its normal Google accounts were absent, consistent with a fresh VPN profile. Persistence is implemented through a stable directory, but a complete sign-in/relaunch persistence test was not recorded. Actual VS Code coexistence and Codex/ChatGPT isolation remain unvalidated.

## 0.1.4: English documentation and interface

Project-owned UI strings, CLI help, errors, recovery messages and documentation are in English. Command names, IPC fields, connection-profile schemas and application-data paths are unchanged. The repository includes an MIT license, current architecture and issue tracking. Validation: 49 unit tests passed, Ruff passed, and the GTK/Xvfb check passed with English labels and About version 0.1.4. Local Markdown file links resolve. The Debian package was rebuilt with architecture, issues and license included. The earlier network laboratories were not rerun for this text/documentation revision, and the new package was not installed on the host.

## Outstanding target validation

- Complete service install/upgrade/restart lifecycle and group membership on the supported distribution matrix.
- Password and real OTP/MFA forms across target Cisco configurations. One successful TLS/DTLS connection log does not certify all configurations.
- Actual VS Code coexistence, browser child processes, persistent sign-in, sleep/resume, network changes and prolonged load.
- Codex/ChatGPT data paths, singleton behavior and shared helper/backend services; no validated support claim.
- Notification icon behavior across desktop environments.
- Throughput, latency, memory and reconnection measurements on reference hardware.

This is an early implementation, not a certified product for every Debian/Ubuntu environment. Follow the [target-machine test procedure](v1-linux.md) and [known issues](issues.md).
