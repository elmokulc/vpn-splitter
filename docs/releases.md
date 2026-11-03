# Release builds

## Outputs and triggers

`.github/workflows/release.yml` builds and tests both platforms when a GitHub release is **published**, including a prerelease. Creating a tag alone, saving a draft or editing an existing release does not run this workflow. GitHub documents the [release event and published activity](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#release).

The tagged commit must contain the workflow. It checks out that exact event commit, validates versions, then builds in parallel:

- Ubuntu 24.04: `make deb`, including the complete Python suite and package inspection.
- macOS 15: `make macos-app`, including Swift tests, arm64 compilation and ad-hoc signature verification. `lipo` checks arm64; `ditto` archives the bundle with executable permissions and macOS metadata.

Once both builds succeed, the workflow assembles:

| File | Purpose |
| --- | --- |
| `vpn-splitter_VERSION_all.deb` | Linux Debian/Ubuntu package; dependencies are installed by apt |
| `vpn-splitter_VERSION_macos_arm64_preview.app.zip` | Apple Silicon configuration preview, containing `VPN Splitter Preview.app` |
| `SHA256SUMS` | SHA-256 checksums of both downloadable packages |

These files are available in the workflow's `release-assets` artifact for 14 days and attached to the published GitHub release. Release assets are independent of Actions artifact retention. Files are uploaded only after both platform jobs pass; individual build artifacts remain available if a later job fails. The publication step needs only the repository's built-in `GITHUB_TOKEN`, with `contents: write` limited to that job. Build jobs have read-only repository access and do not receive the publishing token.

The `.app` is a directory bundle, so it is distributed as a ZIP. Uploading a raw bundle through Actions would not preserve its executable permissions. GitHub describes [artifact permission limits](https://github.com/actions/upload-artifact#limitations). Extract the inner `.app.zip` to recover the bundle.

## Publishing a version

1. Update `src/vpn_splitter/__init__.py` and `pyproject.toml` to the same numeric `MAJOR.MINOR.PATCH` version. This value supplies both the Debian package version and the macOS bundle version.
2. Commit and push the sources and workflow. Run **Actions → Release packages → Run workflow** on that commit/branch to check both builds before publication. Manual runs produce the same downloadable artifacts/checksums but do not attach files to a release or create one.
3. Create and publish a GitHub release using a tag matching that version, with an optional `v` prefix, for example `v0.1.5`. Select the validated commit as the target. Mark preview releases as prereleases and state the macOS limitations in the release notes.
4. Wait for **Release packages** to finish. Verify that all three files appear under the release's **Assets** section. A published release initially exists without binary assets while builds run.

The workflow refuses mismatched runtime/project versions or a mismatched tag before building. Prerelease labels are set on the GitHub release; tags still use the numeric version, rather than suffixes such as `-beta.1`.

Rerun a failed release workflow after correcting transient failures. Publication uses [`gh release upload --clobber`](https://cli.github.com/manual/gh_release_upload), so rerunning replaces files with the same names on a mutable release. Immutable releases prevent asset changes; this workflow targets mutable releases. A source-code fix requires a new commit and version/tag rather than silently moving an existing release tag.

If creating releases from another workflow, GitHub normally suppresses additional workflow events caused by that workflow's built-in token. Use the manual build as part of that process or a suitably authorized user/app token; publishing through the GitHub UI or a user's GitHub CLI is supported. See [triggering workflows from workflows](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow#triggering-a-workflow-from-a-workflow).

## Verifying downloads

Download both packages and `SHA256SUMS` into the same directory. On Linux:

```sh
sha256sum --check SHA256SUMS
sudo apt install ./vpn-splitter_0.1.5_all.deb
```

On macOS, use `shasum -a 256 --check SHA256SUMS` and extract the `.app.zip`. To check just one downloaded package, keep only that package's line from the manifest when invoking the checksum tool.

Checksums detect incomplete or modified downloads relative to the manifest; they do not replace Developer ID signing/notarization or an independently trusted signature.

## Validation boundaries

The macOS artifact currently edits configuration only. It is ad-hoc signed, not Developer ID signed or notarized, and contains no Network Extension or OpenConnect worker. A successful CI build proves compilation, native unit checks, bundle assembly and the stated architecture/signature checks. It does not establish GUI behavior, gateway compatibility, application isolation, DNS guarantees or failure protection. See the [macOS guide](v1-macos.md).

The Linux workflow runs unprivileged unit and packaging checks; it does not install/start the privileged service, alter host networking or validate a real Cisco gateway. Kernel/ocserv/GUI integration checks remain separate, as documented in the [Linux guide](v1-linux.md).
