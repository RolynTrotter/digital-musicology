---
name: schenker-graph
description: "Engrave a Schenkerian graph from MusicXML: the original score with the fundamental line beamed across systems, prolongation slurs, focal-pitch and module labels; SVG, PNG, PDF, MEI."
---

# Schenker graph

Use this skill when someone wants to see a reduction on the music: a graph with the notes of the
fundamental line beamed together, slurs for prolongations, and labels, drawn on the original score.
The analysis comes from the **melodic-reduction** skill, or from a hand-written spec when Alex has
his own reading.

## Where the code is

| What | Where |
| --- | --- |
| Package | GitHub `RolynTrotter/digital-musicology`, branch `melodic-reduction`, folder `schenker-graph/` |
| Analysis package it calls | same branch, `melodic-reduction/` |
| Tests | `schenker-graph/tests/` |
| Graphs of all 16 Dominus clausulae | `~/Documents/DominusClausulae/analysis/reduction/graphs/` |

**Getting the package:** clone the branch and `pip install -e melodic-reduction -e schenker-graph`
(verovio, lxml, cairosvg, pypdf, music21). Don't rewrite it from memory.

## Workflow

1. **Analyse or load.** `schenker-graph SCORE` analyses the duplum (part 0) and the tenor on the
   fly with the tree method; `--analysis a.json` uses a saved melodic-reduction analysis, which is
   better when the analysis has been checked or tuned.
2. **Engrave.**
   ```bash
   schenker-graph Dominus3.xml --analysis Dominus3.json --out graphs/Dominus3
   schenker-graph Dominus3.xml --stacked fundamental pair ordo --out graphs/Dominus3_stacked
   ```
   ```python
   import schenker_graph as sg
   files, graph, analysis = sg.schenker_graph('Dominus3.xml', analysis='Dominus3.json', out_prefix='graphs/D3')
   ```
   Writes `_pN.svg`, `_pN.png`, `.pdf`, and the annotated `.mei`.
3. **Check, then look.** `schenker_graph.graph.unaccounted(graph, n)` lists notes that no slur,
   beam or stem accounts for (duplum: `graph`; tenor: `graph.others[0]`); it should be empty.
   `schenker_graph.collide.collisions(svg)` lists slurs running through labels, beams, stems (away
   from the note the slur ends on) or ties; engraving already moves colliding labels to the other
   side or further out, so anything left needs a look. `collide.crowded_systems(svg)` lists
   systems whose notes are too close together (engraving already splits them). Then Read every PNG:
   the beam continuous from the first fundamental note to the last, across pages; stems on the
   right noteheads. If a pitch looks wrong (a C-flat, an A-flat), check the source edition page
   before analysing further.
4. **Deliver** the PDF (and PNGs if they want to paste them), and list the fundamental line,
   home notes and pedals in the reply with measure numbers. When Alex may be annotating earlier
   PDFs, write new versions to a new folder (e.g. `v2/`) rather than over his copies.

## What is drawn (defaults, for a tree analysis)

