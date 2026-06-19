"""Chart-code normalization at the charts-API ingestion boundary.

The FAA renamed the Standard Terminal Arrival Route chart-listing code from
"STAR" to "STR". The CLI matches the internal value "STAR" everywhere, so the
incoming code is normalized once when the API payload is parsed.
"""

from __future__ import annotations

from zoa_ref.charts import ChartType, _charts_from_payload


def _payload(chart_code: str) -> dict:
    """Build a minimal charts-API payload with one chart of the given code."""
    return {
        "KSJC": [
            {
                "chart_name": "RAZRR FIVE",
                "chart_code": chart_code,
                "pdf_path": "https://example.test/razrr5.pdf",
                "faa_ident": "SJC",
                "icao_ident": "KSJC",
            }
        ]
    }


def test_str_normalized_to_star():
    """The new "STR" code is normalized to the internal "STAR"."""
    charts = _charts_from_payload(_payload("STR"))
    assert len(charts) == 1
    assert charts[0].chart_code == "STAR"
    assert charts[0].chart_type == ChartType.STAR


def test_legacy_star_passes_through():
    """A payload still using "STAR" is left unchanged (mixed-cycle safe)."""
    charts = _charts_from_payload(_payload("STAR"))
    assert charts[0].chart_code == "STAR"
    assert charts[0].chart_type == ChartType.STAR


def test_other_codes_pass_through():
    """Non-STAR codes are untouched by normalization."""
    expected = {
        "DP": ChartType.SID,
        "IAP": ChartType.IAP,
        "APD": ChartType.APD,
    }
    for code, chart_type in expected.items():
        charts = _charts_from_payload(_payload(code))
        assert charts[0].chart_code == code
        assert charts[0].chart_type == chart_type
