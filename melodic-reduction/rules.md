# Reduction rules

There are two reducers. The default (`method='tree'`, §7) groups the voice first (ordines,
pairs, pairs of pairs …) and reduces each group from the foreground up. The flat reducer
(`method='mop'`, §1–6) triangulates the whole voice at once. Both use the same note salience
(§1) and the same prolongation rules (§2).

The reducer is rule-based. Every weight in `data/weights_default.json` stands for one of the rules
below, taken from the published literature on melodic reduction and from Alex Bean's own clausula
rules (2020). Nothing tonal is used: no key, no scale degrees, no harmonic function, no
assumption that the line is a 3-, 5- or 8-line.

## 1. How structural is a note on its own? (salience)

| Weight | Rule | Source |
| --- | --- | --- |
| `metric` | Notes on stronger beats are more structural. | GTTM TSRPR 1 (Lerdahl & Jackendoff 1983); Bean 2020 "rhythmic position" |
| `duration` | Longer notes are more structural (agogic accent). | GTTM TSRPR 2 in its durational reading; Marsden 2010 |
| `cons_*` | Notes consonant with the other voice are more structural, graded perfect > medial > imperfect > imperfect / intermediate / perfect dissonance. | Johannes de Garlandia, *De mensurabili musica* ch. 9–10; GTTM TSRPR 2 (local harmony) replaced by two-voice consonance; Bean 2020 "tenor consonance at structural points" |
| `ref_onset` | A note that starts together with a note of the other voice is a structural point. | Bean 2020 |
| `group_start`, `group_end` | The first and, more strongly, the last note of a rest-delimited group (an ordo) are retained. | GTTM TSRPR 7 (cadential retention), TSRPR 8 (structural beginning) |
| `piece_edge` | The first and last notes frame the whole voice. | GTTM TSRPR 8–9; Schenker's line has fixed endpoints |
| `extreme` | A local registral high or low point gets a small accent. | GTTM TSRPR 3 (registral extremes); Thomassen 1982 |
| `parallel_alpha` | Passages that repeat (same rhythm and diatonic intervals, so transpositions count) are reduced the same way: corresponding notes get the same salience. | GTTM TSRPR 4 / MPR 1 (parallelism); Bean 2020 "modular repetition and transposition"; Mathias's A/B/A′/B′ modules |

## 2. What may a note do between two more structural notes? (relations)

The hierarchy is a triangulation of the melody (a maximal outerplanar graph; Yust 2006, Kirlin &
Jensen 2011): each note *k* is placed inside exactly one interval *i … j* of notes that outlast
it. The kind of motion *k* makes in that interval is scored:

| Weight | Elaboration | Licensed? |
| --- | --- | --- |
| `REP` | *k* repeats *i* or *j* | yes (repetition) |
| `NEI` | *i* = *j*, *k* a step away | yes (neighbour) |
| `PASS` | *i*–*k*–*j* stepwise in one direction | yes (passing) |
| `FILL` | *k* lies between *i* and *j*, not both steps | yes (leap-filling) |
| `INC_R`, `INC_L` | *k* a step from one end only | weaker (incomplete neighbour / appoggiatura / escape) |
| `NEI_LEAP` | *i* = *j*, *k* a leap away | weak (arpeggiated return) |
| `OTHER` | anything else | penalised |

This is Bean 2020's "licensed neighbour, passing and leap-filling only", with the prolongation
types of Kirlin's and Marsden's models. Steps and leaps are counted in letter names (diatonic
steps), so B and B♭ are the same step from C and nothing depends on a mode.

## 3. How the two fit together (triangle weights)

| Weight | Rule |
| --- | --- |
| `sub_min`, `sub_max` | *k* should not be more salient than the endpoints it elaborates (subordination). |
| `leap` | Connections at every level prefer steps (a stepwise middleground). |
| `same_pitch_edge`, `same_pitch_span` | Optional prior for prolonging one pitch. **0 by default**, so focal pitches are found, not assumed. Turning it on (0.5) leaves the dominant focal pitches of all ten F Dominus clausulae unchanged. |
| `root_sal`, `edge_sal`, `EDGE_*` | Only with `frame='virtual'` (first and last notes may be elaborations). |

The best triangulation under the summed score is found exactly by dynamic programming (CKY over
the polygon, O(n³)).

## 4. Reading the hierarchy

* **Height** of a note: 0 for a surface ornament, one more than its highest child otherwise.
  Keeping notes of height ≥ h gives a reduction closed under the hierarchy.
* **Span** of a note: the length of its parent interval, in bars (or `--unit`). Keeping notes
  with span ≥ T is a reduction "at the T-bar level"; `levels_by_span_units` lists T = 1, 2, 4 … 64.
* **Fundamental line**: by default the span threshold that keeps about one note per eight bars
  (at least four). `--fundamental span:T | height:H | count:K | notes:…` overrides it.
* **Focal pitch**: notes of one pitch joined by edges of the hierarchy (F … F … F, everything
  between elaborating it). A span is *focal* when the pitch returns at least once per 8 bars and the
  voice spends at least 40% of the span on the pitch or a step from it. *Dominant* focal pitches are
  focal spans not inside a longer focal span.

