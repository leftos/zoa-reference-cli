# NCT entry and exit route lookup

Design for `zoa xfer`: given a sector, flow, aircraft class and destination or route, return the one applicable handoff row from the NCT SOP or the NCT-ZOA LOA.

## Problem

New NCT controllers struggle to find the right entry and exit route. The answer depends on the sector, the flow, the aircraft class and the destination or route, but the documents are organized differently:

- The SOP files rows by sector, then flow, then neighbouring sector, and prints each handoff twice: as an exit in one sector and an entry in the next.
- The LOA (Attachment 3) files rows by ZOA sector and geography, such as "west of NLC".
- Vocabulary shifts: the SOP's "Napa CX" is the LOA's "Wine Country", and "San Jose CX" needs SOP §1-4 to know it includes PAO.
- OAKE has its own SOP sections only for Boulder, Foster, Grove, Richmond and Sutro. Other sectors put it in row labels such as "Sunol (SFOW/OAKE)".

## Decisions

- **Primary moment: live on position.** Output is a terse answer. Sector cards, whole-flight traces and drills may reuse the data later, but they don't shape the first version.
- **Input: typed first.** For example `zoa xfer morgan SFO J`. It works offline and is testable. Callsign lookup through the VATSIM data feed is a later step.
- **Data: a reviewed file in the repo.** A dev-only extractor drafts it from the PDFs, a person reviews it, and it is committed stamped with the source versions (SOP v1.13, LOA CHG08). The CLI reads only this file and never parses PDFs for this feature.
- **Staleness: warn.** When a downloaded PDF no longer matches the stamped source, the lookup warns and keeps answering from the reviewed data.
- **Conflicts: show both, and check.** Where an exit row and its reciprocal entry row disagree, the lookup prints both versions with a warning. A reciprocal checker compares all such pairs and produces an errata list for the facility.
- **Flow: a persistent setting.** A `flow` command stores the active flows and injects them into later lookups, and `--flow` overrides per call. When a flow is not set, the lookup warns and assumes SFOW, SMFS and RNOS. Every answer prints the flow it used.
- **Combined sectors: show the chain.** The answer names the SOP's receiving sector, its handoff symbol and its "combines to" chain, such as "Licke (combines to Toga, then Morgan)". Naming who is actually online waits for the VATSIM feed.
- **No LLM answers.** A confidently wrong altitude is worse than a slow search, so every answer is a real row with its section and page.

## Extraction findings

`pdfplumber` finds the grid in every SOP exit and entry table and every LOA Attachment 3 table, with its title. The traps a parser has to handle:

- Merged cells come through as gaps to fill from the cell above.
- Wrapped text arrives as extra rows, and it can be told apart from a real row only by the ruled lines.
- Raw column counts vary between tables, so columns must be mapped from the header positions.
- Some merged labels are floating text boxes that also appear as separate one-column tables.
- A few cells need a human reading. Boulder→Seca "Landing MRY" reads "5,000 7,000" in the Boulder SFOW exit table, while Seca's entry table says 7,000.
- A flow can sit in the sector label ("Valley (SFOW)", "Licke (SJCE/SFOE)"), in the route ("(HWD only)") or in the info column ("OSI RV 110° (SFOW)").

Extraction needs no new runtime dependency, since `pdfplumber` is only for the dev-only extractor.

## Data model

One row per handoff, in a form the checker and lookup can both use:

| Field | Example |
|---|---|
| `from` / `to` | `Morgan` / `Cedar`, or a ZOA sector |
| `flows` | `SFOW` (empty means every flow) |
| `dest_or_route` | `SFO`, `V111`, `EMZOH` |
| `aircraft` | `T, J` |
| `altitude` | `14,000` |
| `info` | `RV ALWYS/MOD` |
| `restrictions` | control limits and conditions on the row |
| `source` | `SOP §3-4 p22` |

Beside the rows:

- Sectors: area, symbol, frequency and "combines to", from the SOP's General Information tables, and the LOA's handoff codes.
- Complexes: the airport lists from SOP §1-4, so a destination resolves to rows that say "San Jose CX".
- Aliases: "Wine Country" for "Napa CX", and similar.
- Each sector's and flow's P-ACP lines, attached by section so an answer can list those that mention the row's route or sector.

## Default rules the data must carry

The tables rely on prose elsewhere, so an answer must apply these:

- SOP §1-13: "RV", "Direct" and "FDIO" meanings. Without a listed route, the aircraft flies its TEC route, or failing that its filed route or direct to the first fix outside NCT.
- SOP §1-15: the receiving controller's default control for turns, speed, and climb or descent.
- LOA §2: NCT and ZOA default control (RV 30° left or right plus descent or climb), and control additions that apply "in addition" unless marked "only".
- LOA §2(n): an empty "Handoff To" means the first sector the aircraft enters. Answering this exactly needs sector geometry, so the first version says that rule in words rather than naming a sector.

## Command surface

Follows the five-registry rule in `docs/ARCHITECTURE.md` (Integration Footguns): logic in a `do_*` function in `commands.py`, front ends in `cli.py` and `interactive.py`, help in `cli_utils.py`, and completion in `autocomplete.py`.

- `zoa xfer <sector> <dest-or-route> [class]`, with `--flow`: rows out of the sector. Entry rows are available with a direction flag. For example `zoa xfer morgan SFO J` under SFOW gives "Cedar, 14,000, RV ALWYS/MOD, SOP §3-4 p22". The class is optional and without it every class's rows print.
- `zoa flow [SFOW|SFOE|OAKE|SJCE|SMFS|SMFN|RNOS|RNON ...]`: show or set the active flows, in `~/.zoa-ref/`. The set must allow a Bay flow, a Sacramento flow and a Reno flow together.
- LOA rows use the same lookup. `zoa xfer zoa SFO` lists arrivals, and a sector-to-ZOA query returns the exit row with its control statements.

## Steps

1. Extractor (dev-only script) that writes draft data from both PDFs, covered by tests against saved extractor output.
2. Review the draft by hand and commit the data with its source stamp. Resolve ambiguous cells against the rendered pages.
3. Reciprocal checker, run over the data, producing the errata list.
4. Lookup core and `zoa xfer`, covered by tests against the reviewed data, including the conflict warning.
5. `zoa flow`, with the persisted setting, the warning and the defaults.
6. Combine chain and P-ACP lines in the output.
7. Stale-source warning.

## Known conflicts

Found by hand, with page numbers counted as PDF pages. The reciprocal checker will produce the full list.

- **Grove→Toga, HWD jets, SFOW:** "at least 3 miles east of MABRY" in Grove's exit table (SOP p91), but "west of MABRY" in Toga's entry table (SOP p33).
- **Morgan→Sunol, LVK, SFOE:** 10,000 in Morgan's exit table (SOP p22), but "12,000 or lower filed" in Sunol's entry table (SOP p89).
- **Cedar SFOE, T263/PXN/AVE:** Cedar's exit table sends these to Valley (SOP p55), Morgan's entry table claims them (SOP p23), and Valley's SFOE entry table has no Cedar row (SOP p84).
- **Seca's handoff code:** `Q2S` in the LOA (LOA p11), but symbol `1S` in the SOP (SOP p18).

## Later

- Callsign lookup through the VATSIM data feed, including who is actually online for the combine chain.
- Whole-flight trace, chaining rows through NCT and out the LOA exit.
- Printable sector cards and practice drills from the same data.
- Sector geometry from the SOP's diagrams, to name the first sector entered. The diagrams look like vector drawings, but this hasn't been tried.
