"""Tests that only interactive startup patches asyncio for nested event loops."""

from __future__ import annotations

import subprocess
import sys

import pytest

from zoa_ref import interactive


def _run_python(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-W", "ignore", "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )


def test_importing_input_does_not_patch_asyncio() -> None:
    code = (
        "import asyncio, zoa_ref.input\n"
        "raise SystemExit(1 if hasattr(asyncio, '_nest_patched') else 0)\n"
    )
    result = _run_python(code)
    assert result.returncode == 0, result.stderr


def test_enable_nested_event_loops_allows_a_nested_run() -> None:
    code = (
        "import asyncio\n"
        "from zoa_ref.input import enable_nested_event_loops\n"
        "enable_nested_event_loops()\n"
        "async def outer():\n"
        "    asyncio.run(asyncio.sleep(0))\n"
        "asyncio.run(outer())\n"
    )
    result = _run_python(code)
    assert result.returncode == 0, result.stderr


def test_interactive_startup_enables_nested_loops_before_any_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Reached(Exception):
        pass

    def enable() -> None:
        raise Reached

    def no_browser(*args: object, **kwargs: object) -> None:
        pytest.fail("a browser started before nested loops were enabled")

    monkeypatch.setattr(interactive, "enable_nested_event_loops", enable)
    monkeypatch.setattr(interactive, "BrowserSession", no_browser)
    with pytest.raises(Reached):
        interactive._start_interactive(use_playwright=False)
