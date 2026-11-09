# Main Plan — zoa-reference-cli
<!-- plan-doc-hygiene: 2026-11-08 b5c3326 -->

Index of active and pending work. One checkbox per task; link to subplans for detail.
Fresh agents: start here, work top-down (current focus → next up → backlog).

## Current focus

- [ ] **NCT entry and exit route lookup (`zoa xfer`, `zoa flow`).** `branch: feat/nct-xfer` (#2). Design in [nct-route-lookup.md](./nct-route-lookup.md): a reviewed data file from the NCT SOP and NCT-ZOA LOA, a terse typed lookup for use on position, a persistent flow setting and a reciprocal checker for errata.

  The owner approved the design on 2026-11-08 and asked for all seven Steps, pausing for the data review. Step 1 (extractor), Step 2 (reviewed data, rulings in `docs/plans/nct-data-rulings.md` on the branch) Step 3 (core and reciprocal checker, errata in `docs/nct-errata.md`) and Step 4 (`zoa xfer`, c801630, both install routes proved) are on `feat/nct-xfer` and ship with #2. Step 5 (`zoa flow`) is next: `resolve_xfer_flows` in `src/zoa_ref/commands.py` is the one place that swaps the assumed default for the stored setting.

  The answer rules for `zoa xfer`, owner rulings included, are under "Decisions" in [nct-route-lookup.md](./nct-route-lookup.md).

  At the merge, the design's decisions move into a subsystem doc, `docs/nct-route-lookup.md`, and both plan files are archived. They stay in the plan until then, since the feature isn't on `main`. The owner confirms the merge.
  - [ ] **Check the flow, complex and sector tables for a lost last row too.** On `feat/nct-xfer`, `build_grid` in `tools/extract_nct_routes.py` is also called directly for those tables (`:1608`, `:1672`), outside the check in `_handoff_grid`. Clipping the left border of the `sop_p6` complex table in a simulation dropped `Travis` with no error, since `_check_complete` tests only for empty. No table in SOP v1.13 or LOA CHG08 is known to hit this. Found by review of the extractor.
  - [ ] **Warn when reciprocal rows spell the same item differently.** On `feat/nct-xfer`, `woodside SQL` prints no conflict though Woodside's `OSI Heading 110` differs from the entry table's `OSI RV 110°`, because the entry row says `SQL GPS`, which isn't the same item (`_is_candidate` in `src/zoa_ref/nct_routes.py`). The errata list both as no-reciprocal lines. Found by review of `zoa xfer`.
  - [ ] **polish: hint at quoting a multi-word target.** On `feat/nct-xfer`, `zoa xfer grove San Jose` errors with `Unknown aircraft class 'Jose'`, which doesn't say to quote `San Jose`. Found by review of `zoa xfer`.
  - [ ] **polish: limit `Monterey Runway 10` to MRY.** On `feat/nct-xfer`, any Monterey complex member finds that row, so `zoa xfer licke SNS --flow SFOE` prints it, labelled, though it isn't SNS traffic. Found by review of `zoa xfer`.
  - [ ] **polish: bare `xfer` in interactive mode runs a chart lookup.** On `feat/nct-xfer`, `INTERACTIVE_COMMANDS` holds the prefix `"xfer "` and the query is stripped first, so `xfer` alone falls through to a chart lookup instead of printing its help. `mea` has the same shape. Found by review of `zoa xfer`.

## Backlog

- [ ] **Write console-title and terminal-reset escapes only to a terminal.** `set_console_title` and `reset_terminal_state`, called from `main` in `src/zoa_ref/cli.py`, write `\x1b]0;ZOA Ref CLI\x07\x1b[?1004l` to stdout with no tty check, so the first line of any piped `zoa` command carries them. Found while testing `zoa xfer`, whose tests stub both.
- [ ] **Replace `nest_asyncio` before Python 3.16.** `enable_nested_event_loops` in `src/zoa_ref/input.py` is the only caller of `nest_asyncio.apply()`, which calls `asyncio.get_event_loop_policy` (`nest_asyncio.py:40`, `:71`), slated for removal in 3.16.

  Interactive mode needs it: with Playwright's sync API running, `session.prompt` fails with `asyncio.run() cannot be called from a running event loop` without the patch. One way out is running the prompt on its own thread. Found when moving the call out of module import.
- [ ] **Clear the `ruff check` findings.** `uvx ruff check src tests` reports 129 findings, 41 of them auto-fixable. Examples are the `try`/`except`/`pass` blocks in `src/zoa_ref/procedures.py` (`_extract_pdf_bookmarks`, `_search_pdf_text_for_heading`, `find_text_in_section`), which hide PDF failures as "not found". Fix the auto-fixable set in its own commit, then the rest by rule. It touches nearly every file, so it runs after the items above land.
