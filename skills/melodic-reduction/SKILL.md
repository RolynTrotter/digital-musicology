---
name: melodic-reduction
description: "Tonality-free melodic reduction (modified Schenkerian analysis) of a MusicXML score, built as a tree from the foreground up: each ordo reduced on its own, then pairs of ordines, pairs of pairs and sections, with home notes, pedal/focal pitches, module labels and the tenor reduced alongside. Use for reducing a melody, finding what a passage prolongs, or comparing the skeletons of clausulae or other pre-tonal music."
---

# Melodic reduction: a tree from the foreground up

Use this skill when someone wants a voice reduced to its structural notes without tonal theory:
no key, scale degrees or harmonic function, and no assumption of a 3-, 5- or 8-line. It was built
for Alex's Dominus clausulae (duplum over tenor) and works for any melody, with or without a
second voice. To draw the result, use the **schenker-graph** skill afterwards.

## Where the code is

| What | Where |
| --- | --- |
| Package | GitHub `RolynTrotter/digital-musicology`, branch `melodic-reduction`, folder `melodic-reduction/` |
| Rules and sources | `melodic-reduction/rules.md` (read it before explaining a result) |
| Weights | `src/melodic_reduction/data/weights_default.json` (rules, default); `weights_gttm.json` (flat-method salience fitted to the GTTM database) |
| Tests | `melodic-reduction/tests/` |
| Dominus encodings (authoritative) | `~/Documents/DominusClausulae/data/musicxml/DominusN.xml` on Alex's computer (from Baltzer's edition) |
| Earlier results | `~/Documents/DominusClausulae/analysis/reduction/` |

**Getting the package:** clone the branch and `pip install -e melodic-reduction` (numpy, music21
≥ 9; tested with 9.9.2 on Python 3.11 and the music21 repository head, 11.0.0b9, on 3.12). If the
repository can't be reached, ask for the folder. Don't rewrite the package from memory.

## Workflow

1. **Use Alex's encodings**, not CANDR realisations, unless the question is about the manuscript.
   CANDR follows F where Baltzer's edition differs (Dom 3: E–C–E–F–D for E–D–E–F–D in mm. 13 and
   29, F with a plica for E–D in m. 40, tenor A for B♭ in m. 54), and the ligature-rhythm reader
   gets some rhythms wrong (Dom 3 tenor mm. 81–82: L. + rest for a duplex long).
2. **Analyse.** Part 0 = duplum, part 1 = tenor; the tenor is reduced too.
   ```bash
   melodic-reduction analyze Dominus3.xml --json Dominus3.json          # tree (default)
   melodic-reduction analyze F149r.musicxml --ligatures --json F.json   # ligatures as a level below the ordo
   melodic-reduction corpus ~/Documents/DominusClausulae/data/musicxml --out analysis/reduction
   ```
   ```python
   import melodic_reduction as mr
   a = mr.analyze('Dominus3.xml')          # method='tree'; method='mop' is the older flat reducer
   print(mr.summary_tree(a))
   ```
   Under a second per clausula.
