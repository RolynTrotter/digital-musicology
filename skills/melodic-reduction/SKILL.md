---
name: melodic-reduction
description: "Tonality-free melodic reduction (modified Schenkerian foreground/middleground analysis) of one voice of a MusicXML score: prolongational hierarchy, reduction levels, fundamental line, focal pitches and repeated modules. Use for reducing a melody, finding what pitch a passage prolongs, or comparing the skeletons of clausulae or other pre-tonal music."
---

# Melodic reduction: foreground reduction and focal pitches

Use this skill when someone wants a voice reduced to its structural notes without any tonal
theory: no key, no scale degrees, no harmonic function, no assumption of a 3-, 5- or 8-line. It was
built for Alex's Dominus clausulae (duplum reduced against the tenor), but works for any melody,
with or without a second voice.

To draw the result as a graph, use the **schenker-graph** skill afterwards.

## Where the code is

| What | Where |
| --- | --- |
| Package | GitHub `RolynTrotter/digital-musicology`, branch `melodic-reduction`, folder `melodic-reduction/` |
| Rules and sources | `melodic-reduction/rules.md` (read it before explaining a result) |
| Weights | `src/melodic_reduction/data/weights_default.json` (rules; default) and `weights_gttm.json` (salience fitted to the GTTM database) |
| Tests | `melodic-reduction/tests/` |
| Dominus encodings (ground truth) | `~/Documents/DominusClausulae/data/musicxml/DominusN.xml` on Alex's computer |

**Getting the package:** clone the branch and `pip install -e melodic-reduction` (needs numpy and
music21 ≥ 9; tested with 9.9.2 on Python 3.11 and with the music21 repository head, 11.0.0b9, on 3.12). If the repository can't be
reached, ask for the folder. Don't rewrite the package from memory.

## Workflow

1. **Pick the voice and its reference.** In the Dominus files part 0 is the duplum and part 1 the
   tenor; `reference='auto'` uses the other part of a two-part score. For a monophonic melody pass
   `reference=None`. Prefer Alex's edition encodings to CANDR realisations (from the
   ligature-rhythm skill), which are only ~80% right in rhythm and change the salience of notes.
2. **Analyse.**
   ```bash
   melodic-reduction analyze Dominus3.xml --json Dominus3.json
   melodic-reduction corpus ~/Documents/DominusClausulae/data/musicxml --out analysis/reduction
   ```
   ```python
   import melodic_reduction as mr
   a = mr.analyze('Dominus3.xml', part=0)
   print(mr.summary(a))
   ```
   About 1 s for a 100-note duplum, 3 s for 230 notes.
3. **Read the result** (keys of the JSON):
   - `fundamental`: the background line. Default keeps about one note per eight bars; change with
     `fundamental='span:T' | 'height:H' | 'count:K' | 'notes:0,5,9'`.
   - `levels_by_span_units`: nested reductions. `'1'` keeps notes whose parent interval spans at
     least a bar (strips surface diminution), `'4'` a middleground, and so on.
   - `dominant_focal_pitches`, `focal_pitches`: pitches prolonged over a stretch, with measures,
     number of returns, returns per 8 bars and time spent on or a step from the pitch. `focal:
     False` marks sparse long prolongations (a pitch that only frames a section).
   - `modules`: repeated passages with transposition in steps (exact, and `varied` = same rhythm
     and contour, for a / a′ / a″ variants).
   - Per note: `relation` (REP, NEI, PASS, FILL, INC_L/INC_R, NEI_LEAP, OTHER, FRAME), `parent`,
     `height`, `span_units`, salience features.
4. **Write reduction staves** as MusicXML with music21's `ScoreReduction`:
   `melodic-reduction reduce Dominus3.xml --json Dominus3.json --out D3_red.musicxml --levels fundamental span:4`.
5. **Report**: the fundamental line, the dominant focal pitches with measures, the modules, and
   the relation counts. Give measure numbers so Alex can check them in the score. Say which weights
   were used.

## How the reducer decides

- **Salience** of each note: beat strength, duration, consonance class against the tenor
  (Garlandia's perfect > medial > imperfect, three grades of dissonance), coinciding with a tenor
  onset, first/last note of an ordo, first/last note of the piece, local registral extreme. Notes
  in repeated modules share salience (parallelism).
- **Hierarchy**: a triangulation of the melody (maximal outerplanar graph, Yust / Kirlin): each
  note elaborates one interval between two notes that outlast it. Scored by the kind of motion
  (repetition, neighbour, passing, leap-filling licensed; incomplete neighbours weaker; other leaps
  penalised), by subordination (an elaborating note should be less salient than its frame) and a
  preference for steps. Solved exactly by dynamic programming.
- **Focal pitches** are read off the hierarchy (same-pitch notes connected through it). The
  optional prior that rewards same-pitch prolongation (`same_pitch_edge`) is **0** by default, so
  focal pitches are found, not assumed.

## Weights and training

- The defaults are rules, not a trained model. Each weight is one rule; rules.md gives the source.
- `weights='gttm'` has the generic salience weights (metre, duration, grouping, contour,
  subordination) fitted by coordinate ascent to the GTTM database's human time-span reductions,
  held-out half for testing. Consonance and relation weights stay at their rule values. It is
  tonal repertoire, so treat it as a sensitivity check, not an improvement for clausulae.
- To fit on clausulae, the missing piece is gold reductions. If Alex makes some (as graph specs,
  see schenker-graph), fit on those rather than GTTM.
- Benchmark: `melodic-reduction gttm DIR` (folders downloaded from https://gttm.jp/gttm/database/).

## Checks before trusting a result

- Run with both weight sets and with `same_pitch_edge` 0.5. A focal pitch that survives all three
  is robust; say which ones move. (On the ten F Dominus clausulae the dominant focal pitches did not
  change with the prior.)
- Look at the graph (schenker-graph) before quoting a fundamental line.
- The frame is the first and last note (`frame='notes'`). Use `frame='virtual'` if the voice
  starts with an upbeat or ends off its goal.
- Rhythm matters: salience depends on metre and duration, so a wrong reading of the modal rhythm
  changes the reduction.

## Objections to have answers for

Schulenberg ("Modes, Prolongations, and Analysis") and Leach ("Counterpoint and Analysis in
Fourteenth-Century Song") object to Schenkerian readings of early music. This reducer uses no
harmonic prolongation or tonal hierarchy; every choice comes from an explicit, citable rule and
can be re-run with the rule changed. Say so when presenting results.
