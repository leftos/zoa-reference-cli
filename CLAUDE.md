# CLAUDE.md

## Project Overview

The architecture entry point is [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): Task Index, layers, integration footguns, test locations and the deep docs.

ZOA Reference CLI - command-line lookups for ZOA's (Oakland ARTCC) Reference Tool. Provides charts, routes, ATIS, ICAO codes, and SOPs. Uses Playwright for browser automation and REST API for chart data.

## Commands

```bash
# Setup
python install.py                       # Install `zoa` outside the repo (uv tool), on PATH
python run.py <zoa args>                # Reinstall if src/ changed, then run zoa
uv run pytest                           # Tests (uses the repo .venv)

# Charts (implicit or explicit)
zoa OAK CNDEL5                          # Implicit chart lookup (opens PDF)
zoa chart OAK ILS 28R                   # Explicit chart lookup
zoa chart OAK ILS 28R -r                # Rotate 90°
zoa charts OAK CNDEL5                   # Browse on Reference Tool
zoa list OAK                            # List airport charts
zoa list OAK DP                         # List departure procedures (aliases: SID)
zoa list OAK STAR                       # List arrivals (also: IAP/APP, APD/TAXI)

# Routes, ATIS, ICAO, Navaids, Positions
zoa route SFO LAX                       # Route lookup
zoa atis SFO                            # Single airport ATIS
zoa atis --all                          # All airports ATIS
zoa airline UAL                         # Airline code lookup
zoa airport KSFO                        # Airport code lookup
zoa aircraft B738                       # Aircraft type lookup
zoa navaid FMG                          # Navaid lookup by identifier
zoa navaid MUSTANG                      # Navaid lookup by name
zoa position NCT                        # ATC position lookup
zoa scratchpad OAK                      # Scratchpad codes lookup

# Approaches and Tools
zoa approaches RNO SCOLA1               # Find approaches for STAR
zoa apps RNO KLOCK                      # Find approaches via fix
zoa descent 100 020                     # Descent calc: 10,000 to 2,000
zoa des 100 12.5                        # Altitude at 12.5nm from FL100

# External Tools
zoa vis                                 # Open airspace visualizer
zoa tdls RNO                            # Open TDLS for facility
zoa strips NCT                          # Open flight strips

# SOPs/Procedures
zoa sop OAK                             # Open OAK SOP
zoa sop OAK 2-2                         # Jump to section 2-2
zoa sop --list                          # List all procedures

# Interactive mode
zoa                                     # Default: system browser
zoa --playwright                        # Managed browser with tab reuse
```

## Architecture

Modules in `src/zoa_ref/`:

- **cli.py**: Click CLI with `ImplicitChartGroup` for `zoa <airport> <chart>` syntax. Entry point: `main()`
- **interactive.py**: Interactive mode loop and command handlers. Handlers parse args and delegate to `commands.py`
- **commands.py**: Shared command implementations (e.g., `do_list_charts`, `do_chart_lookup`). **Both CLI and interactive mode must use these shared functions to ensure feature parity.**
- **browser.py**: `BrowserSession` wrapping Playwright sync API. Supports child sessions (headless + visible)
- **charts.py**: API-based chart lookup. `ChartQuery.parse()` normalizes names. Fuzzy matching, multi-page PDF merging, auto-rotation via pypdf
- **procedures.py**: SOP/procedure lookup. `ProcedureQuery.parse()` handles section/search args. PDF section navigation via text extraction
- **routes.py**: TEC/AAR/ADR routes, LOA rules, real-world routes scraping
- **atis.py**: ATIS for SFO/SJC/RNO/OAK/SMF (no caching - time-sensitive)
- **icao.py**: Airline/airport/aircraft lookups with cache (`~/.zoa-ref/cache/`, 7-day TTL). `CodesPage` for persistent page reuse
- **cifp.py**: FAA CIFP (ARINC 424) data download and parsing. Provides procedure data (SIDs, STARs, approaches). Auto-downloads per AIRAC cycle.
- **nasr.py**: FAA NASR data download and parsing. Provides navaid data (NAV.txt) and airway data (AWY.txt). Auto-downloads per AIRAC cycle.
- **navaids.py**: Re-exports navaid functions from nasr.py. Provides navaid aliasing for chart lookup (e.g., "FMG1" → "MUSTANG1")
- **mea.py**: MEA/MOCA altitude analysis for routes using airway data from nasr.py
- **positions.py**: ATC position lookup (name, TCP, callsign, frequency). Cached.
- **scratchpads.py**: STARS scratchpad code lookup per facility. Cached.
- **approaches.py**: Analyzes STAR endpoints and approach IAFs/IFs to find connections
- **descent.py**: 3-degree glideslope calculator (~318 ft/nm)
- **display.py**: Output formatting for all result types
- **input.py**: Prompt session with history, disambiguation prompts
- **cli_utils.py**: Help text, argument parsing utilities, `InteractiveContext`
- **config.py**: Centralized constants (cache dir, TTL, base URLs, external tool URLs)

## Key Patterns

- **Checkout install**: `install.py` installs a snapshot via `uv tool install --constraints` (exported from `uv.lock`) outside the repo (the daily cleanup deletes `.venv`); `run.py` reinstalls only when `src/`, `pyproject.toml` or `uv.lock` changed. Both are stdlib-only and never import `zoa_ref`

- **CLI/Interactive parity**: All command logic lives in `commands.py`. When adding or modifying commands, update the shared `do_*` function—not the CLI or interactive handler directly
- Chart names normalized: digits → words ("5" → "FIVE"), fuzzy matching
- Chart type inference: ILS/LOC/VOR → IAP, etc.
- Multi-page charts (CONT.1, CONT.2) auto-merged
- PDF auto-rotation based on text orientation (disable with `--no-rotate`)
- Opened PDFs use stable `processed/current/` links (symlink, else hardlink, else copy) so browser history survives AIRAC changes
- Ambiguous matches show numbered disambiguation prompt
- `chart` uses API (fast); `charts` uses browser (browsing)
- Interactive mode: headless session for ICAO, visible for charts
- SOP section lookup: extracts PDF text, matches headings, opens at page
- Approaches: detects STAR vs fix by trailing digit; parses chart PDFs for waypoints
- Descent: FL-style altitudes (100 = 10,000), mode determined by second arg format

## Data Sources

- Charts API: `charts-api.oakartcc.org/v1/charts?apt=<airport>`
- Reference Tool: `reference.oakartcc.org/{charts,routes,atis,codes,positions,scratchpads}`
- SOP PDFs: Linked from Reference Tool procedures page
- CIFP: FAA ARINC 424 procedure data (`aeronav.faa.gov/Upload_313-d/cifp/`)
- NASR: FAA navaid and airway data (`nfdc.faa.gov/webContent/28DaySub/`)
- External tools: `airspace.oakartcc.org`, `tdls.virtualnas.net`, `strips.virtualnas.net`

## Workflow

- Always confirm with the user before creating a commit
