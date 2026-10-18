# Main Plan — zoa-reference-cli

Index of active and pending work. One checkbox per task; link to subplans for detail.
Fresh agents: start here, work top-down (current focus → next up → backlog).

## Current focus

- [x] **Install outside the repo and add `run.py`.** `install.py` installs a snapshot with `uv tool install` into a PATH bin dir (alias offered when none fits); `run.py` reinstalls when `src/` changes, then runs `zoa`. Drops the repo-root `zoa` / `zoa.cmd` launchers, which the daily `.venv` cleanup broke.

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

- [ ] **chore: split markdown lines of 500+ characters** (Grep shows them only as `[Omitted long matching line]`). Dry run `uv run --project ~/.claude/tools/md-line-split python -m md_line_split .` finds 4 lines in 2 files, none needing review: `docs/ARCHITECTURE.md:3`, `docs/plans/cifp-parser-drift-from-yaat.md:28`, `:40`, `:114`. Run with `--apply`, rerun until it prints `would split 0 lines`, commit as `docs:`. Requested by claude-config (inbox 20261006-040152).
- [ ] **Clear the two `nest_asyncio` DeprecationWarnings in the test run.** `src/zoa_ref/input.py:18` calls `nest_asyncio.apply()` at import time; `nest_asyncio.py:40` and `:71` call `asyncio.get_event_loop_policy`, deprecated and slated for removal in Python 3.16. Either drop `nest_asyncio` (check why prompt_toolkit needs a nested loop) or move `apply()` out of module import so tests don't trigger it.
- See [cifp-parser-drift-from-yaat.md](./cifp-parser-drift-from-yaat.md) — CIFP parser parity
  with YAAT (all actionable items resolved 2026-05-21; kept for reference).
