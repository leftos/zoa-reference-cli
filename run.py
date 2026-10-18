#!/usr/bin/env python3
"""Run the ZOA Reference CLI, reinstalling only when the source has changed.

Usage:
    python run.py [zoa args...]
"""

import subprocess
import sys
from pathlib import Path

import install


def main() -> int:
    """Ensure the installed tool is current and run it with this script's args."""
    try:
        exe = install.ensure_installed(Path(__file__).resolve().parent, force=False)
    except install.InstallError as exc:
        print(exc, file=sys.stderr)
        return 1

    try:
        return subprocess.run([str(exe), *sys.argv[1:]]).returncode
    except KeyboardInterrupt:
        # The child shares this console and handles Ctrl+C itself.
        return 130


if __name__ == "__main__":
    sys.exit(main())
