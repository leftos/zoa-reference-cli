# zoa-reference-cli — architecture

A Python CLI (`zoa`) for quick lookups against ZOA's Reference Tool (charts, routes, ATIS, ICAO codes, SOPs) plus FAA CIFP and NASR data (procedures, navaids, airways). One package, `src/zoa_ref/`, in four layers: entry points (`cli.py`, `interactive.py`), shared command implementations (`commands.py`, `display.py`), feature modules (charts, procedures, routes, approaches, and so on) and a data layer (`cifp.py`, `nasr.py`, `cache.py`, `config.py`). The rule that shapes it: command logic lives once in `commands.py`, and both the Click CLI and the interactive loop call it, so the two front ends stay at parity. `cache.py` and `config.py` sit at the bottom and are AIRAC-cycle aware (28-day cycles); the data modules download once per cycle and cache under `~/.zoa-ref/`.

## Task Index

| Task | Files, in order | Deep doc |
|---|---|---|
| Add or change a command | `src/zoa_ref/commands.py` (the `do_*` function) → `src/zoa_ref/cli.py` (Click command) → `src/zoa_ref/interactive.py` (`_handle_*_interactive` and the `INTERACTIVE_COMMANDS` registry) → `src/zoa_ref/cli_utils.py` (`COMMAND_HELP`, `INTERACTIVE_HELP_COMMANDS`) → `src/zoa_ref/autocomplete.py` (`INTERACTIVE_COMMANDS`) | `CLAUDE.md` (Key Patterns) |
| Change chart lookup or name matching | `src/zoa_ref/charts.py` (`ChartQuery.parse`) → `src/zoa_ref/fuzzy.py` → `src/zoa_ref/commands.py` (`do_chart_lookup`, `do_list_charts`) → `tests/test_charts_chart_code.py` | `CLAUDE.md` |
| Fix a CIFP (ARINC 424) parsing bug | `src/zoa_ref/cifp.py` → `tests/conftest.py` (`make_cifp_line`) → the matching `tests/test_cifp_*.py` | [`plans/cifp-parser-drift-from-yaat.md`](plans/cifp-parser-drift-from-yaat.md) |
| Change the `cifp` or `uses` output | `src/zoa_ref/commands.py` (`do_cifp_lookup`, `do_uses_lookup`) → `src/zoa_ref/display.py` → `src/zoa_ref/cifp.py` | none |
| Change navaid or airway data | `src/zoa_ref/nasr.py` → `src/zoa_ref/navaids.py` → `src/zoa_ref/airways.py` → `tests/test_nasr_awy.py` | none |
| Change fix coordinates, `distance` or `bearing` | `src/zoa_ref/waypoints.py` → `src/zoa_ref/distance.py` → `tests/test_bearing.py`, `tests/test_bearing_cli.py` | none |
| Change `approaches` / `apps` | `src/zoa_ref/approaches.py` → `src/zoa_ref/commands.py` (`do_approaches_lookup`) | [`plans/MAIN.md`](plans/MAIN.md) (STAR sourcing task) |
| Change SOP / procedure lookup | `src/zoa_ref/procedures.py` (`ProcedureQuery.parse`) → `src/zoa_ref/cache.py` (PDF and heading caches) → `src/zoa_ref/commands.py` | none |
| Change METAR, ATIS or ICAO lookups | `src/zoa_ref/metar.py`, `src/zoa_ref/atis.py`, `src/zoa_ref/icao.py` → `src/zoa_ref/display.py` → `tests/test_metar_display.py` | none |
| Change AIRAC-cycle caching | `src/zoa_ref/cache.py` → `src/zoa_ref/config.py` → `tests/test_airac.py` | none |
| Change browser handling or the hotkey | `src/zoa_ref/browser.py` → `src/zoa_ref/playwright_bootstrap.py` → `src/zoa_ref/hotkey.py` → `src/zoa_ref/cli_utils.py` (`open_in_browser`) | none |
| Change interactive tab completion | `src/zoa_ref/autocomplete.py` (`ZoaCompleter`) → `src/zoa_ref/completers.py` | none |
| Change constants, URLs or cache paths | `src/zoa_ref/config.py` | `CLAUDE.md` (Data Sources) |
| Change the standalone build or release | `build_exe.py` → `.github/workflows/release.yml` → `src/zoa_ref/playwright_bootstrap.py` | none |

## Layers

Modules are flat in `src/zoa_ref/`; the import graph below was read from the `from zoa_ref.X import` and `from .X import` statements.