| Element | Meaning | Where |
| --- | --- | --- |
| Red noteheads, stems and beam | fundamental line: heads of each pair of pairs (duplum) | beam above the duplum |
| Red noteheads, stems and beam | the tenor's line at the same level | beam below the tenor |
| Blue noteheads | heads of ordines and pairs (middleground) | both voices |
| Grey-blue slurs | the reduction inside each ordo (foreground): each note slurred to the notes it lies between or leads to | between the staves: below the duplum, above the tenor |
| Blue slurs | how ordo heads connect inside pairs | outside: above the duplum, below the tenor |
| Blue notes with long sub-stems (5.5 spaces; up on the duplum, down on the tenor) | the top level of connections: pair heads within each pair of pairs, drawn as stems instead of slurs (Schenker's middleground stems) | both voices |
| Blue notes with long up-stems | the piece's pedal pitch (e.g. Dom 3's upper pedal F) at each ordo head where it recurs; slurs attach at the stem tip | duplum |
| Bold letters (a, a', b …, tag) | pair (module) labels | above |
| Italic text | home note, pedal pitch and stepwise line of each pair of pairs (two lines) | below the duplum |

**Layout.** One system per pair of pairs (a long pair of pairs fills systems pair by pair), so no
ordo is split across systems and foreground slurs stay whole. Each break moves up to two bars to
cut the fewest ordines of either voice (Dom 10's tenor runs two bars out of phase, so one voice
is always cut there). The source's own system and page breaks are dropped.

**Note spacing.** A system may hold at most `max_system_load` (default 60: distinct onsets of both
voices plus one per bar). Fuller systems are split at a pair boundary near the middle, else at an
ordo boundary, cutting the fewest ordines. After rendering, any system where two neighbouring
notes or rests on a staff are closer than `min_gap` (1.65 staff spaces), or where an accidental
runs into the note before it (its head, flag or dot), is split again and re-rendered. A last
system of six bars or fewer (a tag) joins the one before it if it fits.

**Slur stacking.** At most `max_slur_stack` (default 2) slurs are printed stacked on one side of a
staff, and they are the background-most ones: a slur enclosed by two or more others on its side
gets `hidden: true`. Hidden slurs stay in the analysis and the graph spec, and every note is
still under a printed slur (the outermost slur of each nest is kept). Alex asked for this (no. 71,
m. 74 had five or six levels; then "only the background-most two layers").
`thin_slurs(g, max_stack, keep='inner+outer')` keeps the outermost and the innermost layers
instead; `max_slur_stack=None` prints them all.

**Sub-stems.** The top level of connections (the fundamental line's level, normally the pair
heads inside each pair of pairs) is drawn as sub-stems on the notes it joins, not as slurs
(`substems=True`, `substem_length=5.5`; `--no-substems` for slurs). Pedal stems are 4.5 spaces.
Levels at or below the ordo are never sub-stemmed.

Options: `--no-substems`, `--max-slur-stack N` (default 2; 0 = print all), `--max-system-load N`
(0 = off), `--min-gap S`, `--upper-slurs-only` (drop the foreground slurs), `--no-slurs`, `--no-reference`
(leave the tenor unmarked), `--ligatures` (analyse with ligatures first), `--stacked fundamental
pair ordo` (reduction staves above the score, from music21's `ScoreReduction`, top staff beamed),
`--title`. In Python, `graph_from_tree(a, max_slur_level=…, pedal_stems=…, system_breaks=…,
max_slur_stack=…, max_system_load=…, substems=…, substem_length=…)` and
`engrave(…, fix_spacing=…, min_gap=…)`.

For a flat analysis (`method='mop'`), the older overlays apply: fundamental line, middleground by
span, parent-interval slurs, dashed focal-pitch slurs, module letters with transposition;
options `--middleground auto|span:T|none`, `--modules N`, `--module-brackets`, `--no-focal`.

## Hand analyses

A spec is JSON; notes are indices into the voice (ties merged, rests skipped) or addresses:
measure + pitch in music21 spelling + occurrence (`3f4-1`, `12b-4-2` for the second B♭4 of m. 12).

```json
{"replace": true,
 "fundamental": ["1d4-1", "3f4-1", "71d4-1", "75c4-1", "91e4-1"],
 "slurs": [{"from": "3f4-1", "to": "67f4-1", "style": "dashed", "place": "below"}],
 "labels": [{"at": "3f4-1", "text": "F prolonged", "place": "below"}]}
```

Without `replace`, the spec's lists replace the automatic ones and everything else stays.
Addresses for every note are in the analysis JSON (`notes[].address`). A hand spec is also a gold
reduction that melodic-reduction could later be fitted to; keep them.

## How it works (for debugging)

- MusicXML → verovio → MEI. Colours, stem directions and lengths, slurs (`lform="dashed"` for
  dashed), `<dir>` labels (a newline in the text becomes `<lb/>`), extender brackets and
  `<sb/>`/`<pb/>` breaks are added to the MEI, so verovio places them.
- MEI notes are matched to the analysed voice in order, skipping tie continuations, and checked
  letter and octave note by note. If an encoding has dangling ties (Dom 1's tenor, mm. 59–62),
  the order breaks and notes are matched by onset through verovio's timemap instead.
- The beam is drawn on the SVG afterwards (MEI has nothing for a beam across non-adjacent notes
  that keep their own rhythm): stems from the fundamental noteheads, one beam per system placed
  two staff spaces above the highest notehead, slur or label over the staff, carried to the system
  edge when the line continues, including across pages.
- The tenor's beam is the same drawing turned over (stems down from the left of the notehead,
  beam below the staff and below any slurs there). Other staves' overlays live in
  `Graph.others`.
- If a beam collides with the system above, raise `spacingSystem` in `options`
  (default 22; e.g. `engrave(..., options={'spacingSystem': 28})`).