"""AIRAC cycle math tests."""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import patch

from zoa_ref.cache import get_current_airac_cycle


def test_epoch_is_cycle_2501():
    """The AIRAC epoch (2025-01-23) is exactly cycle 2501."""
    fixed = datetime(2025, 1, 23, 12, 0, 0, tzinfo=timezone.utc)
    with patch("zoa_ref.cache.datetime") as mock_dt:
        mock_dt.now.return_value = fixed
        cycle_id, start, end = get_current_airac_cycle()
    assert cycle_id == "2501"
    assert start == date(2025, 1, 23)


def test_cycle_uses_utc_not_local_time():
    """Near midnight UTC, the cycle must come from UTC, not the local timezone.

    Set a UTC datetime that is one day past a cycle boundary. If the parser
    accidentally used a local-time conversion (which datetime.now() with no tz
    would do), tests run east of UTC could land in the previous cycle.
    """
    # 2025-02-20 00:30 UTC = cycle 2502 (started 2025-02-20).
    fixed = datetime(2025, 2, 20, 0, 30, 0, tzinfo=timezone.utc)
    with patch("zoa_ref.cache.datetime") as mock_dt:
        mock_dt.now.return_value = fixed
        cycle_id, _, _ = get_current_airac_cycle()
    assert cycle_id == "2502"


def test_cycles_increment_28_days():
    """Cycle 2502 starts 28 days after cycle 2501."""
    fixed = datetime(2025, 2, 20, 12, 0, 0, tzinfo=timezone.utc)
    with patch("zoa_ref.cache.datetime") as mock_dt:
        mock_dt.now.return_value = fixed
        cycle_id, start, end = get_current_airac_cycle()
    assert cycle_id == "2502"
    assert start == date(2025, 2, 20)
    assert end == date(2025, 3, 19)
