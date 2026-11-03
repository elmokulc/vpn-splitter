"""Entry point for privileged subprocesses, invoked with Python isolated mode."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vpn_splitter.cli import main

raise SystemExit(main())
