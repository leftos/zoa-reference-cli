"""Shared pytest fixtures for zoa-reference-cli tests.

The CIFP tests use small inline ARINC 424 record strings rather than depending
on the real ~17 MB FAACIFP18 file or a downloaded AIRAC cycle. Each test
constructs the exact 132-column primary record it needs.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def make_cifp_line(
    *,
    section: str = "S",
    area: str = "USA",
    sec_code: str = "P",
    fac_id: str = "KSFO",
    fac_region: str = "K2",
    fac_sub_code: str = "F",
    procedure_id: str = "I28L  ",
    procedure_type: str = "B",
    transition_id: str = "     ",
    seq_no: str = "010",
    fix_id: str = "WESLA",
    fix_region: str = "K2",
    fix_sec_code: str = "E",
    fix_sub_code: str = "A",
    cont_rec_no: str = "0",
    desc_code: str = "E  F",
    turn_direction: str = " ",
    rnp: str = "   ",
    path_term: str = "TF",
    tdv: str = " ",
    rec_vhf: str = "    ",
    rec_vhf_region: str = "  ",
    arc_radius: str = "      ",
    theta: str = "    ",
    rho: str = "    ",
    course: str = "    ",
    dist_time: str = "    ",
    rec_vhf_sec_code: str = " ",
    rec_vhf_sub_code: str = " ",
    alt_desc: str = " ",
    atc: str = " ",
    alt_1: str = "     ",
    alt_2: str = "     ",
    trans_alt: str = "     ",
    speed_limit: str = "   ",
    vert_angle: str = "    ",
    center_fix: str = "     ",
    mult_code: str = " ",
    center_fix_region: str = "  ",
    center_fix_sec_code: str = " ",
    center_fix_sub_code: str = " ",
    gns_fms_id: str = " ",
    speed_desc: str = " ",
    rte_qual_1: str = " ",
    rte_qual_2: str = " ",
    record_number: str = "00001",
    cycle_data: str = "2501",
) -> str:
    """Construct a 132-column ARINC 424 procedure primary record.

    Column offsets match cifparse PrimaryIndices exactly. Defaults produce a
    benign TF leg with empty altitude/speed restrictions; tests override only
    the fields they care about.
    """
    line = [" "] * 132

    def put(start: int, end: int, value: str) -> None:
        width = end - start
        padded = (value + " " * width)[:width]
        line[start:end] = list(padded)

    put(0, 1, section)
    put(1, 4, area)
    put(4, 5, sec_code)
    # PAD 1 at col 5
    put(6, 10, fac_id)
    put(10, 12, fac_region)
    put(12, 13, fac_sub_code)
    put(13, 19, procedure_id)
    put(19, 20, procedure_type)
    put(20, 25, transition_id)
    # PAD 1 at col 25
    put(26, 29, seq_no)
    put(29, 34, fix_id)
    put(34, 36, fix_region)
    put(36, 37, fix_sec_code)
    put(37, 38, fix_sub_code)
    put(38, 39, cont_rec_no)
    put(39, 43, desc_code)
    put(43, 44, turn_direction)
    put(44, 47, rnp)
    put(47, 49, path_term)
    put(49, 50, tdv)
    put(50, 54, rec_vhf)
    put(54, 56, rec_vhf_region)
    put(56, 62, arc_radius)
    put(62, 66, theta)
    put(66, 70, rho)
    put(70, 74, course)
    put(74, 78, dist_time)
    put(78, 79, rec_vhf_sec_code)
    put(79, 80, rec_vhf_sub_code)
    # RESERVED 2 at cols 80-81
    put(82, 83, alt_desc)
    put(83, 84, atc)
    put(84, 89, alt_1)
    put(89, 94, alt_2)
    put(94, 99, trans_alt)
    put(99, 102, speed_limit)
    put(102, 106, vert_angle)
    put(106, 111, center_fix)
    put(111, 112, mult_code)
    put(112, 114, center_fix_region)
    put(114, 115, center_fix_sec_code)
    put(115, 116, center_fix_sub_code)
    put(116, 117, gns_fms_id)
    put(117, 118, speed_desc)
    put(118, 119, rte_qual_1)
    put(119, 120, rte_qual_2)
    # PAD 3 at cols 120-122
    put(123, 128, record_number)
    put(128, 132, cycle_data)

    return "".join(line)


@pytest.fixture
def synthetic_sid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    """Point the CIFP reader at a one-SID file, so a test doesn't depend on the AIRAC cycle.

    Returns:
        The airport and procedure name to pass to ``get_procedure_detail``.
    """
    legs = [
        make_cifp_line(
            fac_id="KZZZ",
            fac_sub_code="D",
            procedure_id="TESTY5",
            procedure_type="2",
            seq_no=seq_no,
            fix_id=fix_id,
        )
        for seq_no, fix_id in (("010", "ALPHA"), ("020", "BRAVO"))
    ]
    cifp_file = tmp_path / "FAACIFP18"
    cifp_file.write_text("\n".join(legs) + "\n", encoding="latin-1")
    monkeypatch.setattr("zoa_ref.cifp.ensure_cifp_data", lambda: cifp_file)
    monkeypatch.setattr("zoa_ref.navaids.get_all_navaid_identifiers", lambda name: [])
    return "ZZZ", "TESTY5"
