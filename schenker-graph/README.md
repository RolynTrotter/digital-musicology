# schenker-graph

Engrave a Schenkerian graph: the original score with the fundamental line beamed and stemmed,
middleground notes coloured, prolongation slurs, dashed slurs for focal-pitch prolongations, and
module labels. Optionally, reduction staves above the score (music21's `ScoreReduction`).

```bash
pip install -e .                 # verovio, lxml, cairosvg, pypdf; melodic-reduction for automatic analysis

schenker-graph Dominus3.xml --out graphs/Dominus3                       # analyse and engrave
schenker-graph Dominus3.xml --analysis Dominus3.json --out graphs/D3     # use a saved analysis
schenker-graph Dominus3.xml --stacked fundamental pair ordo --out graphs/D3_stacked
schenker-graph Dominus3.xml --graph my_reading.json --out graphs/D3_mine  # hand analysis
```

Writes `<out>_pN.svg`, `<out>_pN.png`, `<out>.pdf` and the annotated `<out>.mei` (open it in any
MEI viewer or edit it further).

## How it draws

* **Verovio** engraves the score from MusicXML, and everything MEI can express is added as MEI
  before engraving, so verovio places it: coloured noteheads, up-stems on the fundamental notes,
  slurs (solid or dashed, above or below, broken across systems), text labels, and bracket lines.
* **The Schenkerian beam** joins non-adjacent notes across barlines and systems while the notes
  keep their own rhythm. MEI has no element for that, so it is drawn on the SVG afterwards from the
  notehead positions verovio reports: a stem from each fundamental note and one beam per system,
  running on to the edge when the line continues on the next system or page, and clearing slurs
  and labels above the staff.
* **Stacked mode** asks music21's `analysis.reduction.ScoreReduction` for one staff per reduction
  level above the score (open noteheads for the fundamental line) and beams the top staff.

## Hand analyses

A graph spec is JSON. Notes are indices into the analysed voice (ties merged, rests skipped) or
addresses: measure, pitch in music21 spelling, occurrence in the measure (`3f4-1`, `12b-4-2`).

```json
{"replace": true,
 "fundamental": ["1d4-1", "3f4-1", "71d4-1", "75c4-1", "91e4-1"],
 "middleground": ["9d4-1"],
 "slurs": [{"from": "3f4-1", "to": "67f4-1", "style": "dashed", "place": "below"}],
 "labels": [{"at": "3f4-1", "text": "F prolonged", "place": "below"}],
 "brackets": [{"from": "3f4-1", "to": "9d4-1", "text": "A", "place": "above"}]}
```

Without `"replace": true` the spec is merged into the automatic overlays (lists replace lists).
