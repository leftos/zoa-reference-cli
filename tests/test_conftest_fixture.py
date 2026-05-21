"""Sanity tests for the make_cifp_line fixture."""

from __future__ import annotations

from tests.conftest import make_cifp_line


def test_default_line_is_132_chars():
    line = make_cifp_line()
    assert len(line) == 132


def test_record_starts_with_susap():
    line = make_cifp_line()
    assert line.startswith("SUSAP")


def test_fields_land_in_expected_columns():
    line = make_cifp_line(
        procedure_id="SCOLA1",
        fix_id="SCOLA",
        seq_no="100",
        alt_1="17000",
        alt_desc="@",
    )
    assert line[12] == "F"
    assert line[13:19] == "SCOLA1"
    assert line[29:34] == "SCOLA"
    assert line[26:29] == "100"
    assert line[82] == "@"
    assert line[84:89] == "17000"
