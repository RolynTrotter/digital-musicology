"""Write reductions as notation, using music21's own reduction machinery.

music21.analysis.reduction.ScoreReduction takes notes tagged with a lyric specification
('::/g:<group>/nf:no/sd:up' ...) and builds one staff per group above the original score, with each
reduced note at its original position and hidden rests in between. We tag the notes kept at each
requested level and let it do the layout.
"""
from __future__ import annotations

import copy

from music21 import converter, stream
from music21.analysis.reduction import ScoreReduction

from .voice import load_score


def _level_sets(analysis, levels):
    notes = analysis['notes']
    out = []
    for lv in levels:
        if lv == 'fundamental':
            out.append(('fundamental', set(analysis['fundamental']['notes'])))
        elif str(lv).startswith('span:'):
            T = float(str(lv).split(':')[1])
            out.append((f'span {T:g}', {n['idx'] for n in notes if n['span_units'] >= T}))
        elif str(lv).startswith('height:'):
            H = int(str(lv).split(':')[1])
            out.append((f'height {H}', {n['idx'] for n in notes if n['height'] >= H}))
        else:
            raise ValueError(f'unknown level {lv!r}')
    return out


def reduction_score(score, analysis, levels=('fundamental', 'span:4')) -> stream.Score:
    """The original score with one reduction staff per level above it (background first)."""
    s = copy.deepcopy(load_score(score))
    part = s.parts[analysis['part']]
    seq = [n for n in part.recurse().notes
           if not (n.tie is not None and n.tie.type in ('stop', 'continue')) and not n.duration.isGrace]
    if len(seq) != len(analysis['notes']):
        raise ValueError('score and analysis disagree on the number of notes')
    fund = set(analysis['fundamental']['notes'])
    for name, keep in _level_sets(analysis, levels):
        g = name.replace(' ', '_')
        for k in sorted(keep):
            nf = 'no' if k in fund else 'yes'   # open noteheads for the fundamental line
            sd = 'up' if k in fund else 'noStem'
            seq[k].addLyric(f'::/g:{g}/nf:{nf}/sd:{sd}')
    sr = ScoreReduction()
    sr.score = s
    red = sr.reduce()
    # ScoreReduction's template parts carry copies of the original's spanners (the ligature
    # brackets); drop them from the reduction staves and name those staves after their level
    names = [nm for nm, _ in _level_sets(analysis, levels)]
    from music21 import spanner
    for p in red.parts:
        if p.id in {nm.replace(' ', '_') for nm in names}:
            for sp in list(p.recurse().getElementsByClass(spanner.Spanner)):
                p.remove(sp, recurse=True)
            p.partName = str(p.id).replace('_', ' ')
            p.partAbbreviation = None
            for inst in p.recurse().getElementsByClass('Instrument'):
                inst.partName = p.partName
    return red


def write_reduction(score, analysis, path, levels=('fundamental', 'span:4')):
    red = reduction_score(score, analysis, levels)
    red.write('musicxml', fp=str(path))
    return path
