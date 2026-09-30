# Reduction rules

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
