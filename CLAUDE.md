# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ZOA Reference CLI is a command-line tool for quick lookups to ZOA's (Oakland ARTCC) Reference Tool at reference.oakartcc.org. It provides lookups for aviation charts, routes, and ICAO codes (airlines, airports, aircraft). Uses Playwright for browser automation and a REST API for chart data.

## Common Commands

```bash
# Install dependencies
uv venv && uv pip install -e .

# Install Playwright browsers (required first time)
.venv/Scripts/playwright install

# Run the CLI
.venv/Scripts/zoa chart OAK CNDEL5      # Look up a chart (opens PDF)
.venv/Scripts/zoa charts OAK CNDEL5     # Browse charts (stays on Reference Tool)
.venv/Scripts/zoa list OAK              # List charts for an airport
.venv/Scripts/zoa route SFO LAX         # Look up routes
.venv/Scripts/zoa atis SFO              # Look up ATIS for an airport
.venv/Scripts/zoa atis --all            # Look up ATIS for all airports
.venv/Scripts/zoa airline UAL           # Look up airline codes
.venv/Scripts/zoa airport KSFO          # Look up airport codes
.venv/Scripts/zoa aircraft B738         # Look up aircraft types
.venv/Scripts/zoa                       # Interactive mode
```

## Architecture

The codebase consists of six modules in `src/zoa_ref/`:

- **cli.py**: Click-based CLI with commands (`chart`, `charts`, `list`, `airports`, `route`, `atis`, `airline`, `airport`, `aircraft`) and interactive mode. Entry point is `main()`.
- **browser.py**: `BrowserSession` class wrapping Playwright's sync API for Chromium automation. Supports context manager pattern and child sessions (for headless ICAO lookups alongside visible browser).
- **charts.py**: Chart lookup logic using the charts API (`charts-api.oakartcc.org`). `ChartQuery.parse()` normalizes queries. Uses fuzzy matching via `_calculate_similarity()`. Supports multi-page PDF merging via pypdf.
- **routes.py**: Route search logic. Scrapes TEC/AAR/ADR routes, LOA rules, real-world routes, and recent flights from tables.
- **atis.py**: ATIS lookup for 5 airports (SFO, SJC, RNO, OAK, SMF). Scrapes live ATIS data from the reference tool (no caching - data is time-sensitive).
- **icao.py**: ICAO code lookups for airlines, airports, and aircraft. Includes caching system (`~/.zoa-ref/cache/`, 7-day TTL) and `CodesPage` class for persistent page reuse in interactive mode.

## Key Patterns

- All browser automation uses Playwright's sync API (`sync_playwright`)
- Chart names ending in digits are normalized to words (e.g., "5" → "FIVE") for matching
- Chart type inference from naming patterns (ILS/LOC/VOR → IAP, etc.)
- Route scraping identifies tables by preceding H1 text, not table classes
- `chart` command uses API for fast lookups; `charts` command uses browser for browsing
- Multi-page charts (with CONT.1, CONT.2 pages) are automatically detected and merged
- ICAO lookups check cache first, then scrape if needed
- Interactive mode uses child browser sessions: visible browser for charts, headless for ICAO lookups
- `CodesPage` class pre-navigates to codes page for instant repeated lookups

## Data Sources

- **Charts API**: `https://charts-api.oakartcc.org/v1/charts?apt=<airport>`
- **Reference Tool**: `https://reference.oakartcc.org/charts` (browser-based)
- **Routes**: `https://reference.oakartcc.org/routes` (browser scraping)
- **ATIS**: `https://reference.oakartcc.org/atis` (browser scraping, no caching)
- **ICAO Codes**: `https://reference.oakartcc.org/codes` (browser scraping with caching)
