---
paths:
  - src/zoa_ref/charts.py
  - src/zoa_ref/procedures.py
  - src/zoa_ref/approaches.py
  - src/zoa_ref/descent.py
---

# Charts, SOPs, approaches and descent

- Chart names normalized: digits → words ("5" → "FIVE"), fuzzy matching
- Chart type inference: ILS/LOC/VOR → IAP, etc.
- Multi-page charts (CONT.1, CONT.2) auto-merged
- PDF auto-rotation based on text orientation (disable with `--no-rotate`)
- Ambiguous matches show numbered disambiguation prompt
- `chart` uses API (fast); `charts` uses browser (browsing)
- Interactive mode: headless session for ICAO, visible for charts
- SOP section lookup: extracts PDF text, matches headings, opens at page
- Approaches: detects STAR vs fix by trailing digit; waypoints come from CIFP
- Descent: FL-style altitudes (100 = 10,000), mode determined by second arg format
