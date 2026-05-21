# CIFP Parser Drift: zoa-reference-cli vs YAAT

**Status:** all 9 actionable items fixed (2026-05-21). See "Resolution" section at the bottom for commit-by-commit log.
**Authored:** 2026-05-21 (by a Claude code-reviewer agent run from zoa-tutor).
**Audience:** future agent or human picking up the CIFP parser fix work.

## Background

Both `zoa-reference-cli` (Python) and YAAT (C#) parse FAA CIFP (Coded Instrument Flight Procedures) data in ARINC 424 format. CIFP is fixed-format text with one record per line; record subsection codes (`PA` = approach, `PD` = SID, `PE` = STAR, etc.) determine the schema.

The user (active VATSIM controller training for S3 TRACON at ZOA, NCT Area A) noticed YAAT renders procedures in a way that suggests its parser is more complete than `zoa-reference-cli`'s. This review confirms it.

Both code paths sit on top of upstream `cifparse` column offsets (the spec-checked Python reference). YAAT mostly stays faithful to that; `zoa-reference-cli` has drifted in several places.

## Files referenced

- YAAT:
  - `X:\dev\yaat\src\Yaat.Sim\Data\Vnas\CifpParser.cs`
  - `X:\dev\yaat\src\Yaat.Sim\Data\Vnas\CifpModels.cs`
  - `X:\dev\yaat\src\Yaat.Sim\Data\Vnas\CifpDataService.cs`
  - Tests under `X:\dev\yaat\tests\Yaat.Sim.Tests\`
- zoa-reference-cli:
  - `src/zoa_ref/cifp.py` (single ~1700-line file)
  - `src/zoa_ref/cache.py` (AIRAC cycle math, shared with rest of the CLI)

## Verdict

**Meaningfully behind YAAT.** The high-level surface (SIDs, STARs, approaches, fix lookups) is present, but several field-level decoders are flat wrong — most notably an altitude column off-by-one and a `× 10` scaling bug that together corrupt every altitude restriction emitted. YAAT also covers richer leg geometry (RF arcs, fly-over, recommended navaid, rho/theta), terminal-waypoint coordinates, navaid records, procedure-turn / hold-in-lieu detection, and a sane missed-approach split — none of which Python has.

For S3 TRACON training, the altitude bug is the headline problem: STAR/approach restrictions read out of `zoa-reference-cli` will not match the chart.

## Punch list

### 1. Altitude column off-by-one (and the `× 10` compensator) — HIGH

- **Category:** parsing-bug
- **YAAT ref:** `CifpParser.cs:491-499, 853-874`
- **zoa-ref-cli ref:** `cifp.py:1230-1232, 1264-1266, 1151-1197`

Per `cifparse` `PrimaryIndices` (the upstream reference checked into YAAT), `alt_desc = (82, 83)`, `alt_1 = (84, 89)`, `alt_2 = (89, 94)`. YAAT matches this exactly. zoa-ref-cli uses `line[82]` (OK), `line[83:88]` (off by one), `line[88:93]` (off by one). The 83rd column in ARINC is the `atc` indicator, not the start of `alt_1`. Worse, `_parse_altitude` in `cifp.py:1194-1195` then does `val * 10`, presumably to "fix" the visibly wrong numbers — `cifparse`'s `_get_altitude_fl` returns the integer feet directly (`"01700"` → `1700`).

**Net effect:** every non-FL altitude restriction parsed by `zoa-ref-cli` reads a shifted source field and inflates it 10×, then sometimes prints `f"FL{alt // 100}"` for `alt >= 18000`, so a 1,700 ft restriction can render as `FL170`. FAF/IF altitudes for SFO/OAK/SJC approaches are all in this range and will be garbage.

### 2. No fly-over flag — MEDIUM

- **Category:** missing-feature
- **YAAT ref:** `CifpParser.cs:462-463`, `CifpModels.cs:70` (`IsFlyOver` on `CifpLeg`)
- **zoa-ref-cli ref:** absent from `ProcedureLeg` (`cifp.py:204-216`)

YAAT reads char 40 (`"Y"` = fly-over) and exposes `IsFlyOver`. Python doesn't extract it. Affects rendering of fly-over waypoints (square symbols) and trajectory generation through them — for TRACON training the fly-over vs fly-by distinction matters on STARs where the heading change at the fix is the cue.

### 3. No RF-arc geometry (radius / center fix / lat-lon) — HIGH

- **Category:** missing-feature
- **YAAT ref:** `CifpParser.cs:524-568, 743-805` (arc_radius, center_fix, terminal-waypoint lookup for arc center coordinates)
- **zoa-ref-cli ref:** none

YAAT decodes `arc_radius` (cols 56-62), `center_fix` (cols 106-111), and resolves the center fix's lat/lon by parsing the airport's subsection-C terminal waypoints. zoa-ref-cli has no RF support at all. Several SFO and OAK RNAV approaches use RF transitions (e.g. CFPTK arcs); without radius+center the procedure path can't be drawn.

### 4. No recommended-navaid / theta / rho / course / distance / vert-angle — MEDIUM

- **Category:** missing-feature
- **YAAT ref:** `CifpParser.cs:514-557`
- **zoa-ref-cli ref:** none

YAAT decodes `rec_vhf` (col 50-54), `theta` (62-66), `rho` (66-70), `course` (70-74, tenths of degrees), `dist_time` (74-78, tenths of NM). Python skips all of these. Outbound course alone is needed to render CF/CA/VA legs honestly and to surface a "heading at fix" for ATC trainers.

### 5. Terminal-waypoint (subsection C) and navaid (SUSAD) records ignored — MEDIUM

- **Category:** coverage-gap
- **YAAT ref:** `CifpParser.cs:139-173` (`ParseTerminalWaypoints`), `:1008-1061` (`ParseNavaids`)
- **zoa-ref-cli ref:** absent

YAAT reads terminal waypoint coordinates (subsection `C`) and VOR/DME/NDB navaid coordinates (`SUSAD`). zoa-ref-cli only reads `D`/`E`/`F` subsections — useful only for fix lists. If the CLI ever needs to compute distance from an aircraft position to a procedure fix, it'd have to layer NavData on top.

### 6. Approach transition detection conflates SID/STAR/approach route types — MEDIUM

- **Category:** parsing-bug
- **YAAT ref:** `CifpParser.cs:600-603` (approaches: only `RouteType == 'A'` is a transition)
- **zoa-ref-cli ref:** `cifp.py:481-483` matches YAAT's approach behaviour, but `cifp.py:1310` lumps SID/STAR/Approach into one `route_type in ("1"..."6","A")` heuristic in `parse_procedure_leg`

For approaches the route-type codes are different (`A` = transition, `B` = base/common, etc. — see ARINC 424 §5.7). The shared `parse_procedure_leg` in Python applies a SID/STAR rule to approaches too, which means approach-procedure detail view classifies legs differently than `parse_approach_record`. The two parsers in the same file disagree about what counts as a "common" leg on an approach.

### 7. Missed approach not separated from common legs — HIGH

- **Category:** missing-feature
- **YAAT ref:** `CifpParser.cs:644-720` (splits legs at the MAP into `CommonLegs` / `MissedApproachLegs`)
- **zoa-ref-cli ref:** `cifp.py:1502-1517` (single `common_legs` list)

YAAT walks the sorted leg list, treats the MAP fix as the boundary, and emits `MissedApproachLegs` separately. Python's `CifpProcedureDetail` lumps the missed approach into `common_legs`. For training renderings this puts the climb-out fixes into the inbound segment.

### 8. No hold-in-lieu / procedure-turn detection — HIGH (for non-RNAV approaches)

- **Category:** missing-feature
- **YAAT ref:** `CifpParser.cs:132, 648-650, 676-685, 709-718, 728-740` (HoldInLieuLeg, ProcedureTurnLeg, HasHoldInLieu)
- **zoa-ref-cli ref:** none

YAAT exposes `HoldInLieuLeg`, `ProcedureTurnLeg`, and `HasHoldInLieu`. Python doesn't surface these even though it captures `path_terminator`. AIM 5-4-9 NoPT depiction depends on this; without it you cannot tell an HF (hold-in-lieu) approach from a regular one.

### 9. Path-terminator parsed as raw string, not enum — LOW

- **Category:** cosmetic / missing-feature
- **YAAT ref:** `CifpModels.cs:32-51`, `CifpParser.cs:807-829`
- **zoa-ref-cli ref:** `cifp.py:210` (`path_terminator: str`)

YAAT enumerates IF/TF/CF/DF/RF/AF/HA/HF/HM/PI/CA/FA/VA/VM/VI/CI/Other. Python just keeps the 2-char string. No correctness loss by itself, but downstream Python code has nothing to switch on. Combined with item 8 it's why HILPT goes undetected.

### 10. Turn direction read alongside a wrong column for fix-role — LOW (but compounding)

- **Category:** parsing-bug
- **YAAT ref:** `CifpParser.cs:466-484` (fix role from `line[42]`, turn direction from `line[43]`)
- **zoa-ref-cli ref:** `cifp.py:1259-1260` (waypoint_desc = `line[39:43]`, turn_direction = `line[43]`)

zoa-ref-cli's enhanced parser reads `waypoint_desc` as a 4-char span and then uses `waypoint_desc[0]` (col 39) — which is the route-description code, not the fix-role code. YAAT and `parse_approach_record` (in the same file, `cifp.py:461`) both correctly use col 42. So the legacy `parse_approach_record` is right, but the new `parse_procedure_leg` reads fix-role from col 39 and will misclassify IAF/IF/FAF/MAP. This is the same kind of bug as item 1 — two parsers in one file using different offsets.

### 11. Approach `routetype` and runway transitions vs feeders — NOT-A-DRIFT

- **YAAT ref:** `CifpParser.cs:600-602, 644-686`
- **zoa-ref-cli ref:** `cifp.py:78-114` (`feeder_paths`)

Python's `CifpApproach.feeder_paths` (first fix of each transition that isn't already an IAF/IF) is *not* a feature YAAT has — YAAT just exposes the transitions and lets the caller decide. This is the rare case where Python is ahead; useful for VATSIM map rendering. Worth keeping when porting forward.

### 12. STAR vs SID common-leg detection: empty transition vs "ALL" — NOT-A-DRIFT

- **YAAT ref:** `CifpParser.cs:362-364`
- **zoa-ref-cli ref:** `cifp.py:1511-1516`

Both treat `""` or `"ALL"` as common. No drift.

### 13. AIRAC cycle calculation — NOT-A-DRIFT

- **YAAT ref:** `AiracCycle.cs:8-71`
- **zoa-ref-cli ref:** `cache.py:21-52`

Both use epoch 2025-01-23 = cycle 2501, 28-day cycles, 13 cycles per year, identical formula. Cycle-id → effective-date mapping matches. zoa-ref-cli uses `date.today()` (local), YAAT uses `DateTime.UtcNow`; near midnight UTC this could disagree by one day. Low impact, but a one-line `datetime.now(tz=timezone.utc).date()` fix.

### 14. Continuation records not handled by either — LOW (both)

- **YAAT ref:** no `cont_rec_no` handling
- **zoa-ref-cli ref:** comment at `cifp.py:1282-1283` skips empty path-terminator records as a heuristic; not a real continuation-aware parse

Neither parser dispatches by `cont_rec_no` (col 38). Both rely on the primary record alone. `cifparse` handles continuation, simulation, and planning variants — for FAS data block, MDA, etc. — but YAAT/zoa don't need those for the current feature set. Flag for the future, not for now.

### 15. Procedure name disambiguation — Python is ahead

- **YAAT ref:** uses raw 6-char procedure ID; exposes `EnrouteTransitions` keyed by transition name
- **zoa-ref-cli ref:** `cifp.py:613-643, 750-758` — regex normalises `"SCOLA1"` and `"SCOLA ONE"`, plus tries navaid-identifier prefixes (e.g. `CCR2` for `CONCORD TWO`)

Python has more chart-name tolerance (good for CLI UX). YAAT doesn't try because it consumes canonical IDs. Keep this.

### 16. Speed restriction description (`+`/`-`/`@`) — Python is ahead (slightly)

- **YAAT ref:** `CifpParser.cs:502-507` (always `IsMaximum = true`)
- **zoa-ref-cli ref:** `cifp.py:1269-1306` (reads `speed_desc` from col 117)

`cifparse` says `speed_desc = (117, 118)` and Python uses `line[117]`, which is correct. YAAT's "always max" is fine for ATC purposes since "at or above" is rare on STARs, but Python's is more faithful.

## Suggested fix sequence

Group by effort, then severity.

### Easy ports (~1 hour each)

1. **Fix altitude columns + remove `× 10` compensator** (item 1). Set `line[84:89]` / `line[89:94]`, then delete the `× 10` in `_parse_altitude` and read FL/feet straight per `cifparse`. Add a regression test: load a real CIFP record for a known-altitude SFO approach FAF and assert the value matches the chart.
2. **Fix fix-role column in `parse_procedure_leg`** (item 10): read `line[42]` not `waypoint_desc[0]` — and align with the existing correct `parse_approach_record`. Add a unit test asserting IAF/IF/FAF classification for a known RNAV approach.
3. **Add `is_fly_over = line[40] == "Y"`** to `ProcedureLeg` (item 2).
4. **Decode `outbound_course`** (cols 70-74, tenths of degrees) and `leg_distance_nm` (cols 74-78, tenths of NM) into `ProcedureLeg` (item 4 partial — the most useful two fields).
5. **Switch DateTime to UTC** in cache lookups (item 13) — one-liner.

### Medium (~half-day each)

6. **Add path-terminator enum** (or string-set helpers) plus `is_hold_in_lieu` / `is_procedure_turn` flags on `CifpProcedureDetail` for approaches (items 8, 9). Mirror YAAT's `HoldInLieuTerminators = {"HA","HF","HM"}` and `"PI"` detection.
7. **Split missed-approach legs from common legs** at the MAP fix (item 7). Walk the sorted leg list, flip on `fix_type == "MAHP"`, and put subsequent non-transition legs in a new `missed_approach_legs` list.
8. **Parse subsection `C` terminal waypoints** into a `dict[str, tuple[float, float]]` and expose as a top-level helper (item 5). Reuse the existing latin-1 file walk.

### Hard (multi-day)

9. **Full RF-arc support** (item 3): parse `arc_radius` + `center_fix`, resolve center_fix lat/lon via the terminal-waypoint map, and surface in `ProcedureLeg`. Touches data model, the leg parser, and any downstream rendering/routing.
10. **Continuation-record awareness** (item 14): dispatch on `cont_rec_no` / `application` for at least the simulation continuation (FAS data block) on approaches — required for PBN/LPV minima from CIFP.
11. **Parse `SUSAD` navaids** into a coordinate table (item 5b). Mostly mechanical, but needs new public dataclass.

## Recommended fix-pack for "biggest user-visible win first"

Items **1 + 10 + 2 + 3**. The four parsing bugs that already corrupt output today. Everything else is additive.

After items 1 + 10 land, the existing zoa-tutor consumer can safely ingest CIFP-derived text descriptions of SIDs/STARs/approaches without showing wrong altitudes or misclassified fixes.

## Test-driven workflow when picking this up

For each item:

1. Find a real CIFP record (or use the existing test fixture `tests/Yaat.Sim.Tests/bin/Debug/net10.0/TestData/FAACIFP18.gz` from YAAT as a known-good corpus).
2. Look up the corresponding chart on the FAA's online charts portal to learn the expected value.
3. Write a failing pytest in `zoa-reference-cli/tests/` that loads the record and asserts the expected value.
4. Fix the parser.
5. Confirm the test passes and that no other tests regress.

## Out of scope for this doc

- Whether `cifparse` itself should be vendored or imported as a library
- Whether `zoa-reference-cli`'s `cifp.py` should be split into multiple files
- Performance work (it's currently `lru_cache`-decorated and adequate for CLI use)

## Provenance

- Investigation tool: Claude Code (Opus 4.7) running a `code-reviewer` agent invoked from `zoa-tutor`
- Date: 2026-05-21
- Both repos at the commit shown in the user's local git on that date

## Resolution (2026-05-21)

All 9 actionable items implemented one commit per item. Commits on `main`:

- `b90419b` — item 1: altitude columns + remove ×10 compensator
- `91d87a2` — item 10: fix-role column off-by-one in `parse_procedure_leg`
- `3969dc8` — item 2: fly-over flag on `ProcedureLeg`
- `5b43331` — item 4: outbound course, leg distance, rec_vhf, theta, rho, vertical angle
- `60f4de7` — item 13: AIRAC cycle math uses UTC date
- `1fba42d` — item 6: subsection-aware route_type detection (D adds T/V; F matches `parse_approach_record`)
- `7a82619` — item 7: `missed_approach_legs` split off `common_legs` at the MAP fix
- `cd7283a` — items 8 + 9: hold and procedure-turn detection (`is_hold` / `is_procedure_turn` / `has_hold` / `has_procedure_turn`)
- `166efc7` — item 5a: `get_terminal_waypoints(airport)` coord lookup
- `184cb6f` — item 3: RF-arc geometry (radius + center fix + resolved lat/lon)
- `75d6368` — item 5b: `get_navaids()` for VHF + NDB with frequency normalization
- `dc48627` — item 14: `cont_rec_no` filtering + `is_sbas_authorized` flag

Items 11, 12, 13 (NOT-A-DRIFT), 15, 16 (Python is ahead) were left alone. Full FAS data block parsing (LPV/LNAV/VNAV minima decoding) is still deferred — only the SBAS-authorization boolean is exposed.

Test infrastructure: `tests/conftest.py` provides `make_cifp_line()` (132-col ARINC builder). 59 pytest cases cover every column offset and code path. The real FAACIFP18 cache is used only for integration-style sanity checks (SFO/OAK/RNO procedures), not the unit tests.