## 5. Checked against human reductions

The GTTM database (Hamanaka, Hirata & Tojo; 300 eight-bar melodies with hand-made time-span trees,
https://gttm.jp/gttm/database/) is the largest freely downloadable set of human melodic reductions I found that is
monophonic and machine-readable. Kirlin's Schenker41 repository holds only its README. The
database is tonal, so it tests the generic rules (metre, duration, grouping, contour, the shape of
the tree), not the consonance or clausula rules.

Score = share of each human reduction level that the reducer's reduction of the same size keeps,
averaged over levels. `fit` searched the generic weights on every other melody (folders in sorted order); the numbers
below are on the other 135 (`melodic-reduction gttm DIR`, `melodic-reduction fit DIR`):

| Ranking | Held-out agreement |
| --- | --- |
| duration alone | 0.581 |
| beat strength alone | 0.610 |
| rule defaults: tree (span order) | 0.698 |
| rule defaults: salience alone | 0.736 |
| fitted (`weights_gttm.json`): tree | 0.760 |
| fitted: salience alone | 0.765 |

Fitting raised metre (1 → 4), lowered duration (1 → 0.5), made the tree defer more to salience
(`sub_min` 2 → 4.5) and dropped the step preference (`leap` −0.3 → +0.2). GTTM time-span trees are
built from the same salience rules and know nothing of licensed passing or neighbour motion, so
they reward a tree that simply follows salience. That is why the fitted set is not the default:
for clausulae the step and licensing rules are the point, and the tenor-consonance weights, which
GTTM cannot fit, would be swamped by a metre weight of 4.

## 6. Robustness on the Dominus clausulae

Dominant focal pitches of the ten clausulae in F (CANDR settings 865–874 realised by
ligature-rhythm with the Dominus weights), under three weight sets. Measures are of the realised
scores, not the edition.

| Clausula | rule defaults | + focal prior (`same_pitch_edge` 0.5) | GTTM-fitted salience |
| --- | --- | --- | --- |
| F_00 (Dominus 3) | F 11–67, D 78–85 | F 11–67, D 78–85 | F 19–67, C 75–89 |
| F_01 | F 20–54, C 62–77 | F 1–54, E 55–81 | F 1–49, E 55–81 |
| F_02 | C 14–16, C 27–72 | C 14–16, C 27–72 | D 7–20, C 27–72, F 75–78 |
| F_03 | E 2–40 | E 2–40 | F 1–15, C 31–39 |
| F_04 | F 1–4, C 11–35, E 37–50 | same | C 11–47 |
| F_05 | F 2–7, C 9–54 | same | same |
| F_06 | F 1–56, E 57–61 | F 1–43, E 44–61 | F 1–56, E 57–61 |
| F_07 | C 13–15, E 22–29, F 50–53, C 59–75, C 84–106, C 112–154 | D 1–31, F 50–53, C 59–154 | D 1–31, F 50–53, C 59–154 |
| F_08 | E 3–11, C 17–44 | same | C 17–44 |
| F_09 | C 12–36, F 37–54, E 65–71, D 74–79, F 85–105, G 109–113 | same | similar, finer |

The long prolongations (F in F_00, F_05 C, F_06 F, F_07 C from m. 59, F_08 C) survive every weight
set; F_01, F_03 and the openings of several pieces depend on the weights and should be argued from
the score, not from the tool.

## 7. The grouped tree (default)

Written after Alex's critique of the flat reducer on Dominus 3: structural notes clustered at
the start, no foreground reduction was visible, and the choices ignored the form. The piece
sounds in pairs of ordines (given by the rhythmic mode), the last pitch of each pair of pairs
(bar 15 of 16) sounds like a home note, and form and structure should inform each other.

**Ordines and the unit.** Notes between rests. The grouping unit is the tenor's shortest common
ordo length (the tenor pattern is the steadiest clock), doubled until it is at least the
duplum's shortest common ordo length. A duplum rest-group longer than 1.25 units is cut on that
grid: the duplum often runs through the tenor's rest (Dom 3 mm. 37–43, 45–51, 77–87; Dom 4 and 6
throughout), and the pair level puts the halves back together. With the duplum's own period as
the unit (the first version), Dom 4, 5, 12, 14 and 15 got lopsided groups; with the tenor's, 13 of
the 16 pieces fall into pairs of pairs of four units (16 bars at the usual 3/8), and the rest are
Dom 1 (from organum pages, irregular), Dom 5 and 12 (irregular ordo lengths).

**Grouping** (`grouping` weights), for each level above the ordo, by dynamic programming:

