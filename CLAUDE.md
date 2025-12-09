# CLAUDE.md

## Project Overview

ZOA Reference CLI - command-line lookups for ZOA's (Oakland ARTCC) Reference Tool. Provides charts, routes, ATIS, ICAO codes, and SOPs. Uses Playwright for browser automation and REST API for chart data.

## Commands

```bash
# Setup
uv venv && uv pip install -e .
.venv/Scripts/playwright install

# Charts (implicit or explicit)
.venv/Scripts/zoa OAK CNDEL5            # Implicit chart lookup (opens PDF)
.venv/Scripts/zoa chart OAK ILS 28R     # Explicit chart lookup
.venv/Scripts/zoa chart OAK ILS 28R -r  # Rotate 90°
.venv/Scripts/zoa charts OAK CNDEL5     # Browse on Reference Tool
.venv/Scripts/zoa list OAK              # List airport charts
.venv/Scripts/zoa list OAK DP           # List departure procedures (aliases: SID)
.venv/Scripts/zoa list OAK STAR         # List arrivals (also: IAP/APP, APD/TAXI)

# Routes, ATIS, ICAO
.venv/Scripts/zoa route SFO LAX         # Route lookup
.venv/Scripts/zoa atis SFO              # Single airport ATIS
.venv/Scripts/zoa atis --all            # All airports ATIS
.venv/Scripts/zoa airline UAL           # Airline code lookup
.venv/Scripts/zoa airport KSFO          # Airport code lookup
.venv/Scripts/zoa aircraft B738         # Aircraft type lookup

# SOPs/Procedures
.venv/Scripts/zoa sop OAK               # Open OAK SOP
.venv/Scripts/zoa sop OAK 2-2           # Jump to section 2-2
.venv/Scripts/zoa sop --list            # List all procedures

# Interactive mode
.venv/Scripts/zoa                       # Default: system browser
.venv/Scripts/zoa --playwright          # Managed browser with tab reuse
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
- **display.py**: Output formatting for all result types
- **input.py**: Prompt session with history, disambiguation prompts
- **cli_utils.py**: Help text, argument parsing utilities, `InteractiveContext`

## Key Patterns

- **CLI/Interactive parity**: All command logic lives in `commands.py`. When adding or modifying commands, update the shared `do_*` function—not the CLI or interactive handler directly
- Chart names normalized: digits → words ("5" → "FIVE"), fuzzy matching
- Chart type inference: ILS/LOC/VOR → IAP, etc.
- Multi-page charts (CONT.1, CONT.2) auto-merged
- PDF auto-rotation based on text orientation (disable with `--no-rotate`)
- Ambiguous matches show numbered disambiguation prompt
- `chart` uses API (fast); `charts` uses browser (browsing)
- Interactive mode: headless session for ICAO, visible for charts
- SOP section lookup: extracts PDF text, matches headings, opens at page

## Data Sources

- Charts API: `charts-api.oakartcc.org/v1/charts?apt=<airport>`
- Reference Tool: `reference.oakartcc.org/{charts,routes,atis,codes}`
- SOP PDFs: Linked from Reference Tool procedures page

## Workflow

- Always confirm with the user before creating a commit
