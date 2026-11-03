# Recovering desktop applications after the instance incident

## What happened

Early versions launched applications using their normal data profiles. Chrome and the installed ChatGPT/Codex executable reused a main process inside the VPN namespace when opened from the desktop. Closing their windows could leave that process running. Disconnecting the tunnel then blocked these applications, making them appear dependent on VPN Splitter.

The reported “restart” meant reopening applications, not rebooting the computer. Diagnosis did not find a persistent change to host routing or DNS. See [ISSUE-002](issues.md#issue-002--desktop-launch-reuses-a-vpn-application-process).

Chrome was stopped gracefully and Chrome/VS Code were launched through the normal user systemd manager; the user confirmed both worked. The ChatGPT/Codex executable was subsequently restarted using the delayed procedure below. Its recovery log recorded a normal-network launch and a later process inspection confirmed that the three applications were outside the VPN namespace. Their personal profile files were not edited or deleted.

The user later confirmed that Chrome's separate VPN instance worked. Codex/ChatGPT coexistence remains unvalidated; a successful recovery is not proof of VPN-instance support.

## Targeted recovery

Save work first. Keep the VPN connected if the affected application is your only communication channel. Run from the repository as your regular user, without sudo:

```sh
# Diagnostic only; does not close anything:
python3 tools/recover_desktop.py chrome
# Explicitly stop and relaunch only the selected application's VPN instance:
python3 tools/recover_desktop.py chrome --restart
```

Targets: `chrome`, `code`, `chatgpt`, at the native paths declared in the script. The historical `chatgpt` target also covers a Codex installation whose executable is `/usr/lib/chatgpt/ChatGPT`; it is not a generic detector for every Codex package.

If authorized to close that application and its active tools, a delayed restart is available:

```sh
python3 tools/recover_desktop.py chatgpt --restart --delay 30
```

This schedules a transient **user systemd service**, returns immediately and waits thirty seconds. The worker refuses to operate as root or from the VPN namespace. It identifies the selected application's main processes by UID, executable and network namespace, uses pidfds and rechecks identity before SIGTERM. Normal instances are left alone. It never sends SIGKILL or forces a restart after an unsuccessful shutdown, and it does not stop the VPN. Logs are written to `build/recovery-*.log`.

**Restarting the application hosting Codex closes this conversation's active tools.** Arrange a recovery path before scheduling it. The worker needs the user's systemd manager to be outside the VPN.

## Verify and upgrade

After recovery, check new network requests with the VPN disconnected and inspect process network namespaces if necessary. A new window is not sufficient evidence of a distinct network process.

Versions 0.1.2 and later supply dedicated Chrome/Chromium and VS Code data directories and warn about remaining VPN processes when quitting. Data starts empty and persists across VPN launches; personal accounts and extensions are not copied. Generic XDG separation does not validate arbitrary applications.

Only upgrade after communication applications are outside the VPN: package installation restarts the privileged service. See the [README](../README.md) for the current package and [known issues](issues.md) for unresolved cases.
