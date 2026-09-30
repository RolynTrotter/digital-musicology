---
name: schenker-graph
description: "Engrave a Schenkerian graph from MusicXML: the original score with the fundamental line stemmed and beamed across barlines and systems, middleground notes coloured, prolongation slurs, dashed focal-pitch slurs and module labels, optionally with reduction staves above. Takes a melodic-reduction analysis or a hand-written spec. Outputs SVG, PNG, PDF and MEI."
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
3. **Look at every page** (Read the PNGs) before handing anything over. Check that the beam is
   continuous from the first fundamental note to the last (running to the system edge when it
   continues), that stems land on the right noteheads, and that labels don't sit on each other.
4. **Deliver** the PDF (and PNGs if they want to paste them), and list the fundamental line and
   focal pitches in the reply with measure numbers.

## What is drawn (defaults, for a tree analysis)

| Element | Meaning | Where |
| --- | --- | --- |
| Red noteheads, stems and beam | fundamental line: heads of each pair of pairs (duplum) | beam above the duplum |
| Red noteheads, stems and beam | the tenor's line at the same level | beam below the tenor |
| Blue noteheads | heads of ordines and pairs (middleground) | both voices |
| Grey-blue slurs | the reduction inside each ordo (foreground): each note slurred to the notes it lies between or leads to | below the duplum |
| Blue slurs | how ordo heads connect inside pairs and pairs of pairs | above the duplum, below the tenor |
| Bold letters (a, a', b …) | pair (module) labels by duplum similarity | above |
| Italic text | home note and pedal pitch of each pair of pairs | below the duplum |

Options: `--upper-slurs-only` (drop the foreground slurs), `--no-slurs`, `--no-reference` (leave
the tenor unmarked), `--ligatures` (analyse with ligatures first), `--stacked fundamental pair
ordo` (reduction staves above the score, from music21's `ScoreReduction`, top staff beamed),
`--title`. In Python, `graph_from_tree(a, max_slur_level=…)` sets the highest level that gets
slurs (default: the fundamental line's level; above it the beam does the job).

For a flat analysis (`method='mop'`), the older overlays apply: fundamental line, middleground by
span, parent-interval slurs, dashed focal-pitch slurs; options `--middleground auto|span:T|none`,
`--modules N`, `--module-brackets`, `--no-focal`.

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

- MusicXML → verovio → MEI. Colours, stem directions, slurs (`lform="dashed"` for dashed),
  `<dir>` labels and extender brackets are added to the MEI, so verovio places them and breaks
  slurs across systems.
- MEI notes are matched to the analysed voice in order, skipping tie continuations; letter and
  octave are checked note by note, and a mismatch stops with its position.
- The beam is drawn on the SVG afterwards (MEI has nothing for a beam across non-adjacent notes
  that keep their own rhythm): stems from the fundamental noteheads, one beam per system placed
  two staff spaces above the highest notehead, slur or label over the staff, carried to the system
  edge when the line continues.
- The tenor's beam is the same drawing turned over (stems down from the left of the notehead,
  beam below the staff and below any slurs there). Other staves' overlays live in
  `Graph.others`.
- If a beam collides with the system above, raise `spacingSystem` in `options`
  (default 22; e.g. `engrave(..., options={'spacingSystem': 28})`).
