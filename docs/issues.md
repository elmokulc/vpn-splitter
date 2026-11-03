# Known issues and incident follow-up

Updated November 3, 2026. This file records observed problems, fixes and their remaining validation limits. “Fixed” refers to the stated defect, not universal application compatibility. See the [validation record](validation-linux.md) for evidence and the [architecture](../architecture.md) for boundaries.

## ISSUE-001 — Optional vhost-net permission warning

**Status:** addressed in 0.1.1; load/performance validation open.

**Observed:** after successful AnyConnect authentication and CSTP/DTLS establishment, OpenConnect printed `Failed to open /dev/vhost-net: Permission denied`.

**Cause:** OpenConnect attempted optional vhost-net acceleration with the original queue size. The application uses an unprivileged userspace `--script-tun` relay; granting access to vhost-net was not required for this design. The warning alone did not establish tunnel failure.

**Fix:** `--queue-len=10`, below the activation threshold. A regression test checks the queue and retains script-tun. See the [OpenConnect manual](https://www.infradead.org/openconnect/manual.html) and [upstream TUN implementation](https://gitlab.com/openconnect/openconnect/-/blob/master/tun.c).

**Remaining:** measure throughput under load and rerun the gateway matrix; do not interpret absence of this warning as proof of destination reachability.

## ISSUE-002 — Desktop launch reuses a VPN application process

**Status:** managed profile fix shipped in 0.1.2; Chrome user check passed; VS Code coexistence open.

**Observed:** opening Chrome from the desktop after launching it through VPN Splitter reused the VPN process. Chrome, the installed ChatGPT/Codex application and VS Code appeared to require VPN Splitter to regain connectivity after reopening. The reported restart was an application relaunch, not a computer reboot.

**Cause:** a network namespace does not change application singleton/profile identity. Early versions reused personal profiles; background main processes could survive closing all windows. A later desktop launch could join that process. Disconnecting then blocked its network by design. Diagnosis found no persistent global host route/DNS modification. Chrome and ChatGPT/Codex VPN processes were observed; VS Code was not running at diagnosis.

**Fix:** persistent VPN-only Chrome/Chromium and VS Code `--user-data-dir`, private XDG paths, refusal of conflicting explicit data directories, namespace-wide process counting, and a quit warning with cancellation as the default. Applications left in the VPN remain blocked; no silent direct fallback is introduced.

**Recovery:** gracefully stop only the affected application's VPN main process and relaunch through the normal user systemd manager. Chrome/VS Code recovery was confirmed by the user; the later ChatGPT/Codex recovery log and process inspection confirmed its normal-network launch. See the [recovery guide](incident-recovery.md).

**Validation:** unit checks cover arguments, stable paths, personal data preservation and orphan process reporting; GTK checks cover quit ordering. The user subsequently reported a working separate Chrome instance. Real VS Code coexistence and the complete child/helper process matrix remain to be tested.

## ISSUE-003 — Codex/ChatGPT desktop isolation is not validated

**Status:** open; do not launch the active support application through VPN Splitter.

The locally installed `/usr/lib/chatgpt/ChatGPT` executable can host Codex and its tools. The historical recovery target is named `chatgpt`; that does not mean the conversation can be continued in a web browser, or that all ChatGPT/Codex packages share its paths.

The current launcher supplies private XDG directories, but does not force or validate every data path, singleton lock, backend or shared helper. Static inspection of this installation is not a coexistence test. A new window is not sufficient evidence of an independent process/network.

**Required resolution:** document the installed application's data/service paths, prove separate normal and VPN main/child processes, test disconnect/relaunch with a recovery channel outside that application, and verify personal data is preserved. Do not stop the sole communication process to perform this test.

**Current workaround:** keep Codex outside the VPN. The targeted recovery script is available if an older launch is still bound to the VPN; recovery itself closes the application's active tools and requires an explicit restart decision.

## ISSUE-004 — VPN Chrome starts without normal Google accounts

**Status:** expected profile separation; sign-in persistence needs a full user test.

The user observed a fresh Chrome profile after the isolation fix. This is intentional: personal cookies, accounts, preferences and extensions are not copied. Configure/sign in to the VPN instance separately. Its stable data directory persists across launches; logging out or clearing it naturally removes saved sessions.

**Remaining:** verify account sign-in, full process exit and the next VPN launch on the target machine. Avoid promising permanent authentication: the application and account provider control session expiry.

## ISSUE-005 — Closing windows can leave protected processes blocked

**Status:** warning/process accounting addressed in 0.1.2; lifecycle testing continues.

Background descendants can outlive the initial launcher. The old GUI did not adequately explain that quitting the VPN leaves those processes isolated. Status now counts namespace processes, Quit warns and waits for disconnect, and reset refuses a namespace with live processes.

**Workaround:** fully close protected applications before quitting. Hiding the GUI with the window close button keeps the tunnel running. Use targeted recovery for an older personal-profile process. Never “clean up” by silently moving protected processes onto the direct network.

**Remaining:** test sleep/resume, network changes, service upgrades/crashes and application-specific background behavior across supported desktop environments. Generic automatic stop/restart of every protected application is not implemented.

## ISSUE-006 — Missing GUI version information

**Status:** fixed in 0.1.3.

An About button now displays the version loaded by the GUI using the package version constant. The Xvfb check opens it, compares the version and closes it. An already running GUI retains its old version until Quit and relaunch, even if a newer package is installed.

## Validation backlog and unsupported scope

- Actual Cisco OTP/MFA coverage is narrower than OpenConnect's advertised protocol support; ocserv tests are not Cisco certification.
- IPv6 inside the protected namespace is deliberately blocked, not tunneled.
- Browser SSO, client certificates, posture checks, Snap/Flatpak and unvalidated shared desktop services are outside V1.
- One VPN network per user; application data is per application, not per VPN connection profile.
- Windows/macOS backends are not implemented. See the [prospective study](research-and-design.md).
- Desktop tray behavior and prolonged-load measurements remain to be validated. Package Maintainer contact is a placeholder.
