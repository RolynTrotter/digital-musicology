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
res = lr.realise(clausulae[0].upper, clausulae[0].tenor)
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

On the 14 Dominus encodings (13 from the same sources as CANDR's copies), see
[`benchmarks/`](benchmarks/). In-sample means the pieces were used for tuning. Cross-validated
means leave-one-clausula-out, with near-duplicate pieces held out together.

| Measure (13 same-source pieces) | v1 reader | v0.2, in-sample | v0.2, cross-validated |
| --- | --- | --- | --- |
| duplum values | 79% | 90% | (running) |
| duplum onsets within ordo | 73% | 85% | (running) |
| duplum onsets (strict) | 53% | 69% | (running) |
| tenor values | 81% | 96% | (running) |
| tenor onsets (strict) | 63% | 84% | (running) |
| duplum over the right tenor note | 62% | 78% | (running) |

- **v1 reader** is the previous hand-tuned cost table, run on the same (corrected) segmentation.
- **Dominus 10** is left out of the means. Its encoding follows F 172v, which CANDR lacks, so it is
  compared across sources.
- **Measures:**
  - *values*: same note value as the edition;
  - *onsets (strict)*: same onset after one global offset, so one misplaced rest counts against
    everything after it;
  - *onsets within ordo*: same position within the ordo;
  - *same tenor note*: the duplum note sounds over the same tenor note as in the edition.

<details><summary>Per piece (in-sample)</summary>

| Piece | source | duplum values | duplum onsets (strict / in ordo) | tenor values | tenor onsets | same tenor note |
| --- | --- | --- | --- | --- | --- | --- |
| D2 | F | 95% | 95% / 95% | 98% | 100% | 93% |
| D3 | F | 97% | 93% / 93% | 98% | 98% | 91% |
| D4 | F | 94% | 44% / 85% | 97% | 42% | 85% |
| D5 | W1-49 | 88% | 47% / 58% | 97% | 78% | 65% |
| D6 | F | 95% | 84% / 88% | 98% | 94% | 93% |
| D7 | F | 94% | 40% / 90% | 93% | 33% | 82% |
| D8 | F | 87% | 51% / 88% | 96% | 89% | 43% |
| D9a | W1-55 | 98% | 95% / 95% | 95% | 95% | 98% |
| D9b | F | 68% | 49% / 58% | 89% | 85% | 64% |
| D10 | W1-55 | 72% | 41% / 78% | 52% | 42% | 15% |
| D11 | F | 77% | 68% / 88% | 98% | 98% | 80% |
| D12 | F | 96% | 98% / 98% | 98% | 100% | 99% |
| D13 | F | 100% | 100% / 100% | 98% | 89% | 90% |
| D14 | F | 83% | 37% / 72% | 87% | 89% | 32% |

</details>

```bash
ligature-rhythm evaluate benchmarks/dominus.json --candr-dir candr --editions editions
ligature-rhythm cv benchmarks/dominus.json --candr-dir candr --editions editions --workers 4
ligature-rhythm train benchmarks/dominus.json --candr-dir candr --editions editions --out weights.json
```

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
