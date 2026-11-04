.PHONY: test check lint run deb macos-test macos-app macos-lab clean

RUFF ?= ruff

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v

check: test
	python3 -m compileall -q src

lint:
	$(RUFF) check src tests tools packaging/*.py bin/vpn-splitter
	$(RUFF) format --check src tests tools packaging/*.py bin/vpn-splitter

run:
	python3 bin/vpn-splitter gui

deb: check
	python3 packaging/build_deb.py

macos-test:
	@xcrun --find xctest >/dev/null 2>&1 || { \
		echo "macOS tests require full Xcode with XCTest; standalone Command Line Tools are insufficient." >&2; \
		echo "Select Xcode in Settings > Locations > Command Line Tools, or run:" >&2; \
		echo "  DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer make $@" >&2; \
		exit 1; \
	}
	xcrun swift test --package-path native/macos

macos-app: macos-test
	python3 packaging/build_macos.py

macos-lab: macos-test
	xcrun swift build --package-path native/macos --product VPNSplitterNetworkLab
	xcrun swift build --package-path native/macos --product VPNSplitterMacLab

clean:
	rm -rf build dist
	find src tests -type d -name __pycache__ -prune -exec rm -rf {} +
