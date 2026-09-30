"""Load one voice of a score as a list of notes with the context the reducer needs.

Everything here is tonality-free: pitches are compared by diatonic step (letter + octave,
music21's ``diatonicNoteNum``) and, for the reference voice, by semitone interval class.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from fractions import Fraction

from music21 import converter, stream, note, chord, meter


@dataclass
class VNote:
    idx: int                 # position in the voice (0-based, tied notes merged)
    pitch: str               # nameWithOctave, e.g. 'B-4'
    midi: int
    dnum: int                # diatonic note number (C4 = 29); steps are |dnum difference| == 1
    onset: float             # quarterLength from the start of the part
    dur: float               # quarterLength (tied notes merged)
    measure: int             # measure number of the onset
    beat_strength: float     # music21 beatStrength of the onset (1.0 = downbeat)
    occurrence: int          # nth occurrence of this pitch in its measure (1-based), for addressing
    after_rest: bool = False     # first note of a group (piece start or after a rest)
    before_rest: bool = False    # last note of a group (piece end or before a rest)
    ref_interval: int | None = None   # semitones above the reference voice note sounding at onset
    ref_class: str | None = None      # consonance class of that interval
    ref_onset: bool = False           # a reference-voice note starts together with this one
    group: int = 0                    # index of the rest-delimited group (ordo)
    features: dict = field(default_factory=dict)

    @property
    def end(self) -> float:
        return self.onset + self.dur

    @property
    def address(self) -> str:
        """Kirlin-style address: measure, pitch (lower-case, music21 accidental), occurrence."""
        return f'{self.measure}{self.pitch.lower()}-{self.occurrence}'

    def to_dict(self):
        d = asdict(self)
        d['address'] = self.address
        return d


# Consonance classes for the interval a voice makes with the reference voice (semitones mod 12).
# Default follows Johannes de Garlandia's ordering (perfect, medial, imperfect consonance; imperfect,
# intermediate, perfect dissonance). Weights for each class live in the weights file, so a
# different theory (or none) is a weights change, not a code change.
CONSONANCE = {
    0: 'perfect', 7: 'medial', 5: 'medial', 3: 'imperfect', 4: 'imperfect',
    2: 'imp_diss', 8: 'imp_diss', 9: 'int_diss', 10: 'int_diss',
    1: 'perf_diss', 6: 'perf_diss', 11: 'perf_diss',
}


def _top(n):
    if isinstance(n, chord.Chord):
        return max(n.notes, key=lambda x: x.pitch.ps)
    return n


def _flat_events(part: stream.Part):
    """(offset, quarterLength, element) for notes and rests, ties merged, in order."""
    p = part.stripTies(inPlace=False)
    out = []
    for el in p.flatten().notesAndRests:
        if el.duration.isGrace:
            continue
        out.append((float(el.getOffsetInHierarchy(p)), float(el.quarterLength), el))
    out.sort(key=lambda x: x[0])
    return p, out


def load_score(path_or_stream):
    if isinstance(path_or_stream, stream.Stream):
        return path_or_stream
    return converter.parse(str(path_or_stream))


def load_voice(score, part: int = 0, reference: int | None = None) -> list[VNote]:
    """Extract part ``part`` as VNotes; if ``reference`` is given, annotate each note with the
    interval it makes against that part (for clausulae: duplum = 0, tenor = 1)."""
    s = load_score(score)
    parts = list(s.parts)
    if part >= len(parts):
        raise ValueError(f'score has {len(parts)} parts; part {part} requested')
    p, events = _flat_events(parts[part])

    ref_events = None
    if reference is not None and reference < len(parts) and reference != part:
        _, ref_events = _flat_events(parts[reference])
        ref_events = [(o, d, _top(e)) for o, d, e in ref_events if not e.isRest]

    notes: list[VNote] = []
    per_measure_count: dict[tuple[int, str], int] = {}
    prev_rest = True
    group = -1
    for k, (off, dur, el) in enumerate(events):
        if el.isRest:
            if notes:
                notes[-1].before_rest = True
            prev_rest = True
            continue
        n = _top(el)
        mnum = el.measureNumber if el.measureNumber is not None else 0
        key = (mnum, n.pitch.nameWithOctave)
        per_measure_count[key] = per_measure_count.get(key, 0) + 1
        try:
            bs = float(el.beatStrength)
        except Exception:  # no time signature
            bs = 1.0 if off == int(off) else 0.5
        if prev_rest:
            group += 1
        v = VNote(idx=len(notes), pitch=n.pitch.nameWithOctave, midi=int(round(n.pitch.ps)),
                  dnum=n.pitch.diatonicNoteNum, onset=off, dur=dur, measure=mnum,
                  beat_strength=bs, occurrence=per_measure_count[key],
                  after_rest=prev_rest, group=group)
        notes.append(v)
        prev_rest = False
    if notes:
        notes[-1].before_rest = True

    if ref_events:
        j = 0
        for v in notes:
            while j + 1 < len(ref_events) and ref_events[j + 1][0] <= v.onset + 1e-9:
                j += 1
            ro, rd, rn = ref_events[j]
            if ro <= v.onset + 1e-9 < ro + rd:
                iv = v.midi - int(round(rn.pitch.ps))
                v.ref_interval = iv
                v.ref_class = CONSONANCE[abs(iv) % 12]   # voice crossing: the interval is the same
                v.ref_onset = abs(ro - v.onset) < 1e-6
    return notes


def piece_bounds(notes: list[VNote]) -> tuple[float, float]:
    return (notes[0].onset, notes[-1].end) if notes else (0.0, 0.0)
