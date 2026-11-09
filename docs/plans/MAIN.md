# Main Plan — zoa-reference-cli
<!-- plan-doc-hygiene: 2026-11-08 b5c3326 -->

Index of active and pending work. One checkbox per task; link to subplans for detail.
Fresh agents: start here, work top-down (current focus → next up → backlog).

## Current focus

- [ ] **NCT entry and exit route lookup (`zoa xfer`, `zoa flow`).** `branch: feat/nct-xfer` (#2). Design in [nct-route-lookup.md](./nct-route-lookup.md): a reviewed data file from the NCT SOP and NCT-ZOA LOA, a terse typed lookup for use on position, a persistent flow setting and a reciprocal checker for errata.

  The owner approved the design on 2026-11-08 and asked for all seven Steps, pausing for the data review. Step 1 (extractor), Step 2 (reviewed data, rulings in `docs/plans/nct-data-rulings.md` on the branch) and Step 3 (core and reciprocal checker, errata in `docs/nct-errata.md`; landed on feat/nct-xfer, ships with #2) are on `feat/nct-xfer`. Step 4 (`zoa xfer`) is next.

  When no row applies, `zoa xfer` answers "no specific instructions, hand off en route at any altitude": every table is an override, not exhaustive. Step 4 reads rows through `applicable_rows`, never a filtered list, since narrowing needs the whole file; `conflicts` and `find_reciprocals` take the whole file too, so the brief gives them the same shorthand.

  At the merge, the design's decisions move into a subsystem doc, `docs/nct-route-lookup.md`, and both plan files are archived. They stay in the plan until then, since the feature isn't on `main`. The owner confirms the merge.
  - [ ] **Catch a last unruled row below a border gap in the NCT extractor.** On `feat/nct-xfer`, `_body_bottom` in `tools/extract_nct_routes.py` ends a table where its left border stops, and the check beside it looks only for ruled rows below that point. A final row with no closing rule would vanish with exit 0. No table in SOP v1.13 or LOA CHG08 hits this; SOP p33, p96 and p105 end open-bottomed but don't stop short. Found by review of the extractor.
  - [ ] **Check two suspect data cells against the pages.** On `feat/nct-xfer`, `sop-p136-t0-r0` says "Runway 17" with empty `flows`, so it applies under RNON, and `sop-p136-t1-r0` and `r1` say "Rwy 35" and apply under RNOS; their p135 counterparts carry the flow.

    `sop-p57-t0-r1` has "SQL Departures Only" at 5,000 against `r0`'s same qualifier at 3,000, and looks like a merged cell over-filled. Corrections go through `tools/nct_corrections.json`. Do this before the merge, since a wrong row reaches a controller. Found by review of the checker.
  - [ ] **List "two receivers claimed" in the errata.** On `feat/nct-xfer`, under SFOW+OAKE, `sop-p111-t1-r1` (Grove to Richmond at 10,000) drops `sop-p82-t1-r7` and `r8` (Grove to Valley) while the exit rows `sop-p96-t0-r11` and `r12` still name Valley. `tools/check_nct_reciprocals.py` shows that as unrelated no-reciprocal lines instead of one conflict. Add a section for it; don't add a guard to `rows_for`, which would keep correct drops such as `sop-p22-t0-r8`. Found by review of the checker.
  - [ ] **polish: don't show a stale row beside its replacement when a complex and an airport name the same place.** On `feat/nct-xfer`, `sop-p91-t0-r1` stays under SFOW+SJCE beside `sop-p91-t0-r4`, because the row rule's match treats `San Jose CX` and `SJC` as different items. Only an extra row prints. It needs an owner ruling on whether complexes match their airports.

## Backlog

- [ ] **polish: resolve STARs typed by a chart name that isn't their identifier.** `resolve_star` in `src/zoa_ref/approaches.py` returns nothing for `BIGSUR3` and `POINTREYES3` (the navaid names have a space, so `get_all_navaid_identifiers` misses them; CIFP has `BSR3`, `PYE3`) or for `FERNANDO7` and `MOORPARK4` (no navaid has the name; CIFP has `FERN7`, `MOOR4`).

  The removed chart matcher failed on these too, and the not-found list shows the identifiers. A census typing all 81 STAR charts at 20 airports by name found only these.
- [ ] **Replace `nest_asyncio` before Python 3.16.** `enable_nested_event_loops` in `src/zoa_ref/input.py` is the only caller of `nest_asyncio.apply()`, which calls `asyncio.get_event_loop_policy` (`nest_asyncio.py:40`, `:71`), slated for removal in 3.16.

  Interactive mode needs it: with Playwright's sync API running, `session.prompt` fails with `asyncio.run() cannot be called from a running event loop` without the patch. One way out is running the prompt on its own thread. Found when moving the call out of module import.
- [ ] **Clear the `ruff check` findings.** `uvx ruff check src tests` reports 129 findings, 41 of them auto-fixable. Examples are the `try`/`except`/`pass` blocks in `src/zoa_ref/procedures.py` (`_extract_pdf_bookmarks`, `_search_pdf_text_for_heading`, `find_text_in_section`), which hide PDF failures as "not found". Fix the auto-fixable set in its own commit, then the rest by rule. It touches nearly every file, so it runs after the items above land.
