# Repository Guidelines

## Project Structure & Module Organization

The Linux V1 uses Python 3.11+, GTK 3/VTE, OpenConnect, and a privileged namespace service. Read `README.md` and `docs/v1-linux.md` for current behavior. `docs/research-and-design.md` contains the original, prospective Tauri/Rust design. `architecture.md` describes the implemented Linux design; `docs/issues.md` records incidents and open limitations.

The current layout is:

- `src/vpn_splitter/`: GTK interface, CLI, validated profiles, IPC, service, Linux backend, and packet bridge.
- `bin/vpn-splitter`: source-tree and installed launcher.
- `tests/`: standard-library unit tests; `tests/integration/` contains kernel, GTK, and ocserv laboratory checks.
- `packaging/`: Debian builder, systemd unit, desktop entry, and SVG icon.

`build/` and `dist/` are generated and ignored. Rust workspaces and other OS adapters have not been introduced.

## Build, Test, and Development Commands

Use the system Python; GTK bindings come from distribution packages.

- `make check`: run unit tests and compile Python modules.
- `make run`: open the GTK interface from source.
- `make deb`: check sources and build the Debian package in `dist/`.
- `python3 bin/vpn-splitter doctor`: report local prerequisites and service access.

The privileged service requires a root-owned installed package; never run it from a user-writable checkout. Integration commands and their isolation requirements are documented in `docs/v1-linux.md`.

## Coding Style & Naming Conventions

Use four-space Python indentation, `snake_case` for functions/modules, and `PascalCase` for types. Ruff settings are in `pyproject.toml`; keep imports and validation explicit. Keep operating-system operations in `linux.py` and protocol handling in `ipc.py`.

Keep platform-specific operations in their adapters. Write project documentation, UI strings and diagnostics in English. Cite sources and distinguish proposals from verified behavior.

## Testing Guidelines

Use `unittest`, files named `test_*.py`, and descriptive names such as `test_selected_app_blocks_when_tunnel_drops`. No numeric coverage threshold is configured. Test changes to state transitions, credential checks, descriptor passing, validation, and privileged execution order.

Verify kernel behavior in disposable namespaces and GUI behavior on a virtual display. Validate actual Cisco/OTP compatibility separately from ocserv laboratory results.

## Commit & Pull Request Guidelines

Use concise, scoped commit messages such as `docs: clarify DNS guarantees` or `feat(linux): add namespace launcher`.

PRs should explain behavior, affected platforms, validation, and limitations; link relevant issues and include screenshots for UI changes.

## Security & Configuration

Keep secrets out of configuration exports, logs, and process arguments. Preserve the core contract: selected applications use the VPN or remain blocked; other applications stay direct. Run launched applications as the user, and authenticate privileged IPC requests.
