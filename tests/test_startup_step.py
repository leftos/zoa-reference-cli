"""Tests for the interactive-mode startup progress line."""

from __future__ import annotations

import re

import pytest

from zoa_ref.interactive import StartupStep


def test_step_prints_label_then_done_with_time(capsys: pytest.CaptureFixture[str]):
    with StartupStep("Launching browser"):
        pass

    assert re.fullmatch(
        r"  Launching browser\.\.\. done \(\d+\.\ds\)\n", capsys.readouterr().out
    )


def test_label_prints_before_the_body_runs(capsys: pytest.CaptureFixture[str]):
    with StartupStep("Loading page"):
        assert capsys.readouterr().out == "  Loading page... "


def test_body_can_replace_the_outcome(capsys: pytest.CaptureFixture[str]):
    with StartupStep("Loading page") as step:
        step.outcome = "unavailable"

    assert "Loading page... unavailable (" in capsys.readouterr().out


def test_exception_prints_failed_and_propagates(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(RuntimeError, match="boom"), StartupStep("Launching browser"):
        raise RuntimeError("boom")

    assert "Launching browser... failed (" in capsys.readouterr().out
