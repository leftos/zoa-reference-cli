# ZOA Reference CLI

A command-line tool for quick lookups to [ZOA's Reference Tool](https://reference.oakartcc.org). Look up aviation charts, routes, ATIS, and ICAO codes for Oakland ARTCC airports directly from your terminal.

## Installation

Requires Python 3.10+.

### Quick Install

Run the installation script which handles everything automatically:

```bash
git clone https://github.com/leftos/zoa-reference-cli.git
cd zoa-reference-cli
python install.py
```

This will:
- Install uv (if not present)
- Create a virtual environment
- Install project dependencies
- Install Playwright Chromium browser

### Manual Installation

```bash
# Clone the repository
git clone https://github.com/leftos/zoa-reference-cli.git
cd zoa-reference-cli

# Create virtual environment and install
uv venv
uv pip install -e .

# Install Playwright browsers (first time only)
.venv/Scripts/playwright install
```

## Usage

### Chart Lookup

Look up instrument procedures and charts:

```bash
zoa chart OAK CNDEL5      # CNDEL FIVE departure - opens PDF directly
zoa chart SFO ILS 28L     # ILS RWY 28L approach at SFO
zoa chart SJC RNAV 30L    # RNAV approach to runway 30L
zoa chart OAK ILS 28R --headless  # Output PDF URL only
```

The tool automatically:
- Normalizes chart names (e.g., "CNDEL5" becomes "CNDEL FIVE")
- Uses fuzzy matching to find the correct chart
- Merges multi-page charts (continuation pages) into a single PDF

### Browse Charts

Use the `charts` command to stay on the Reference Tool page for browsing:

```bash
zoa charts OAK CNDEL5     # Open chart, browse other OAK charts
zoa charts SFO ILS 28L    # Open ILS 28L, browse other SFO charts
```

Unlike `chart`, this keeps you on the Reference Tool page to explore other charts for the same airport.

### List Charts

List all available charts for an airport:

```bash
zoa list OAK
zoa list SFO
```

### Route Lookup

Search for routes between airports:

```bash
zoa route SFO LAX           # Show routes (top 5 real world)
zoa route SFO LAX -a        # Show all real world routes
zoa route SFO LAX -f        # Include recent flights
zoa route SFO LAX -a -f     # Show everything
zoa route SFO LAX -n 10     # Show top 10 real world routes
zoa route OAK SAN --browser # Open browser to view results
```

Route results include:
- TEC/AAR/ADR routes
- LOA (Letter of Agreement) rules
- Real world routes from historical data
- Recent flights (with `-f` flag)

### ATIS Lookup

Get current ATIS for ZOA airports:

```bash
zoa atis SFO            # Show ATIS for SFO
zoa atis OAK            # Show ATIS for Oakland
zoa atis --all          # Show ATIS for all airports
zoa atis SFO --browser  # Open ATIS page in browser
```

Supported ATIS airports: SFO, SJC, RNO, OAK, SMF

ATIS data is fetched live (not cached) since it changes frequently.

### Airline Lookup

Search for airlines by ICAO code, telephony, or name:

```bash
zoa airline UAL            # Search by ICAO ID
zoa airline united         # Search by telephony/name
zoa airline "United Air"   # Multi-word search
zoa airline UAL --browser  # Open in browser
zoa airline UAL --no-cache # Bypass cache for fresh data
```

Results include ICAO ID, telephony, airline name, and country.

### Airport Code Lookup

Search for airports by ICAO code, FAA ID, or name:

```bash
zoa airport KSFO           # Search by ICAO ID
zoa airport SFO            # Search by FAA local ID
zoa airport "San Francisco" # Search by name
zoa airport SFO --no-cache # Bypass cache
```

Results include ICAO ID, local (FAA) ID, and airport name.

### Aircraft Lookup

Search for aircraft by type designator or manufacturer/model:

```bash
zoa aircraft B738          # Search by type designator
zoa aircraft boeing        # Search by manufacturer
zoa aircraft "737-800"     # Search by model
zoa aircraft B738 --no-cache # Bypass cache
```

Results include type designator, manufacturer, model, engine type, FAA weight class, CWT, SRS, and LAHSO category.

### List Airports

View all supported ZOA airports:

```bash
zoa airports
```

### Interactive Mode

Run without arguments to enter interactive mode:

```bash
zoa
```

In interactive mode:
- The browser stays open between queries for faster lookups
- ICAO code lookups use a persistent background page for instant results
- All commands work without the `zoa` prefix

Available interactive commands:
- `<airport> <chart>` - Look up a chart (e.g., `OAK CNDEL5`)
- `charts <query>` - Browse charts in browser (e.g., `charts OAK CNDEL5`)
- `list <airport>` - List charts for an airport
- `route <dep> <arr>` - Look up routes
- `atis <airport>` - Look up ATIS (e.g., `atis SFO` or `atis all`)
- `airline <query>` - Look up airline codes
- `airport <query>` - Look up airport codes
- `aircraft <query>` - Look up aircraft types
- `help` - Show help
- `quit` / `exit` / `q` - Exit

## Options

### Chart Commands
- `--headless` - Run browser in headless mode (outputs PDF URL)

### Route Command
- `--browser` - Open browser instead of CLI display
- `-a, --all-routes` - Show all real world routes
- `-f, --flights` - Show recent flights
- `-n, --top N` - Number of real world routes to show (default: 5)

### ATIS Command
- `-a, --all` - Show ATIS for all airports
- `--browser` - Open browser instead of CLI display

### ICAO Commands (airline, airport, aircraft)
- `--browser` - Open browser instead of CLI display
- `--no-cache` - Bypass cache and fetch fresh data

## Caching

ICAO code lookups (airline, airport, aircraft) are cached locally for 7 days to provide instant lookups. Cache is stored in `~/.zoa-ref/cache/`. Use `--no-cache` to bypass the cache and fetch fresh data.

## Supported Airports

Major: SFO, OAK, SJC, SMF, RNO, FAT, MRY, BAB

Other: APC, CCR, CIC, HWD, LVK, MER, MHR, MOD, NUQ, PAO, RDD, RHV, SAC, SCK, SNS, SQL, STS, SUU, TRK
