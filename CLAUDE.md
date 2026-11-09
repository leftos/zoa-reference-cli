# CLAUDE.md

## Project Overview

The architecture entry point is [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): Task Index, layers, integration footguns, test locations and the deep docs.

ZOA Reference CLI - command-line lookups for ZOA's (Oakland ARTCC) Reference Tool. Provides charts, routes, ATIS, ICAO codes, and SOPs. Uses Playwright for browser automation and REST API for chart data. `zoa --help` and the README list the commands.

## Commands

```bash
python install.py                       # Install `zoa` outside the repo (uv tool), on PATH
python run.py <zoa args>                # Reinstall if src/ changed, then run zoa
uv run pytest                           # Tests (uses the repo .venv)
```

## Key Patterns

- **Checkout install**: `install.py` installs a snapshot via `uv tool install --constraints` (exported from `uv.lock`) outside the repo (the daily cleanup deletes `.venv`); `run.py` reinstalls only when `src/`, `pyproject.toml` or `uv.lock` changed. Both are stdlib-only and never import `zoa_ref`
- **CLI/Interactive parity**: All command logic lives in `commands.py`. When adding or modifying commands, update the shared `do_*` function—not the CLI or interactive handler directly
