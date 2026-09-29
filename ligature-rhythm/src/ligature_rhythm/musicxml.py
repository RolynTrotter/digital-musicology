"""Writing realised clausulae as MusicXML (3/8, one perfection per bar, duplum over tenor).

Ligatures are shown as brackets above the notes (dashed for currentes) and plica notes at cue size,
following modern edition practice. Notes that cross a barline are split and tied.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Sequence

from .realise import Event

BAR = 6                                    # sixteenths per 3/8 bar
DIVISIONS = 4                              # MusicXML divisions per quarter note = sixteenths
TYPES = {1: ('16th', 0), 2: ('eighth', 0), 3: ('eighth', 1), 4: ('quarter', 0), 6: ('quarter', 1)}


def _pieces(d: int) -> list:
    """split a within-bar duration into notatable values, largest first"""
    out = []
    for v in (6, 4, 3, 2, 1):
        while d >= v:
            out.append(v)
            d -= v
    return out


def _fill(events: Sequence[Event], total: int) -> list:
    """sorted events with gaps filled by rests, padded to `total`"""
    out, t = [], 0
    for e in sorted(events, key=lambda e: e.onset):
        on, d = e.onset, e.duration
        if on > t:
            out.append(Event(t, on - t, None))
        if on < t:                        # overlap guard
            d -= t - on
            on = t
            if d <= 0:
                continue
        out.append(Event(on, d, e.pitch, e.lig, e.plica, e.mode, e.note_id))
        t = on + d
    if total > t:
        out.append(Event(t, total - t, None))
    return out


def _sub(parent, tag, text=None, **attrs):
    el = ET.SubElement(parent, tag, {k.replace('_', '-'): str(v) for k, v in attrs.items()})
    if text is not None:
        el.text = str(text)
    return el


def _bracket(measure, kind, dashed=False):
    d = _sub(measure, 'direction', placement='above')
    dt = _sub(d, 'direction-type')
    attrs = dict(type=kind, number=1, line_end='down')
    if kind == 'start':
        attrs['line_type'] = 'dashed' if dashed else 'solid'
    _sub(dt, 'bracket', **attrs)


def _part(root_part, events: Sequence[Event], clef: str, total: int):
    measures = {}
    for e in _fill(events, total):
        segs, t, rem = [], e.onset, e.duration
        while rem > 0:
            dd = min(rem, BAR - t % BAR)
            for v in _pieces(dd):
                segs.append((t, v))
                t += v
            rem -= dd
        for j, (t0, v) in enumerate(segs):
            measures.setdefault(t0 // BAR, []).append((e, v, j, len(segs)))
    shown_flat = set()
    for m in range(total // BAR):
        meas = _sub(root_part, 'measure', number=m + 1)
        if m == 0:
            a = _sub(meas, 'attributes')
            _sub(a, 'divisions', DIVISIONS)
            _sub(_sub(a, 'key'), 'fifths', 0)
            tm = _sub(a, 'time')
            _sub(tm, 'beats', 3)
            _sub(tm, 'beat-type', 8)
            c = _sub(a, 'clef')
            if clef == 'G8':
                _sub(c, 'sign', 'G'); _sub(c, 'line', 2); _sub(c, 'clef-octave-change', -1)
            else:
                _sub(c, 'sign', 'F'); _sub(c, 'line', 4)
        for e, v, j, n in measures.get(m, []):
            lig = e.lig
            if lig and lig[1] == 0 and j == 0:
                _bracket(meas, 'start', dashed=lig[3] == 'currentes')
            note = _sub(meas, 'note')
            if e.pitch is None:
                _sub(note, 'rest')
            else:
                step, alt, octv = e.pitch
                p = _sub(note, 'pitch')
                _sub(p, 'step', step)
                if alt:
                    _sub(p, 'alter', alt)
                _sub(p, 'octave', octv)
            _sub(note, 'duration', v)
            tie_start, tie_stop = e.pitch is not None and j < n - 1, e.pitch is not None and j > 0
            if tie_stop:
                _sub(note, 'tie', type='stop')
            if tie_start:
                _sub(note, 'tie', type='start')
            _sub(note, 'voice', 1)
            typ, dots = TYPES[v]
            if e.plica:
                _sub(note, 'type', typ, size='cue')
            else:
                _sub(note, 'type', typ)
            for _ in range(dots):
                _sub(note, 'dot')
            if e.pitch is not None and e.pitch[1] == -1 and j == 0:
                _sub(note, 'accidental', 'flat')
            if tie_start or tie_stop:
                nt = _sub(note, 'notations')
                if tie_stop:
                    _sub(nt, 'tied', type='stop')
                if tie_start:
                    _sub(nt, 'tied', type='start')
            if lig and lig[1] == lig[2] - 1 and j == n - 1:
                _bracket(meas, 'stop')
        if m not in measures:
            note = _sub(meas, 'note')
            _sub(note, 'rest', measure='yes')
            _sub(note, 'duration', BAR)
            _sub(note, 'voice', 1)


def to_musicxml(upper: Sequence[Event], tenor: Sequence[Event], title: str = '', subtitle: str = '') -> str:
    end = max((e.onset + e.duration for e in list(upper) + list(tenor)), default=BAR)
    end += (-end) % BAR
    root = ET.Element('score-partwise', version='3.1')
    if title:
        _sub(_sub(root, 'work'), 'work-title', title)
    if subtitle:
        _sub(root, 'movement-title', subtitle)
    _sub(_sub(_sub(root, 'identification'), 'encoding'), 'software', 'ligature-rhythm')
    pl = _sub(root, 'part-list')
    for pid, name in (('P1', 'Duplum'), ('P2', 'Tenor')):
        _sub(_sub(pl, 'score-part', id=pid), 'part-name', name)
    _part(_sub(root, 'part', id='P1'), upper, 'G8', end)
    _part(_sub(root, 'part', id='P2'), tenor, 'F', end)
    ET.indent(root, space=' ')
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 3.1 Partwise//EN" '
            '"http://www.musicxml.org/dtds/partwise.dtd">\n' + ET.tostring(root, encoding='unicode') + '\n')


def write(path, upper, tenor, title: str = '', subtitle: str = '') -> Path:
    path = Path(path)
    path.write_text(to_musicxml(upper, tenor, title, subtitle), encoding='utf-8')
    return path
