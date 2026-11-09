"""Navaid name lookups, including a name typed without its spaces."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from zoa_ref.nasr import get_all_navaid_identifiers


def navaid(ident: str) -> SimpleNamespace:
    """Build a navaid carrying the identifier the lookup returns."""
    return SimpleNamespace(ident=ident)


@pytest.fixture(autouse=True)
def _navaid_indexes(monkeypatch):
    """Serve a fixed navaid index, so a test doesn't depend on the AIRAC cycle."""
    indexes = (
        {},
        {
            "BIG SUR": [navaid("BSR")],
            "POINT REYES": [navaid("PYE")],
            "CONCORD": [navaid("CCR"), navaid("CON")],
        },
    )
    monkeypatch.setattr("zoa_ref.nasr._build_navaid_indexes", lambda: indexes)


def test_exact_name():
    assert get_all_navaid_identifiers("concord") == ["CCR", "CON"]


def test_name_without_its_space():
    assert get_all_navaid_identifiers("BIGSUR") == ["BSR"]


def test_name_with_a_space_typed():
    assert get_all_navaid_identifiers("Point Reyes") == ["PYE"]


def test_unknown_name():
    assert get_all_navaid_identifiers("NOWHERE") == []
