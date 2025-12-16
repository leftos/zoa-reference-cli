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
zoa OAK CNDEL5            # Implicit chart lookup (no 'chart' needed)
zoa chart OAK CNDEL5      # CNDEL FIVE departure - opens PDF directly
zoa chart SFO ILS 28L     # ILS RWY 28L approach at SFO
zoa chart SJC RNAV 30L    # RNAV approach to runway 30L
zoa chart OAK ILS 28R -l  # Output PDF URL only (--link)
```

The tool automatically:
- Normalizes chart names (e.g., "CNDEL5" becomes "CNDEL FIVE")
- Uses fuzzy matching to find the correct chart
- Merges multi-page charts (continuation pages) into a single PDF
- Auto-rotates PDFs based on text orientation
- Shows numbered disambiguation when multiple charts match

Rotation options:
```bash
zoa chart OAK CNDEL5 -r          # Rotate 90°
zoa chart OAK CNDEL5 --rotate 180  # Rotate specific degrees
zoa chart OAK CNDEL5 --no-rotate   # Disable auto-rotation
```

### Browse Charts

Use the `charts` command to stay on the Reference Tool page for browsing:

```bash
zoa charts OAK CNDEL5     # Open chart, browse other OAK charts
zoa charts SFO ILS 28L    # Open ILS 28L, browse other SFO charts
```

Unlike `chart`, this keeps you on the Reference Tool page to explore other charts for the same airport.

### List Charts

List all available charts for an airport, optionally filtered by type or content:

```bash
zoa list OAK               # List all OAK charts
zoa list SFO DP            # List departure procedures (aliases: SID)
zoa list OAK STAR          # List arrivals
zoa list SJC IAP           # List instrument approaches (aliases: APP)
zoa list RNO APD           # List airport diagrams (aliases: TAXI)
zoa list SMF APP TENCO     # Search approaches for 'TENCO' text
zoa list OAK DP PORTE      # Search departures for 'PORTE' text
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
```

Supported ATIS airports: SFO, SJC, RNO, OAK, SMF

ATIS data is fetched live (not cached) since it changes frequently.

### SOP/Procedure Lookup

Look up Standard Operating Procedures and jump to specific sections:

```bash
zoa sop OAK                        # Open Oakland ATCT SOP
zoa sop OAK 2-2                    # Open OAK SOP at section 2-2
zoa sop "NORCAL TRACON"            # Open NORCAL TRACON SOP
zoa sop SJC "IFR Departures" SJCE  # Find SJCE in IFR Departures section
zoa sop --list                     # List all available procedures
zoa proc OAK                       # 'proc' is an alias for 'sop'
```

The tool extracts PDF text and matches section headings to open documents at the correct page. Multi-step lookups let you search for text within a specific section.

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

### Navaid Lookup

Search for navaids by identifier or name:

```bash
zoa navaid FMG            # Search by identifier (MUSTANG VORTAC)
zoa navaid MUSTANG        # Search by name
zoa navaid SFO            # Search for San Francisco VOR
zoa navaid OAKLAND        # Search by city/name (partial match)
```

Results include type (VOR, VORTAC, TACAN, NDB), location, and coordinates.

### Position Lookup

Search for ATC positions by name, TCP code, callsign, or frequency:

```bash
zoa position NCT           # Search by TCP code
zoa position 125.35        # Search by frequency
zoa position "NorCal"      # Search by callsign/name
zoa position OAK           # Search for Oakland positions
zoa pos NCT                # 'pos' is an alias for 'position'
zoa position --browser     # Open positions page in browser
```

Results include position name, TCP code, callsign, and frequencies.

### Scratchpad Lookup

Look up STARS scratchpad codes for a facility:

```bash
zoa scratchpad OAK         # Show OAK scratchpads
zoa scratchpad NCT         # Show NorCal TRACON scratchpads
zoa scratch OAK            # 'scratch' is an alias for 'scratchpad'
zoa scratchpad --list      # List available facilities
```

### Approaches Lookup

Find approaches connected to a STAR or fix:

```bash
zoa approaches RNO SCOLA1  # Find approaches for SCOLA ONE STAR
zoa approaches OAK EMZOH4  # Find approaches for EMZOH FOUR STAR
zoa approaches RNO KLOCK   # Find approaches via KLOCK fix
zoa apps OAK MYSHN         # 'apps' is an alias for 'approaches'
```

When a STAR endpoint or fix matches an IAF/IF on an approach, aircraft can fly directly to the approach without vectors.

### Descent Calculator

Calculate descent parameters for a 3-degree glideslope:

```bash
zoa descent 100 020        # Distance needed: 10,000 ft to 2,000 ft
zoa des 100 12.5           # Altitude at 12.5 nm from 10,000 ft
zoa des 100 5              # Altitude at 5 nm from 10,000 ft
zoa des 080 040            # Distance needed: 8,000 ft to 4,000 ft
```

Altitudes use FL-style notation (100 = 10,000 ft). The second argument determines mode:
- 3 digits: target altitude - calculates distance needed
- 1-2 digits or decimal: distance - calculates altitude at that point

### External Tools

Open ZOA external tools in your browser:

```bash
zoa vis                    # Open ZOA airspace visualizer
zoa tdls                   # Open TDLS (Pre-Departure Clearances)
zoa tdls RNO               # Open TDLS for specific facility
zoa strips                 # Open flight strips
zoa strips NCT             # Open flight strips for specific facility
```

### Interactive Mode

Run without arguments to enter interactive mode:

```bash
zoa                      # Use system browser (default)
zoa --playwright         # Use managed Playwright browser with tab reuse
```

In interactive mode:
- The browser stays open between queries for faster lookups
- ICAO code lookups use a persistent background page for instant results
- All commands work without the `zoa` prefix
- `--playwright` mode reuses browser tabs for charts (avoids tab accumulation)

Available interactive commands:
- `<airport> <chart>` - Look up a chart (e.g., `OAK CNDEL5`)
- `chart <query>` - Same as above (e.g., `chart OAK CNDEL5`)
- `charts <query>` - Browse charts in browser (e.g., `charts OAK CNDEL5`)
- `list <airport> [type] [search]` - List/search charts for an airport
- `route <dep> <arr>` - Look up routes
- `atis <airport>` - Look up ATIS (e.g., `atis SFO` or `atis all`)
- `sop <query>` - Look up SOP/procedure (e.g., `sop OAK IFR`)
- `proc <query>` - Same as above (e.g., `proc OAK IFR`)
- `airline <query>` - Look up airline codes
- `airport <query>` - Look up airport codes
- `aircraft <query>` - Look up aircraft types
- `navaid <query>` - Look up navaid (e.g., `navaid FMG`)
- `position <query>` / `pos <query>` - Look up ATC positions
- `scratchpad <facility>` / `scratch <facility>` - Look up scratchpads
- `approaches <airport> <star|fix>` / `apps` - Find approaches for STAR/fix
- `descent <alt> <alt|nm>` / `des` - Descent calculator
- `vis` - Open airspace visualizer
- `tdls [facility]` - Open TDLS
- `strips [facility]` - Open flight strips
- `help [command]` - Show help (e.g., `help sop`)
- `quit` / `exit` / `q` - Exit

## Options

### Chart Commands
- `-l, --link` - Output PDF URL only (don't open)
- `-r` - Rotate chart 90°
- `--rotate 90|180|270` - Rotate chart by specific degrees
- `--no-rotate` - Disable auto-rotation

### Route Command
- `--browser` - Open browser instead of CLI display
- `-a, --all-routes` - Show all real world routes
- `-f, --flights` - Show recent flights
- `-n, --top N` - Number of real world routes to show (default: 5)

### ATIS Command
- `-a, --all` - Show ATIS for all airports

### SOP/Procedure Commands
- `--list` - List all available procedures
- `--no-cache` - Bypass cache and fetch fresh data

### ICAO Commands (airline, airport, aircraft)
- `--browser` - Open browser instead of CLI display
- `--no-cache` - Bypass cache and fetch fresh data

### Position Command
- `--browser` - Open browser instead of CLI display
- `--no-cache` - Bypass cache and fetch fresh data

### Scratchpad Command
- `--list` - List available facilities
- `--no-cache` - Bypass cache and fetch fresh data

## Caching

ICAO code lookups (airline, airport, aircraft), positions, and scratchpads are cached locally for 7 days to provide instant lookups. Cache is stored in `~/.zoa-ref/cache/`. Use `--no-cache` to bypass the cache and fetch fresh data.
