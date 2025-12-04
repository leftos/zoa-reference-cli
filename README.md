# ZOA Reference CLI

A command-line tool for quick lookups to [ZOA's Reference Tool](https://reference.oakartcc.org). Look up aviation charts and routes for Oakland ARTCC airports directly from your terminal.

## Installation

Requires Python 3.10+.

### Quick Install

Run the installation script which handles everything automatically:

```bash
git clone https://github.com/yourusername/zoa-reference-cli.git
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
git clone https://github.com/yourusername/zoa-reference-cli.git
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
zoa chart OAK CNDEL5      # CNDEL FIVE departure at OAK
zoa chart SFO ILS 28L     # ILS RWY 28L approach at SFO
zoa chart SJC RNAV 30L    # RNAV approach to runway 30L
```

The tool automatically normalizes chart names (e.g., "CNDEL5" becomes "CNDEL FIVE") and uses fuzzy matching to find the correct chart.

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
zoa route SFO LAX -n 10     # Show top 10 real world routes
zoa route OAK SAN --browser # Open browser to view results
```

Route results include:
- TEC/AAR/ADR routes
- LOA (Letter of Agreement) rules
- Real world routes from historical data
- Recent flights (with `-f` flag)

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

In interactive mode, the browser stays open between queries for faster lookups.

## Options

- `--headless` - Run browser in headless mode (chart command)
- `--browser` - Open browser instead of CLI display (route command)
- `-a, --all-routes` - Show all real world routes
- `-f, --flights` - Show recent flights
- `-n, --top N` - Number of real world routes to show (default: 5)

## Supported Airports

Major: SFO, OAK, SJC, SMF, RNO, FAT, MRY, BAB

Other: APC, CCR, CIC, HWD, LVK, MER, MHR, MOD, NUQ, PAO, RDD, RHV, SAC, SCK, SNS, SQL, STS, SUU, TRK
