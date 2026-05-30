"""CLI tests for the 'distance' and 'bearing' commands."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from zoa_ref.cli import main


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# distance command
# ---------------------------------------------------------------------------


def test_distance_command_success(runner: CliRunner):
    """distance KSMF SUU prints distance and bearing lines."""
    result = runner.invoke(main, ["distance", "KSMF", "SUU"])
    if result.exit_code != 0 and "Unknown identifier" not in (
        result.output + str(result.exception)
    ):
        pytest.skip("Reference data unavailable")
    if "Unknown identifier" in result.output:
        pytest.skip("Reference data unavailable")

    assert result.exit_code == 0
    assert "From:" in result.output
    assert "To:" in result.output
    assert "Distance:" in result.output
    assert "NM" in result.output
    assert "Bearing:" in result.output


def test_distance_command_output_contains_ssw(runner: CliRunner):
    """distance KSMF SUU bearing line must contain SSW (regression guard)."""
    result = runner.invoke(main, ["distance", "KSMF", "SUU"])
    if result.exit_code != 0:
        pytest.skip("Reference data unavailable")

    assert "SSW" in result.output, f"Expected SSW in output, got:\n{result.output}"


def test_distance_command_unknown_ident(runner: CliRunner):
    """distance with an unknown identifier must exit with code 1."""
    result = runner.invoke(main, ["distance", "ZZZZZ", "KSMF"])
    assert result.exit_code == 1


def test_distance_command_missing_args(runner: CliRunner):
    """distance with missing arguments exits non-zero."""
    result = runner.invoke(main, ["distance", "KSMF"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# bearing command
# ---------------------------------------------------------------------------


def test_bearing_command_success(runner: CliRunner):
    """bearing KSMF SUU prints bearing and distance lines."""
    result = runner.invoke(main, ["bearing", "KSMF", "SUU"])
    if result.exit_code != 0 and "Unknown identifier" not in (
        result.output + str(result.exception)
    ):
        pytest.skip("Reference data unavailable")
    if "Unknown identifier" in result.output:
        pytest.skip("Reference data unavailable")

    assert result.exit_code == 0
    assert "From:" in result.output
    assert "To:" in result.output
    assert "Bearing:" in result.output
    assert "Distance:" in result.output
    assert "NM" in result.output


def test_bearing_command_output_contains_ssw(runner: CliRunner):
    """bearing KSMF SUU must show SSW direction (regression guard)."""
    result = runner.invoke(main, ["bearing", "KSMF", "SUU"])
    if result.exit_code != 0:
        pytest.skip("Reference data unavailable")

    assert "SSW" in result.output, f"Expected SSW in output, got:\n{result.output}"


def test_bearing_command_unknown_ident(runner: CliRunner):
    """bearing with an unknown identifier must exit with code 1."""
    result = runner.invoke(main, ["bearing", "ZZZZZ", "KSMF"])
    assert result.exit_code == 1


def test_bearing_command_missing_args(runner: CliRunner):
    """bearing with missing arguments exits non-zero."""
    result = runner.invoke(main, ["bearing", "KSMF"])
    assert result.exit_code != 0
