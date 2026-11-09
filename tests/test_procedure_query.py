"""Tests for ProcedureQuery parsing of SOP section and search terms."""

import pytest

from zoa_ref.procedures import ProcedureQuery


@pytest.mark.parametrize(
    ("parts", "section", "search"),
    [
        (("NCT", "licke sfoe", "exit"), "licke sfoe", "exit"),
        (("NCT", "licke", "sfoe", "exit"), "licke sfoe", "exit"),
        (("NCT", "licke sfoe exit"), "licke sfoe", "exit"),
        (("NCT", "Morgan Entry"), "Morgan", "Entry"),
    ],
)
def test_exit_and_entry_suffix_is_a_search_term_quoted_or_not(parts, section, search):
    parsed = ProcedureQuery.parse(parts)

    assert parsed.section_term == section
    assert parsed.search_term == search


@pytest.mark.parametrize(
    "section",
    ["2-2", "IFR Departures", "licke sfoe", "exit", "Exit Routes"],
)
def test_other_quoted_sections_stay_whole(section):
    parsed = ProcedureQuery.parse(("NCT", section))

    assert parsed.section_term == section
    assert parsed.search_term is None


def test_string_query_splits_like_a_tuple():
    parsed = ProcedureQuery.parse('NCT "licke sfoe exit"')

    assert parsed.procedure_term == "NCT"
    assert parsed.section_term == "licke sfoe"
    assert parsed.search_term == "exit"
