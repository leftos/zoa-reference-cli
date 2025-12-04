# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ZOA Reference CLI is a command-line tool for quick lookups to ZOA's (Oakland ARTCC) Reference Tool at reference.oakartcc.org. It uses Playwright for browser automation to search aviation charts and routes.

## Common Commands

```bash
# Install dependencies
uv venv && uv pip install -e .

# Install Playwright browsers (required first time)
.venv/Scripts/playwright install

# Run the CLI
.venv/Scripts/zoa chart OAK CNDEL5      # Look up a chart
.venv/Scripts/zoa list OAK               # List charts for an airport
.venv/Scripts/zoa route SFO LAX          # Look up routes
.venv/Scripts/zoa                        # Interactive mode
```

## Architecture

The codebase consists of four modules in `src/zoa_ref/`:

- **cli.py**: Click-based CLI with commands (`chart`, `list`, `airports`, `route`) and interactive mode. Entry point is `main()`.
- **browser.py**: `BrowserSession` class wrapping Playwright's sync API for Chromium automation. Supports context manager pattern.
- **charts.py**: Chart lookup logic. `ChartQuery.parse()` normalizes queries (e.g., "CNDEL5" → "CNDEL FIVE"). Uses fuzzy matching via `_calculate_similarity()` to find chart buttons.
- **routes.py**: Route search logic. Scrapes TEC/AAR/ADR routes, LOA rules, real-world routes, and recent flights from tables.

## Key Patterns

- All browser automation uses Playwright's sync API (`sync_playwright`)
- Chart names ending in digits are normalized to words (e.g., "5" → "FIVE") for matching
- Chart type inference from naming patterns (ILS/LOC/VOR → IAP, etc.)
- Route scraping identifies tables by preceding H1 text, not table classes
