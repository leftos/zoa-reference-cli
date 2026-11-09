# Main Plan — zoa-reference-cli
<!-- plan-doc-hygiene: 2026-11-08 b5c3326 -->

Index of active and pending work. One checkbox per task; link to subplans for detail.
Fresh agents: start here, work top-down (current focus → next up → backlog).

## Current focus

- [ ] **NCT entry and exit route lookup (`zoa xfer`, `zoa flow`).** `branch: feat/nct-xfer` (#2). Design in [nct-route-lookup.md](./nct-route-lookup.md): a reviewed data file from the NCT SOP and NCT-ZOA LOA, a terse typed lookup for use on position, a persistent flow setting and a reciprocal checker for errata.

  The owner approved the design on 2026-11-08 and asked for all seven Steps, pausing for the data review. Step 1 (extractor) and Step 2 (reviewed data, rulings in `docs/plans/nct-data-rulings.md` on the branch) landed on `feat/nct-xfer`, draft PR #2.

  At the merge, the design's decisions move into a subsystem doc, `docs/nct-route-lookup.md`, and both plan files are archived. They stay in the plan until then, since the feature isn't on `main`. The owner confirms the merge.
  - [ ] **Catch a last unruled row below a border gap in the NCT extractor.** On `feat/nct-xfer`, `_body_bottom` in `tools/extract_nct_routes.py` ends a table where its left border stops, and the check beside it looks only for ruled rows below that point. A final row with no closing rule would vanish with exit 0. No table in SOP v1.13 or LOA CHG08 hits this; SOP p33, p96 and p105 end open-bottomed but don't stop short. Found by review of the extractor.

## Next up

- [ ] **Source STARs for `approaches`/`apps` from CIFP instead of the charts-API `chart_code`.** Repoint `find_star_chart` / `find_connected_approaches` (`src/zoa_ref/approaches.py`) to resolve STAR names from CIFP (`get_all_stars` / `get_star_data` in `src/zoa_ref/cifp.py`) rather than filtering the charts-API list by `chart_code == "STAR"`.

  `analyze_star` (`approaches.py:69`) already pulls waypoints from CIFP, so the chart-code dependency on the STAR side exists only for name resolution. Removing it makes `apps` independent of charts-API designation changes (e.g. the STAR→STR rename).
  - Caveat: the IAP side still needs the charts API (it enumerates `chart_code == "IAP"`), so the charts fetch does not go away entirely.
  - Caveat: CIFP-based name matching differs from the current chart-name fuzzy matcher (`ChartQuery.parse` → `find_chart_by_name`, e.g. `CCR2 → CONCORD TWO`). Needs its own tests so `apps`/`approaches` resolution behavior doesn't regress.
  - Origin: surfaced while fixing the STAR→STR rename (boundary-normalization fix shipped separately; this is the deferred architectural improvement the user asked to track).

## Backlog

- [ ] **Replace `nest_asyncio` before Python 3.16.** `enable_nested_event_loops` in `src/zoa_ref/input.py` is the only caller of `nest_asyncio.apply()`, which calls `asyncio.get_event_loop_policy` (`nest_asyncio.py:40`, `:71`), slated for removal in 3.16. Interactive mode needs it: with Playwright's sync API running, `session.prompt` fails with `asyncio.run() cannot be called from a running event loop` without the patch. One way out is running the prompt on its own thread. Found when moving the call out of module import.
- [ ] **Clear the `ruff check` findings.** `uvx ruff check src tests` reports 129 findings, 41 of them auto-fixable. Examples are the `try`/`except`/`pass` blocks in `src/zoa_ref/procedures.py` (`_extract_pdf_bookmarks`, `_search_pdf_text_for_heading`, `find_text_in_section`), which hide PDF failures as "not found". Fix the auto-fixable set in its own commit, then the rest by rule. It touches nearly every file, so it runs after the items above land.