3. **Read the result.**
   - `groups`: the formal tree. Levels: `ordo` (between rests; an ordo that runs through a rest in
     the other voice is cut on the voice's ordo period), `pair` (of ordines), `pair of pairs`,
     `section`, … `piece`. Each group has a `head`; pairs have a module `label`.
   - `sections` (one per pair of pairs): `home` note (the group's head, usually its last note),
     the line of ordo heads, and the `pedal`: the pitch that recurs most among the ordo heads
     other than the home note, with `position` upper/lower. In Dom 3 this gives home D with an
     upper pedal F (mm. 1–31), and F–E–(F)–D ordo heads in mm. 57–71.
   - `fundamental`: heads of each pair of pairs plus the first note. `fundamental='level:2'`
     (pair heads) gives a more detailed line.
   - `levels`: nested reductions `surface`, `ordo`, `pair`, `pair of pairs` … as note lists.
   - `dependencies`: every note's place in its group: `level`, `parent` (the members of the same
     group it sits between, or leads to / follows), `relation` (PASS, NEI, REP, FILL, INC_L/R,
     NEI_LEAP, EDGE_*). Level-1 dependencies are the reduction inside each ordo.
   - `modules`: pair labels. Same letter = same duplum (≥ 0.9 similarity); primes = variants
     (≥ 0.6 like the letter's first pair, or ≥ 0.7 like any member). Each keeps `like` (the most
     similar earlier pair and the similarity). The labels compare the duplum only, so pairs with the
     same duplum over a different tenor share a letter (Alex's "ab" pairs in Dom 3 come out as a′).
   - `reference_voice`: the tenor's notes, groups (following the duplum's pairs and above),
     dependencies and line.
   - `focal_pitches`, `dominant_focal_pitches`: same-pitch prolongations through the tree.
4. **Reduction staves** (music21 `ScoreReduction`):
   `melodic-reduction reduce Dominus3.xml --json Dominus3.json --out D3_red.musicxml --levels fundamental pair ordo`.
5. **Report** per pair of pairs: home note, pedal, the ordo-head line; then the fundamental line and
   the tenor line, with measure numbers. Separate the home note (where groups arrive) from the
   focal or pedal pitch (what recurs): Alex hears F in Dom 3 as a structural upper pedal over a D
   home, not as the structural pitch.

## How the reducer decides

- **Grouping first.** Ordines are grouped in twos (pairs, then pairs of pairs …) by a dynamic
  programme that prefers two members, allows three (Dom 3 mm. 33–56 has an extra pair) and a lone
  tag at the end, and rewards groups that end on a perfect consonance with the tenor, members of
  equal length, and pairs that recur in the same phase elsewhere (duplum pitch and rhythm plus the
  tenor's rhythm).
- **Then a tree inside each group**, from the ordo up: the group's members (notes, or the heads of
  its subgroups) are triangulated with the prolongation rules (repetition, neighbour, passing,
  leap-filling licensed; incomplete neighbours weaker; other leaps penalised; an elaborating note
  less salient than its frame; steps preferred). The root is the group's head. Each group's last
  member gets a cadential weight, so ordines, pairs and pairs of pairs are heard as arriving on
  their last notes. The piece's first and last notes get extra weight only at the top.
- **Salience** of a note: beat strength, duration, consonance with the other voice (Garlandia's
  perfect > medial > imperfect, three grades of dissonance; intervals below the tenor count the
  same as above), sounding with a tenor onset, ordo boundaries, registral extremes.
- **The tenor** is reduced the same way against the duplum, with its ordines placed in the
  duplum's pairs and higher groups. It can stress notes the chant would not.
- **Ligatures** are ignored unless `ligatures=True`; then each ligature is reduced first. They
  cannot replace the reduction slurs; on Dom 3 (CANDR) they change 27 foreground attachments and
  nothing above the ordo.

## Calibration and checks

- The grouping weights (notably `grouping.cadence_high` = 1.5) were set so Dom 3 comes out as
  Alex hears it (pairs of pairs 1–16, 17–32, 33–56, 57–72, 73–88, tag). They are not yet checked
  on the other clausulae; several (Dom 4, 5, 9a, 12, 14) get pairs of pairs of odd sizes. Look at the
  grouping before quoting results for a new piece and say when it looks wrong.
- Other checks: run with and without `ligatures`; compare edition and CANDR readings; look at the
  graph before quoting a line.
- The flat reducer (`method='mop'`) and its GTTM benchmark are still there; rules.md §5–6.

## Objections to have answers for

Schulenberg ("Modes, Prolongations, and Analysis") and Leach ("Counterpoint and Analysis in
Fourteenth-Century Song") object to Schenkerian readings of early music. This reducer uses no
harmonic prolongation or tonal hierarchy; form (ordines, pairs, cadences) and explicit, citable
voice-leading rules decide, and any rule can be changed and the analysis re-run.
