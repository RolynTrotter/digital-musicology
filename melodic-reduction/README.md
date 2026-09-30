# melodic-reduction

Tonality-free melodic reduction built on [music21](https://github.com/cuthbertLab/music21): a
prolongational hierarchy for one voice, the foreground and middleground reductions it implies, a
fundamental line, focal pitches (pitches prolonged over a stretch of music) and repeated modules.

Nothing tonal is assumed: no key, scale degrees or harmonic function, and no 3-, 5- or 8-line.
Pitches are compared by letter-name step; a second voice (the tenor of a clausula) supplies
consonance at structural points.

```bash
pip install -e .          # numpy, music21 >= 9

melodic-reduction analyze Dominus3.xml --json Dominus3.json        # duplum over tenor
melodic-reduction reduce  Dominus3.xml --json Dominus3.json --out Dominus3_reduction.musicxml
melodic-reduction corpus  data/musicxml --out analysis/reduction    # every piece, plus summary.csv
```

```python
import melodic_reduction as mr
a = mr.analyze('Dominus3.xml', part=0)            # reference voice: the other part
print(mr.summary(a))
a['fundamental'], a['dominant_focal_pitches'], a['modules'], a['levels_by_span_units']
```

## How it works

1. **Salience** of each note from metre, duration, consonance with the other voice, ordo
   boundaries and contour; notes in repeated modules share salience across occurrences.
2. **Hierarchy**: the best triangulation of the melody (a maximal outerplanar graph) under a score
   that licenses repetition, neighbour, passing and leap-filling motion, makes elaborating notes
   less salient than their frame, and prefers steps. Solved exactly by dynamic programming.
3. **Readings**: reductions by height or by span (the length of a note's parent interval, in
   bars), a fundamental line, and focal pitches (same-pitch notes joined by the hierarchy).

The rules and where each comes from are in [rules.md](rules.md); the weights are in
`src/melodic_reduction/data/weights_default.json`.

## Output (`analyze --json`)

| Key | Contents |
| --- | --- |
| `notes[]` | pitch, onset, measure, `address` (e.g. `3f4-1`), salience and its features, `parent` interval, `relation`, `height`, `span_units` |
| `levels_by_span_units` | note indices kept at each span threshold (1, 2, 4 … bars) |
| `levels_by_height` | note indices kept at each height |
| `fundamental` | the rule used and the note indices |
| `focal_pitches` | every same-pitch prolongation with length, returns, time on/near the pitch, `focal` flag, nesting |
| `dominant_focal_pitches` | the top layer of focal spans, in order |
| `modules` | repeated passages (exact, and varied = same rhythm and contour), with transposition in steps |
| `pitch_profile` | time-weighted pitch shares, plain and height-weighted |

## Checking the rules

`melodic-reduction gttm DIR` scores the reducer against the 300 hand-made time-span reductions of
the GTTM database (download the folders from https://gttm.jp/gttm/database/). `fit` fits the
generic salience weights to it with a held-out half. See rules.md §5 for the numbers.

## Tests

`pip install -e .[test] && pytest`
