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

1. **Analyse or load.** `schenker-graph SCORE` analyses the duplum (part 0) on the fly;
   `--analysis a.json` uses a saved melodic-reduction analysis, which is better when the analysis
   has been checked or tuned.
2. **Engrave.**
   ```bash
   schenker-graph Dominus3.xml --analysis Dominus3.json --out graphs/Dominus3
   schenker-graph Dominus3.xml --stacked fundamental span:4 --out graphs/Dominus3_stacked
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

## What is drawn (defaults)

| Element | Meaning | Where |
| --- | --- | --- |
| Red noteheads, stems and beam | fundamental line | beam above the staff |
| Blue noteheads | middleground (span ≥ ¼ of the fundamental line's threshold) | |
| Blue slurs | a middleground note's parent interval (passing, neighbour, leap-filling) | below |
| Grey dashed slurs | successive returns of a dominant focal pitch not already joined | below |
| Italic label | focal pitch and number of returns, at its first note | below |
| Bold letters (A, B (−1)…) | module occurrences, with transposition in steps | above |

Options: `--middleground auto|span:T|none`, `--modules N` (0 = none), `--module-brackets`
(line over the whole occurrence), `--no-focal`, `--no-slurs`, `--stacked LEVEL …` (reduction
staves from music21's `ScoreReduction`; the top staff is beamed), `--title`.

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
- If a beam collides with the system above, raise `spacingSystem` in `options`
  (e.g. `engrave(..., options={'spacingSystem': 22})`).