- **Entry points** (`cli.py`, `interactive.py`): `cli.py` holds the Click group (`main`, with `ImplicitChartGroup` from `cli_utils.py` so `zoa OAK CNDEL5` becomes a chart lookup) and one command per feature. `interactive.py` holds the prompt loop, `_handle_*_interactive` handlers and the `INTERACTIVE_COMMANDS` prefix registry. Both delegate to `commands.py`. `interactive.py` imports `main` from `cli.py` inside each handler, and `cli.py` imports `interactive` at module level.
- **Shared commands and output** (`commands.py`, `display.py`): `commands.py` owns the `do_*` implementations for both front ends and imports nearly every feature module. `display.py` formats every result type and imports the feature modules for their types only.
- **CLI support** (`cli_utils.py`, `input.py`, `autocomplete.py`, `completers.py`): help text (`COMMAND_HELP`), `InteractiveContext`, browser preference, prompt session and history, tab completion. `autocomplete.py` and `completers.py` reach into `commands.py`, `charts.py`, `procedures.py`, `navaids.py`, `atis.py` and `cache.py`.
- **Feature modules** (`charts.py`, `procedures.py`, `routes.py`, `atis.py`, `metar.py`, `icao.py`, `positions.py`, `scratchpads.py`, `frequency.py`, `descent.py`, `distance.py`, `mea.py`, `approaches.py`, `airways.py`, `fuzzy.py`): one lookup each. `charts.py` uses the charts API and `pypdf`; `procedures.py` extracts SOP PDF text. `approaches.py` reads both `charts.py` and `cifp.py`; `charts.py` in turn imports `approaches.py`, `cifp.py`, `fuzzy.py` and `navaids.py`.
- **Browser** (`browser.py`, `playwright_bootstrap.py`, `hotkey.py`): `BrowserSession` wraps Playwright's sync API; `playwright_bootstrap.py` installs Chromium on first run of a frozen build into `~/.zoa-ref/browsers`; `hotkey.py` is Windows-only (ctypes) global-hotkey focus management.
- **Data** (`cifp.py`, `nasr.py`, `navaids.py`, `waypoints.py`): `cifp.py` downloads and parses FAA CIFP; `nasr.py` downloads and parses NASR (navaids, airways); `navaids.py` re-exports navaid functions from `nasr.py` and adds aliasing; `waypoints.py` builds coordinate lookups from CIFP and navaids. `cifp.py` imports `cache.py` and `navaids.py`; `nasr.py` imports `cache.py`.
- **Foundation** (`cache.py`, `config.py`): `config.py` holds constants (cache dir, TTL, base URLs) and imports nothing from the package. `cache.py` imports only `config.py` and owns AIRAC math (`AIRAC_EPOCH`, `get_current_airac_cycle`) and the per-cycle caches.

Stated rule (`CLAUDE.md`): both the CLI and interactive mode use the shared `do_*` functions in `commands.py`, so new command logic goes there and not in a CLI or interactive handler.

## Integration Footguns

- **A command lives in five registries.** Adding a command means a `@main.command` in `cli.py`, an entry in `INTERACTIVE_COMMANDS` in `interactive.py`, `COMMAND_HELP` and `INTERACTIVE_HELP_COMMANDS` in `cli_utils.py`, and `INTERACTIVE_COMMANDS` (a plain list) in `autocomplete.py`. No test enforces that they agree, so a missed one shows up as a command missing in interactive mode, help or tab completion.
- **Unknown first argument means a chart query.** `ImplicitChartGroup.parse_args` in `cli_utils.py` rewrites any first argument that is not a registered command into `chart <args>` (and `OAK sop` into `sop OAK`), so a mistyped command runs a chart lookup instead of erroring.
- **Charts-API code renames.** The FAA renamed the arrival chart code `STAR` to `STR`; `charts.py` maps it back at the API boundary (`tests/test_charts_chart_code.py` covers it). `approaches.py` still filters on `chart_code == "STAR"`, which `docs/plans/MAIN.md` tracks for removal.
- **CIFP fixed-column offsets.** `cifp.py` decodes 132-column ARINC 424 records by position; `tests/conftest.py` `make_cifp_line` builds test records column by column, and `tests/test_conftest_fixture.py` checks that fields land in the expected columns. A column change in the parser needs the fixture to agree.
- **AIRAC cycle drives every download cache.** `nasr.py` and `cifp.py` key their downloads on `get_current_airac_cycle()` from `cache.py`; `tests/test_airac.py` pins the cycle computation (UTC date).
- **Import cycle between `cli.py` and `interactive.py`.** Handlers in `interactive.py` import `main` from `cli.py` lazily inside each function, because `cli.py` imports `interactive_mode` at module level; a module-level import back would be circular.
- **Cross-repo parity.** The CIFP parser was aligned to YAAT's parser (`docs/plans/cifp-parser-drift-from-yaat.md`); a decoder fix in one repo may need the same in the other.

## Test locations

`pytest` with `testpaths = ["tests"]` and `test_*.py` files (`pyproject.toml`). New tests go in `tests/` as `test_<area>.py`.

- `tests/test_cifp_*.py`: the CIFP parser in `src/zoa_ref/cifp.py` (altitude, continuation records, fix role, fly-over, geometry, missed approach, navaids, RF arcs, route type, terminators, waypoints), built from `make_cifp_line` in `tests/conftest.py`.
- `tests/test_conftest_fixture.py`: the `make_cifp_line` fixture itself.
- `tests/test_nasr_awy.py`: NASR AWY parsing in `nasr.py`.
- `tests/test_airac.py`: AIRAC cycle math in `cache.py`.
- `tests/test_bearing.py`, `tests/test_bearing_cli.py`: bearing and distance calculation and the `bearing` / `distance` commands through `CliRunner` on `zoa_ref.cli.main`.
- `tests/test_charts_chart_code.py`: chart-code normalisation in `charts.py`.
- `tests/test_metar_display.py`: METAR output formatting.
- Untested: the browser, interactive loop, hotkey, routes, procedures and ICAO modules have no tests.

## Deep docs

- [`plans/MAIN.md`](plans/MAIN.md): the plan index (the open task is sourcing STARs from CIFP for `approaches`).
- [`plans/cifp-parser-drift-from-yaat.md`](plans/cifp-parser-drift-from-yaat.md): CIFP parser parity review against YAAT, with the resolution log.
- [`../CLAUDE.md`](../CLAUDE.md): command reference, module list, key patterns and data sources.
- [`../README.md`](../README.md): install and usage.
