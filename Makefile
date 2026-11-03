.PHONY: test check lint run deb macos-test macos-app clean

RUFF ?= ruff

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v

check: test
	python3 -m compileall -q src

lint:
	$(RUFF) check src tests tools packaging/build_deb.py packaging/build_macos.py bin/vpn-splitter
	$(RUFF) format --check src tests tools packaging/build_deb.py packaging/build_macos.py bin/vpn-splitter

run:
	python3 bin/vpn-splitter gui

deb: check
	python3 packaging/build_deb.py

macos-test:
	swift test --package-path native/macos

macos-app: macos-test
	python3 packaging/build_macos.py

clean:
	rm -rf build dist
	find src tests -type d -name __pycache__ -prune -exec rm -rf {} +
