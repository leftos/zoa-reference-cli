"""First-run Chromium installation for frozen/standalone builds.

The GitHub Actions release build does not bundle Chromium — it would bloat
each archive by ~300-500 MB per platform. Instead, we download it on first
use into ``~/.zoa-ref/browsers`` via Playwright's own install driver.

This module must be imported and :func:`ensure_chromium_installed` called
before any :class:`BrowserSession` is constructed.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import click

from .config import PLAYWRIGHT_BROWSERS_DIR

_ENV_VAR = "PLAYWRIGHT_BROWSERS_PATH"


# Playwright's on-disk directory layout uses ``<name-with-underscores>-<rev>``
# (e.g. the ``chromium-headless-shell`` browser lands in
# ``chromium_headless_shell-1208/``). Only these two entries matter for this
# app — tip-of-tree variants are unused.
_REQUIRED_BROWSER_NAMES = {
    "chromium": "chromium",
    "chromium-headless-shell": "chromium_headless_shell",
}


def _required_chromium_dirs() -> list[str] | None:
    """Return the directory names the current Playwright expects, or None.

    Reads ``browsers.json`` from the Playwright package bundled with the
    running app — important when the frozen binary embeds a newer Playwright
    than any system cache, so we can't assume a cached ``chromium-*`` dir is
    compatible. Returns ``None`` if we can't locate or parse the manifest.
    """
    try:
        import playwright  # type: ignore[import-not-found]
    except ImportError:
        return None

    manifest_path = (
        Path(playwright.__file__).parent / "driver" / "package" / "browsers.json"
    )
    if not manifest_path.exists():
        return None

    try:
        with manifest_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None

    required: list[str] = []
    for browser in data.get("browsers", []):
        name = browser.get("name")
        revision = browser.get("revision")
        dir_prefix = _REQUIRED_BROWSER_NAMES.get(name)
        if dir_prefix and revision is not None:
            required.append(f"{dir_prefix}-{revision}")
    return required or None


def _chromium_already_installed() -> bool:
    """Return True if the expected Chromium revisions are present.

    If we can't determine the expected revisions (e.g. ``browsers.json`` is
    missing), fall back to a loose "any ``chromium-*`` dir exists" check so
    we don't spam a reinstall every launch.
    """
    if not PLAYWRIGHT_BROWSERS_DIR.exists():
        return False

    required = _required_chromium_dirs()
    if required is None:
        return any(
            entry.is_dir() and entry.name.startswith("chromium-")
            for entry in PLAYWRIGHT_BROWSERS_DIR.iterdir()
        )

    return all((PLAYWRIGHT_BROWSERS_DIR / d).is_dir() for d in required)


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