| Weight | Rule |
| --- | --- |
| `size3`, `size1`, `tag` | groups of two preferred; three cost 1.2; one costs 2, except a tag at the end (0.3) |
| `unequal` | members of unequal length cost (standard deviation of their lengths) |
| `cadence`, `cadence_high` | reward for a group ending on a perfect (1) or medial (0.6) consonance with the other voice; `cadence_high` above the pair level |
| `parallel`, `parallel_pairs` | reward for members resembling each other (a + a′); weaker for pairs of ordines, whose two ordines usually differ |
| `repeat` | reward for a group that recurs elsewhere in the same phase (a pair that comes back as a pair) |

Similarity is a global alignment of the two note sequences (pitch by letter and duration; a step
off or a different duration counts half; transposition up to two steps at a small cost), with the
other voice's rhythm over the same stretch counting 30%: the tenor's alternation of ordo patterns
is what fixes the phase of the pairs.

**Tree.** Inside each group, the members (notes of an ordo, or the heads of the subgroups) are
triangulated with the §2–3 rules inside a virtual frame, so no ordo's reduction reaches into the
next. Each group's last member gets `tree.cadence` (1.5), its first `tree.initial` (0.3); the
piece's first and last notes get `tree.piece_edge` (2) at the top only. The root is the head.

**Module labels.** A pair's letter comes from its opening: the first three pitches of its first
ordo (repeats merged, rhythm ignored). Pairs that open alike share a letter; a pair that matches an
earlier member as a whole (≥ 0.9, pitch and rhythm) takes its label, otherwise the next prime. A
last group much shorter than the rest is the `tag`. Revised after Alex's reading of Dom 3: 25–31
and 49–55 open C–D–E–F like 33–40, so they are b-family, and 81–87 opens D…E–F, so it is a-family.

**Home, pedal, line.** For each pair of pairs: the home note is its head; the pedal is the pitch
that recurs most among its ordo heads other than the home pitch (at least twice), marked upper or
lower; the line is the longest chain of ordo heads, in order, moving by step in one direction into
the home note (three notes or more). Dom 3 has one, F–E–D in mm. 57–72; across the corpus there
are five (Dom 3, 6, 8, 9b, 10).

**Tenor.** Reduced the same way against the duplum; its ordines are placed in the duplum's pairs
(an ordo belongs to the pair in which it ends) and the tree is built on those groups.

**Ligatures** (`ligatures=True`): each ligature is reduced first and its head represents it in
the ordo. Off by default: ligature brackets are notation, not a reduction.

**Calibration.** `cadence_high` = 1.5 is the value at which Dom 3's pairs of pairs come out as Alex
hears them (1–16, 17–32, 33–56 with the extra pair, 57–72, 73–88, tag); at 1.2 or lower the extra
pair is missed. It has not been checked on the other clausulae.

**Dominus 3 (Alex's encoding) with the defaults.** Alex's own reading, for comparison: D home
through m. 32 with F as a structural upper pedal; mm. 33–56 irregular, F marked as home; a 3-line
descent in mm. 57–72; the piece ends on E over A, off the home note. The tool agrees except in
mm. 33–56, where it hears C (m. 55) as the arrival and F only as the pedal (4 of 6 ordo heads).

| Pair of pairs | Pairs (labels) | Ordo heads | Home | Pedal |
| --- | --- | --- | --- | --- |
| mm. 1–16 | a, a′ | F C F D | D (m. 15) | upper F |
| 17–32 | a″, b | F B♭ F D | D (m. 31) | upper F |
| 33–56 | b′, b″, b‴ | F D F F F C | C (m. 55) | upper F |
| 57–72 | a′, a′ | F E F D (line F–E–D) | D (m. 71) | upper F |
| 73–88 | c, a‴ | C D D C | C (m. 87) | upper D |
| 89–92 | tag | E | E (m. 92) | |

Sections: 1–32 (A), 33–56 (B), 57–88, tag; piece head E (m. 92), a fifth over the tenor's A.
The tenor's line at the pair-of-pairs level: D D D C G C A. The CANDR reading of F 149r gives the
same upper levels, with or without ligatures.

## References

* Lerdahl, F. & Jackendoff, R. (1983). *A Generative Theory of Tonal Music*. MIT Press.
* Yust, J. (2006). *Formal Models of Prolongation*. PhD diss., University of Washington.
* Kirlin, P. B. & Jensen, D. D. (2011). Probabilistic modeling of hierarchical music analysis. *ISMIR*.
* Kirlin, P. B. (2014). *A Probabilistic Model of Hierarchical Music Analysis*. PhD diss., UMass Amherst.
* Marsden, A. (2010). Schenkerian analysis by computer: a proof of concept. *Journal of New Music Research* 39(3).
* Hamanaka, M., Hirata, K. & Tojo, S. (2014). Musical structural analysis database based on GTTM. *ISMIR*.
* Thomassen, J. (1982). Melodic accent: experiments and a tentative model. *JASA* 71(6).
* Bean, A. (2020). Formal Grammar in the Dominus Clausulae. Unpublished paper.
* Mathias, A. PhD dissertation, Ex. 2.18 (Dominus 3, modules A/B/A′/B′).
* Objections to answer: Schulenberg, "Modes, Prolongations, and Analysis"; Leach, "Counterpoint and
  Analysis in Fourteenth-Century Song".
