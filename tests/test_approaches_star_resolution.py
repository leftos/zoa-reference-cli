"""STAR resolution from CIFP for the approaches and apps commands."""

from __future__ import annotations

import pytest

from tests.conftest import make_cifp_line
from zoa_ref.approaches import ApproachAnalysis, find_connected_approaches
from zoa_ref.charts import ChartInfo
from zoa_ref.commands import do_approaches_lookup

AIRPORT = "ZZZ"


def _chart(name: str, code: str) -> ChartInfo:
    """Build a chart as the charts API would return it."""
    return ChartInfo(
        chart_name=name,
        chart_code=code,
        pdf_path="",
        faa_ident="",
        icao_ident="",
    )


def _iap_chart() -> ChartInfo:
    """Build the approach chart the connection lookup runs against."""
    return _chart("ILS RWY 17", "IAP")


@pytest.fixture
def cifp(tmp_path, monkeypatch):
    """Patch CIFP data and navaid lookups for the airport under test."""
    navaid_map: dict[str, list[str]] = {}

    def write(star_ids: list[str], fix_id: str = "WESLA") -> None:
        lines = [
            make_cifp_line(
                fac_id="KZZZ",
                fac_sub_code="E",
                procedure_type="2",
                procedure_id=star_id,
                fix_id=fix_id,
            )
            for star_id in star_ids
        ]
        path = tmp_path / "FAACIFP18"
        path.write_text("\n".join(lines) + "\n", encoding="latin-1")
        monkeypatch.setattr("zoa_ref.cifp.ensure_cifp_data", lambda: str(path))

    monkeypatch.setattr(
        "zoa_ref.navaids.get_all_navaid_identifiers",
        lambda name: navaid_map.get(name.upper(), []),
    )
    return write, navaid_map


def _patch_charts(monkeypatch, charts: list[ChartInfo]) -> None:
    """Serve the given chart list from the charts API."""
    monkeypatch.setattr(
        "zoa_ref.approaches.fetch_charts_from_api",
        lambda airport: charts,
    )


def test_exact_identifier(cifp, monkeypatch):
    write, _ = cifp
    write(["SCOLA1"])
    _patch_charts(monkeypatch, [_iap_chart()])

    star, connections = find_connected_approaches(AIRPORT, "SCOLA1")

    assert star is not None
    assert star.name == "SCOLA1"
    assert connections == []


def test_found_when_charts_use_another_code(cifp, monkeypatch):
    write, _ = cifp
    write(["SCOLA1"])
    _patch_charts(monkeypatch, [_chart("SCOLA ONE", "STR"), _iap_chart()])

    star, _connections = find_connected_approaches(AIRPORT, "SCOLA1")

    assert star is not None
    assert star.name == "SCOLA1"


def test_navaid_identifier_typed(cifp, monkeypatch):
    write, _ = cifp
    write(["CCR2"])
    _patch_charts(monkeypatch, [_iap_chart()])

    star, _connections = find_connected_approaches(AIRPORT, "CCR2")

    assert star is not None
    assert star.name == "CCR2"


def test_navaid_name_typed(cifp, monkeypatch):
    write, navaids = cifp
    write(["CCR2"])
    navaids["CONCORD"] = ["CCR"]
    _patch_charts(monkeypatch, [_iap_chart()])

    star, _connections = find_connected_approaches(AIRPORT, "CONCORD2")

    assert star is not None
    assert star.name == "CONCORD2"
    assert star.waypoints == ["WESLA"]


def test_stale_number_resolves_to_only_same_base(cifp, monkeypatch):
    write, _ = cifp
    write(["SCOLA1"])
    _patch_charts(monkeypatch, [_iap_chart()])

    star, _connections = find_connected_approaches(AIRPORT, "SCOLA2")

    assert star is not None
    assert star.name == "SCOLA1"


def test_stale_number_with_two_candidates_is_not_found(cifp, monkeypatch):
    write, _ = cifp
    write(["SCOLA1", "SCOLA3"])
    _patch_charts(monkeypatch, [_iap_chart()])

    star, connections = find_connected_approaches(AIRPORT, "SCOLA2")

    assert (star, connections) == (None, [])


def test_unknown_star_is_not_found(cifp, monkeypatch):
    write, _ = cifp
    write(["SCOLA1"])
    _patch_charts(monkeypatch, [_iap_chart()])

    star, connections = find_connected_approaches(AIRPORT, "NOPEE1")

    assert (star, connections) == (None, [])


def test_no_charts_is_not_found(cifp, monkeypatch):
    write, _ = cifp
    write(["SCOLA1"])
    _patch_charts(monkeypatch, [])

    star, connections = find_connected_approaches(AIRPORT, "SCOLA1")

    assert (star, connections) == (None, [])


def test_connection_found_through_shared_iaf(cifp, monkeypatch):
    write, _ = cifp
    write(["SCOLA1"], fix_id="ALPHA")
    _patch_charts(monkeypatch, [_iap_chart()])
    monkeypatch.setattr(
        "zoa_ref.approaches.analyze_approach",
        lambda airport, chart_name: ApproachAnalysis(
            name=chart_name,
            runway="17",
            iaf_waypoints=["ALPHA"],
            if_waypoints=[],
        ),
    )

    star, connections = find_connected_approaches(AIRPORT, "SCOLA1")

    assert star is not None
    assert len(connections) == 1
    assert connections[0].connecting_fix == "ALPHA"
    assert connections[0].fix_type == "IAF"


def test_not_found_lists_cifp_identifiers(cifp, monkeypatch, capsys):
    write, _ = cifp
    write(["SCOLA1", "SCOLA3"])
    _patch_charts(monkeypatch, [_iap_chart()])
    monkeypatch.setattr("zoa_ref.commands.record_airport", lambda airport: None)

    do_approaches_lookup(AIRPORT, "NOPEE1")

    output = capsys.readouterr().out
    assert "Could not find STAR 'NOPEE1'" in output
    assert "  - SCOLA1" in output
    assert "  - SCOLA3" in output
