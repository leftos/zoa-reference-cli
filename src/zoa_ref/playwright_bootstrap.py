"""First-run Chromium installation for frozen/standalone builds.

The GitHub Actions release build does not bundle Chromium — it would bloat
each archive by ~300-500 MB per platform. Instead, we download it on first
use into ``~/.zoa-ref/browsers`` via Playwright's own install driver.

This module must be imported and :func:`ensure_chromium_installed` called
before any :class:`BrowserSession` is constructed.
"""

import os
import subprocess
import sys

import click

from .config import PLAYWRIGHT_BROWSERS_DIR

_ENV_VAR = "PLAYWRIGHT_BROWSERS_PATH"


def _chromium_already_installed() -> bool:
    """Return True if a Chromium install is present in PLAYWRIGHT_BROWSERS_DIR."""
    if not PLAYWRIGHT_BROWSERS_DIR.exists():
        return False
    # Playwright lays out browsers as ``chromium-<build>/chrome-<platform>/...``.
    # Any ``chromium-*`` subdirectory with content counts as installed.
    for entry in PLAYWRIGHT_BROWSERS_DIR.iterdir():
        if entry.is_dir() and entry.name.startswith("chromium-"):
            return True
    return False


def _run_playwright_install() -> None:
    """Invoke the Playwright install driver to download Chromium.

    Uses the node driver bundled with the playwright package, which works
    both in a normal venv and inside a PyInstaller-frozen binary (where
    ``python -m playwright`` is unavailable because there is no Python
    interpreter accessible via ``sys.executable``).
    """
    from playwright._impl._driver import (  # type: ignore[import-not-found]
        compute_driver_executable,
        get_driver_env,
    )

    driver = compute_driver_executable()
    # compute_driver_executable() returns a tuple (node_exe, cli_js) on
    # modern Playwright versions; older versions returned a single string.
    if isinstance(driver, (list, tuple)):
        cmd = [*driver, "install", "chromium"]
    else:
        cmd = [driver, "install", "chromium"]

    env = get_driver_env()
    env[_ENV_VAR] = str(PLAYWRIGHT_BROWSERS_DIR)

    subprocess.run(cmd, env=env, check=True)


def ensure_chromium_installed() -> None:
    """Ensure Playwright's Chromium is installed, downloading on first run.

    - Sets ``PLAYWRIGHT_BROWSERS_PATH`` to ``~/.zoa-ref/browsers`` so every
      subsequent Playwright call uses that location.
    - If Chromium is not yet present, runs the Playwright install driver
      and prints a clear progress message.
    - Idempotent: safe to call on every launch.
    - Respects a user-provided ``PLAYWRIGHT_BROWSERS_PATH`` override — if
      the env var is already set, assume the user knows what they're doing
      and skip our custom location entirely.
    """
    user_override = os.environ.get(_ENV_VAR)
    if user_override:
        # User chose their own browser location; don't touch it.
        return

    os.environ[_ENV_VAR] = str(PLAYWRIGHT_BROWSERS_DIR)

    if _chromium_already_installed():
        return

    PLAYWRIGHT_BROWSERS_DIR.mkdir(parents=True, exist_ok=True)
    click.echo(
        "First run: downloading Chromium browser (~150 MB, one-time)...",
        err=True,
    )
    try:
        _run_playwright_install()
    except subprocess.CalledProcessError as exc:
        click.echo(
            f"Error: Chromium download failed (exit code {exc.returncode}).\n"
            "Check your internet connection and run `zoa` again.",
            err=True,
        )
        sys.exit(1)
    except FileNotFoundError as exc:
        click.echo(
            f"Error: Playwright install driver not found: {exc}.\n"
            "This is a bug in the packaged build.",
            err=True,
        )
        sys.exit(1)
