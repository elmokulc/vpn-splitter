# macOS identity and transparent-proxy laboratory

## Implemented boundary

This laboratory advances the macOS network adapter without claiming a working VPN. It contains a compiled `NETransparentProxyProvider`, a separate system-extension entry point, application signature inspection/revalidation, an audit-token identity adapter and a lifecycle gate. No command in the current laboratory installs or activates an extension, launches an application or changes host networking. The preview app does not embed the provider.

The provider's only network rules target **127.0.0.1:49600 and [::1]:49600, outbound TCP and UDP**. Addresses and ports are fixed in source; the configuration cannot expand that scope. The provider supplies no DNS settings or global routes and performs no relay. Traffic outside that scope would not be intercepted by this experiment.

Within that scope, the policy is:

| Flow identity | Laboratory result |
| --- | --- |
| Explicitly selected application, same user, valid saved signing requirement | Close both sides with access denied; no direct fallback |
| Explicit control application, same user, valid saved signing requirement | Return `false` to permit direct loopback access |
| Missing/malformed audit token, other user, invalid signature or mismatched identifier/requirement | Close both sides with access denied |
| Any other application or helper | Close both sides with access denied |
| Startup pending/failed, stopped provider or stale start completion | No direct authorization from the lifecycle gate |

The provider consumes `NEFlowMetaData.sourceAppAuditToken` from macOS. It extracts the effective UID through Darwin's audit API, resolves running code using `kSecGuestAttributeAudit` and checks `SecCodeCheckValidity` against the saved requirement. A claimed signing identifier alone never authorizes a direct flow. Unsigned/ad-hoc code is refused. The API's attribution to responsible apps and helpers must still be measured in a live signed extension; there is no inferred parent/helper trust.

These are source behavior and unit-test results. They do not establish blocking after extension termination, system disablement or a kernel failure. Apple documents that returning `false` from a transparent proxy permits a direct connection and that its DNS settings are ignored: [NETransparentProxyProvider](https://developer.apple.com/documentation/networkextension/netransparentproxyprovider).

## Build and inspect without a developer account

Full Xcode with XCTest is required. An App Store account is sufficient to obtain Xcode; it does not supply the signing/provisioning required for the system-extension deployment described below.

```sh
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
make macos-lab
swift run --package-path native/macos VPNSplitterMacLab --help
swift run --package-path native/macos VPNSplitterMacLab inspect /System/Applications/TextEdit.app
```

Generate an independent laboratory configuration using two signed `.app` bundles:

```sh
umask 077
swift run --package-path native/macos VPNSplitterMacLab configuration \
  /System/Applications/TextEdit.app /System/Applications/Calculator.app \
  > /tmp/vpn-splitter-laboratory.json
```

This example validates signatures and the configuration format. It does not cause TextEdit or Calculator to generate probe traffic. Future live tests need two separately signed fixture applications that originate their own TCP/UDP probes; launching a browser from another app does not prove which identity macOS attributes to the flow.

The format is separate from `profiles.json`: schema version 1, non-root `ownerUID`, `blockedApplication` and `directApplication`. Both selections use the same signature metadata fields as the preview. Duplicate signing identities, unknown fields, invalid requirements and oversized documents are refused. The provider expects the encoded JSON as `NETunnelProviderProtocol.providerConfiguration["laboratoryConfiguration"]` (`Data`) and rejects other configuration keys. It does not accept identity data in start options.

`VPNSplitterNetworkLab` is a raw executable for future system-extension packaging, not a manually runnable VPN. It refuses execution outside a `.systemextension` bundle. Renaming a directory does not grant entitlements or make the extension installable.

## Signed integration still required

The current source does **not** include a signed containing-app target, provisioning profiles, an activation controller or an installable system-extension package. A future integration must:

1. Establish owner-controlled app and extension identifiers, a developer team, valid signing identities and provisioning profiles with the Network Extension/system-extension capabilities. An ad-hoc signature or an App Store login does not provide them.
2. Package the executable as a system extension with `NetworkExtension.NEProviderClasses["com.apple.networkextension.app-proxy"]` set to `VPNSplitterNetworkExtension.LaboratoryProvider`, the appropriate Mach service declaration, and entitlements/profile for that team and distribution channel.
3. Embed it in a correctly signed containing app and implement activation through `OSSystemExtensionManager`, followed by a `NETransparentProxyManager` configuration. Keep the two-app loopback scope fixed and obtain macOS user approval through the normal system UI.
4. Run two signed probe fixtures against TCP and UDP echo listeners on both loopback addresses. Record the audit-token attribution and observed blocked/direct results. Include unknown helpers, invalid requirements, different users, startup errors and stop/restart races.
5. Record behavior when the provider crashes or is disabled. That result must precede any claim of persistent protection or any extension of the laboratory scope to ordinary network traffic.

Deployment rules and signing differ by distribution channel. See Apple's [Network Extension deployment table](https://developer.apple.com/documentation/technotes/tn3134-network-extension-provider-deployment), [Network Extension entitlement](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.networking.networkextension) and [Developer ID Network Extension signing guidance](https://developer.apple.com/forums/thread/737894).

The OpenConnect relay, private per-application DNS, production IPv6 policy, authenticated control IPC and protected launcher remain unimplemented. The preview's connection control therefore stays unavailable. The laboratory deliberately offers no proxy-variable, global-tunnel or PF-based substitute.
