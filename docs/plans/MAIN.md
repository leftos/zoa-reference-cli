# Main Plan — zoa-reference-cli

Index of active and pending work. One checkbox per task; link to subplans for detail.
Fresh agents: start here, work top-down (current focus → next up → backlog).

## Next up

- [ ] **Source STARs for `approaches`/`apps` from CIFP instead of the charts-API `chart_code`.**
  Repoint `find_star_chart` / `find_connected_approaches` (`src/zoa_ref/approaches.py`) to
  resolve STAR names from CIFP (`get_all_stars` / `get_star_data` in `src/zoa_ref/cifp.py`)
  rather than filtering the charts-API list by `chart_code == "STAR"`. `analyze_star`
  (`approaches.py:69`) already pulls waypoints from CIFP, so the chart-code dependency on the
  STAR side exists only for name resolution. Removing it makes `apps` independent of charts-API
  designation changes (e.g. the STAR→STR rename).
  - Caveat: the IAP side still needs the charts API (it enumerates `chart_code == "IAP"`), so
    the charts fetch does not go away entirely.
  - Caveat: CIFP-based name matching differs from the current chart-name fuzzy matcher
    (`ChartQuery.parse` → `find_chart_by_name`, e.g. `CCR2 → CONCORD TWO`). Needs its own tests
    so `apps`/`approaches` resolution behavior doesn't regress.
  - Origin: surfaced while fixing the STAR→STR rename (boundary-normalization fix shipped
    separately; this is the deferred architectural improvement the user asked to track).

## Backlog

- See [cifp-parser-drift-from-yaat.md](./cifp-parser-drift-from-yaat.md) — CIFP parser parity
  with YAAT (all actionable items resolved 2026-05-21; kept for reference).
