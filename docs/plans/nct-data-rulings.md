# NCT data review: rulings

Rulings on the cells the agent review of the draft in [nct-route-lookup.md](./nct-route-lookup.md) couldn't settle from the page. The review compared all 967 draft rows, the P-ACP lines and the general tables with the page images. It found no printed row missing, and no misread in a row without a doubt. Pages are PDF pages, in SOP v1.13 and LOA CHG08.

A later document version gets the same review, and these rulings are its starting point.

## Decided by question

- **Reno runways: Runway 17 is RNOS, Runway 35 is RNON.** SOP p136's rows print a runway with no flow, and p135 prints the same handoffs at the same altitudes under `Silver (RNOS)` and `Silver (RNON)`. So `sop-p136-t0-r0` takes RNOS, and `sop-p136-t1-r0` and `r1` take RNON. `sop-p57-t0-r1` keeps its `SQL Departures Only`: that destination cell is merged across both rows on the page.
- **Two altitudes in one cell: pair by line where aligned.** Where a cell's two lines sit beside two destinations, each destination takes its own line, in the order printed. That covers SOP p20 and p25 (MRY Runway 10 at 5,000, Monterey CX at 7,000) and p27 (Monterey CX at 5,000, Monterey Runway 10 at 7,000). p27's opposite order goes on the errata list.

  Every other such cell answers with both altitudes, including p46, where both lines sit beside Landing MRY and none beside Monterey CX, and the slash cells such as `5,000/ 7,000`. They are written uniformly as `5,000 / 7,000`, so an unprinted separator or a missing comma (`7000`, p84) doesn't reach the answer.
- **SFO10 and SFO19: settable subsets of SFOE, replacing row by row.** They are SFOE, just more specific, and `zoa flow` can set either. They replace only row by row, never a whole table: where rows define an SFO10 and an SFO19 variation, or an SFO10 and an SFOE variation, an active SFO10 prefers the SFO10 row; the same holds for SFO19.

  The Grove SFO10 tables (p98) hold a few rows, and Grove's other SFOE rows keep answering. The Grove SFO10 tables and the Boulder SFO10 P-ACP (p53) keep `SFO10` as their flow. No table or row names SFO19 in this SOP version.
- **Flow tags on p114 and p119: SJCE takes over.** Of the two `San Jose CX or SQL` rows, `OSI RV 110° (SFOW)` has flow SFOW and `OSI RV 140° (SJCE)` has flow SJCE, so under SFOW alone the 110° row answers, and under SFOW with SJCE the 140° row replaces it, by the next ruling.
- **Flow subsets: OAKE and SJCE are subsets of SFOW.** The `flow_parents` block records this beside SFO10 and SFO19. If a sector has a table for an active OAKE or SJCE flow, that table replaces the sector's SFOW table, per direction.

  Otherwise, a row tagged with that flow replaces the SFOW row for the same origin, destination and class, even when the two rows name different receiving sectors, as with Grove to Toga at 2,500 (SFOW) and Grove to Licke at 2,000 (SJCE) on p91. SFO10 and SFO19 never replace a whole table, as the previous ruling says.
- **Every table is an override, not exhaustive.** For every flow, a table lists only what needs overriding: "they only override what needs to be overridden where 'en route, any altitude' doesn't work." A gap means no specific instructions, so the aircraft is handed off en route at any altitude, and nothing falls back to another flow's table.

## Accepted rulings

The owner accepted these as proposed. Page discrepancies also go on the errata list.

| # | Cell | Page | Proposed |
|---|---|---|---|
| 1 | `SJC (SJCW)`, `SNS KLIDE`, J | LOA p16 | `flows` becomes SFOW. The owner ruled that these plans are really SFOW, and Table 1-1 prints the same route as `SJC (SFOW)`. |
| 2 | `flows` block | SOP p7, LOA p11 | Holds only the eight settable flows, with OAKE and SJCE defined as LOA p11 defines them. `SFOE / SJCW` and `SFOE / OAKW` and their footnotes are left out. |
| 3 | Area of Paradise and Elkhorn; Nugget and Silver | SOP p7, p124 | `Area E CA` and `Area E NV`, as p7 prints, since the allowed combinations on p16 depend on the split. |
| 4 | Departure Combined (Sutro) symbol | SOP p7, p16, p103 | Stays `4U`. p7's Combined row prints `4D`, which p143 gives to Diablo: an erratum. |
| 5 | Attachment 1 real-world sectors | SOP p143, p144 | Left out, since they are staffed only for approved events and no row uses them. The exception is Turlock (`1Q`, 126.475, combines to Morgan), which LOA Table 1-3 hands off to, so that row can name its sector. |
| 6 | Cedar P-ACP headed `Cedar SFOW` | SOP p55 | Filed under SFOE. It sits under `4-13 Cedar - SFOE` below the SFOE tables, so the heading looks like a misprint: an erratum. |
| 7 | P-ACP lines naming a flow in their text: Sunol SFOW `d` (`OAKE -`), Grove OAKE `f` (`During SJCE`) | SOP p87, p97 | Stay under their section's flow, with the text as printed. The reader sees the condition. |
| 8 | Blank sector on `All others`, `11,000 or lower filed` | SOP p105 | `to` becomes Sunol, as the OAKE table on p111 prints the same row: an erratum. |
| 9 | Blank class on `SUUTR`, `Descend Via` | SOP p131 | `J`, as the SMFN table on p134 prints the same row: an erratum. |
| 10 | Fully empty rows: Sunol (SFOW), Woodside | SOP p22, p33 | Dropped. On p33 that leaves `PAO Departures` as the only Woodside row in that merged block. |
| 11 | Altitude and info cells whose reach is unclear: `RNAV STAR or Abeam OSI RV 110° (SFOW) Abeam OSI RV 140° (SJCE)` (p46, p51), `↓ 100 or 120 or level at lower filed altitude` (LOA p14, p15), `Jets: X 6 NW SFO @110 & 250K` (LOA p17), `X STINS @ 050/090 (SFOW) @ 040/070 (SFOE)` (LOA p18) | as listed | Kept whole and printed as written. An answer shows the full cell, so nothing needs splitting and no reading is imposed. |
| 12 | Routes whose `or` or list scope is unclear: `BSR or SHOEY V27 HADLY SAU` (LOA p12, p16), `BSR LIBBO TOKIO or SERFR` (LOA p13, p16), `CEDES HARGO BLEAR FRAME` (SOP p54), `SPTNS, SJC or SOLN DP's` (SOP p33) | as listed | Kept whole as one item and printed as written. A lookup matches any token inside the item, so a query on `SHOEY` or `SERFR` still finds the row. |
| 13 | `CCR * WINE COUNTRY` | LOA p15 | Two destinations, `CCR` and `WINE COUNTRY`, reading `*` as the `&` the row above prints: an erratum. |
| 14 | `OAK (SFOW) HWD` | LOA p22 | Both airports stay SFOW as drafted, since the row below is `OAK (SFOE)` alone. Under SFOE, HWD gets no answer from this row rather than a possibly wrong one: an erratum. |

## Applied without a ruling

- Misreads where the page is plain: the review's `fix` findings, such as comma lists left whole. They change a list's shape to match the page, never a printed value. One word is carried across a split: `Direct ALCOA, BEBOP, or CINNY` (LOA p17) gives `Direct` on each fix, since a bare `BEBOP` would lose the "must be direct" meaning of SOP §1-13.
- A `to` naming several sectors by class or flow, such as `Laguna (J) Seca (T/P)` or `Sutro (SFOW) Boulder (SFOE)`, becomes one row per sector with that class or flow, so a lookup can match a single sector.
