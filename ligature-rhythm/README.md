# ligature-rhythm

Realise the rhythm of Notre-Dame modal notation (ligatures, plicae, currentes) from
[CANDR](https://www.candr.org.uk) MEI, and write MusicXML.

CANDR (the Clausula Archive of the Notre Dame Repertory) transcribes the manuscripts
diplomatically. Its MEI records each setting's pitches, ligatures, plicae and strokes, and which
events in the two voices sound together. It has no note values. This package supplies them the way
an editor would, and writes a modern score: 3/8, one perfection per bar, duplum over tenor. The
reader is tuned and tested on the *Dominus* clausulae.

```bash
pip install -e .                 # numpy, pandas; add [render] for verovio/cairosvg, [test] for pytest

ligature-rhythm fetch --out candr --title '^Dominus$'            # polite, resumable download
ligature-rhythm split 865 866 867 868 869 870 871 872 873 874 --candr-dir candr
ligature-rhythm realise 865 866 867 868 869 870 871 872 873 874 --candr-dir candr --out scores --prefix F149r
```

```python
import ligature_rhythm as lr

paths = [f'candr/setting_{i:04d}.mei' for i in range(865, 875)]      # consecutive settings, manuscript order
clausulae, _ = lr.split(paths, incipit='DCCACDCBCDAFA')              # or lr.guess_incipit(paths)
res = lr.realise(clausulae[0].upper, clausulae[0].tenor)   # model=lr.Model(lr.load_weights('dominus')) for the Dominus fit
lr.write('dominus.musicxml', res.upper, res.tenor, title='Dominus')
res.info    # home modes, ordo-ending styles, which voice led, dropped synchronisations, organum flag
```

## How it reads the notation

A voice is a sequence of notes and strokes. A Viterbi search (`decoder.py`, vectorised with numpy)
chooses a value for every note (B, L, L., duplex …), a rest for every stroke and a mode for every
ordo. Each choice is scored by weighted features (`features.py`):

| Template | What it encodes |
| --- | --- |
| `grid` | where in the perfection a value may start, per mode |
| `mctx`, `nxt`, `prev` | the note's notational context (single, place in its ligature, currentes, plica), what follows it, the previous value |
| `osig1-3` | the ordo's ligature pattern (ternaria first = mode 1, ternaria last = mode 2, …) |
| `cons`, `consd` | the interval the duplum makes with the tenor note under it |
| `rest`, `rctx`, `rshort` | the rest after a stroke, against the mode, the ordo's last note, and short ordines (a stroke after one or two single notes just separates them) |
| `olen`, `osame`, `ostart`, `coinc` | ordo lengths, a tenor repeating its ordo length, ordines starting on the beat and together with the other voice's |
| `stymatch`, `home0`, `offhome`, `mchg` | one ordo-ending style and one home mode per voice |

Both voices are read together (`realise.py`):

- **Synchronisation.** After every stroke CANDR marks as synchronised, both voices start their next
  ordo together. The two voices end together.
- **Which voice leads.** Either voice may be read first, and the better joint reading wins.
- **Tenor mode.** The tenor is in the fifth mode or in the duplum's mode.
- **Note against note.** Where the voices move note against note, the duplum shares the tenor's
  rhythm.

**Segmentation** (`segment.py`) cuts a run of settings, which follow the page layout, into
clausulae:

- A new clausula starts where the tenor begins the chant again at a system break, or where CANDR
  marks the two voices' first notes as simultaneous.
- A chant restart in mid-system with nothing marked is a second cursus of the same clausula.

**The weights** start from the theorists' rules (Garlandia, Anonymous IV; `theory_weights()`) and
are tuned on edition-based encodings (`train.py`):

- Each CANDR note is aligned by pitch with the edition to give it the edition's value.
- Each voice is cut into stretches between synchronisation points where CANDR and the edition
  agree, so each stretch is a small, self-contained problem.
- The weights are fitted with an averaged passive-aggressive structured perceptron.

## Accuracy

Tested on the 14 Dominus encodings (see [`benchmarks/`](benchmarks/)). Notes are matched to the edition
by pitch. **Cross-validated** means leave-one-clausula-out: each piece was read by a model tuned
without it, with near-duplicate pieces held out together. That column is the fair estimate for
new repertory.

| Measure (mean of 13 same-source pieces) | v1 reader¹ | v0.2, theory prior only | **v0.2, cross-validated²** | v0.2, fitted to these pieces³ |
| --- | --- | --- | --- | --- |
| duplum values | 79% | 73% | **78%** | 90% |
| tenor values | 81% | 75% | **82%** | 96% |
| duplum over the right tenor note | 62% | 70% | **68%** | 78% |
| duplum onsets within ordo | 73% | 67% | **70%** | 85% |
| tenor onsets within ordo | 83% | 78% | **85%** | 95% |
| duplum onsets (strict) | 53% | 40% | **58%** | 69% |
| tenor onsets (strict) | 63% | 48% | **68%** | 84% |

1. **v1 reader:** the previous hand-tuned cost table, on the same corrected segmentation. It was
   tuned by looking at these same pieces, so it is not out-of-sample either.
2. **Cross-validated:** the packaged `default` weights (conservative tuning: `--c-pa 0.01 --epochs 8`).
   The less regularised fit reached only 74% / 79% on values when cross-validated.
3. **Fitted to these pieces:** the packaged `dominus` weights (`--weights dominus`). This is the
   best reading of these particular pieces, not an estimate for others.

Dominus 10 is left out of the means. Its encoding follows F 172v, which CANDR lacks, so it is
compared across sources.

Measures:
- *values*: same note value as the edition.
- *over the right tenor note*: the duplum note sounds over the same tenor note as in the edition.
- *onsets within ordo*: the same position within the ordo.
- *strict onsets*: same onset after one global offset; one misplaced rest counts against everything
  after it.

**What generalises:** first-mode clausulae over a fifth-mode tenor read at 85–95% of values out of
sample (D2–D8, D12, D13). **What doesn't:** pieces with a reading found nowhere else in the set
(D14's first-mode tenor, the second-mode note-against-note 9b/11). With only ~11 independent
clausulae, the tuned model cannot learn those from the others. More edition-based encodings are the
most direct fix.

<details><summary>Per piece</summary>

| Piece | source | duplum values (CV / fit) | tenor values (CV / fit) | over the right tenor note (CV / fit) |
| --- | --- | --- | --- | --- |
| D2 | F | 92% / 95% | 96% / 98% | 91% / 93% |
| D3 | F | 93% / 97% | 95% / 98% | 90% / 91% |
| D4 | F | 87% / 94% | 98% / 97% | 93% / 85% |
| D5 | W1-49 | 88% / 88% | 93% / 97% | 63% / 65% |
| D6 | F | 93% / 95% | 98% / 98% | 91% / 93% |
| D7 | F | 86% / 94% | 95% / 93% | 56% / 82% |
| D8 | F | 86% / 87% | 96% / 96% | 23% / 43% |
| D9a | W1-55 | 84% / 98% | 87% / 95% | 89% / 98% |
| D9b | F | 55% / 68% | 73% / 89% | 51% / 64% |
| D10 | W1-55 | 85% / 72% | 49% / 52% | 18% / 15% |
| D11 | F | 46% / 77% | 44% / 98% | 40% / 80% |
| D12 | F | 95% / 96% | 98% / 98% | 98% / 99% |
| D13 | F | 94% / 100% | 91% / 98% | 77% / 90% |
| D14 | F | 21% / 83% | 7% / 87% | 18% / 32% |

</details>

## Limits

- **No ligature shapes in CANDR's MEI** (propriety, perfection, stems). Where an editor reads a
  ligature by its shape, the reader cannot know.
- **Strict onsets are the weak point.** One misplaced rest shifts a voice until the next
  synchronised stroke. Where CANDR marks few synchronisations, the voices can drift a perfection
  apart for a stretch; `info['synch_dropped']` and a look at the score catch most of it.
- **Second-mode, note-against-note clausulae are the least reliable.**
- **Organum purum** (held tenor notes under a melismatic duplum) is not modal discant. It is flagged
  (`info['organum_like']`), not realised.
- **Tuned on one tenor's clausulae.** Check a few pieces of any new repertory against an edition
  before trusting a whole run.

## Development

```bash
pip install -e '.[test]'
pytest                                   # unit tests; the decoder is checked against exhaustive search
LR_CANDR_DIR=candr LR_EDITIONS=editions pytest tests/test_benchmark.py     # integration test
```

Ideas that would likely improve accuracy:

- repeated duplum material read with the same rhythm;
- balanced pairs of ordo lengths;
- the drawn length of strokes;
- more edition-based encodings, especially second-mode pieces.

## Credits

The data are CANDR's (candr.org.uk); credit the archive in anything you publish. The Dominus edition
encodings are Alex Bean's (from Baltzer's edition of the Magnus liber organi and others).
