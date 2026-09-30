"""Focal pitches: pitches prolonged over a stretch of the voice.

In the hierarchy an interval i..j whose endpoints are the same pitch is a prolongation of that
pitch: every note strictly between i and j elaborates it. Same-pitch edges that share a note chain
together (F ... F ... F), so a focal span is a connected set of same-pitch notes linked by edges of
the hierarchy, and it covers the time from its first note to the end of its last.
"""
from __future__ import annotations

import numpy as np


def hierarchy_edges(tree):
    edges = set()
    for k in range(1, tree.n + 1):
        i, j = tree.parent[k]
        for a, b in ((i, k), (k, j), (i, j)):
            if 1 <= a <= tree.n and 1 <= b <= tree.n:
                edges.add((min(a, b) - 1, max(a, b) - 1))
    return edges


def focal_spans(notes, tree, unit: float, min_span_units: float = 2.0, min_returns: int = 3,
                min_density: float = 1.0, min_within_step: float = 0.4):
    """Every same-pitch prolongation of at least ``min_span_units`` and ``min_returns`` notes.
    A prolongation counts as *focal* (heard as an elaboration of one pitch) when the pitch
    returns at least ``min_density`` times per 8 units and the voice spends at least
    ``min_within_step`` of the span on the pitch or a step from it. Sparse, long prolongations
    (a pitch that frames a whole section) are kept but marked ``focal: False``."""
    edges = [(a, b) for a, b in hierarchy_edges(tree) if notes[a].pitch == notes[b].pitch]
    parent = list(range(len(notes)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
    members: dict[int, set] = {}
    for a, b in edges:
        members.setdefault(find(a), set()).update((a, b))

    height = tree.height
    t0, t1 = notes[0].onset, notes[-1].end
    spans = []
    for root, mem in members.items():
        mem = sorted(mem)
        first, last = mem[0], mem[-1]
        start, end = notes[first].onset, notes[last].end
        length = end - start
        if length < min_span_units * unit or len(mem) < min_returns:
            continue
        inside = range(first, last + 1)
        on_pitch = sum(notes[x].dur for x in inside if notes[x].pitch == notes[first].pitch)
        near = sum(notes[x].dur for x in inside if abs(notes[x].dnum - notes[first].dnum) <= 1)
        spans.append({
            'pitch': notes[first].pitch,
            'first': first, 'last': last, 'members': mem,
            'start': start, 'end': end,
            'measures': [notes[first].measure, notes[last].measure],
            'length_units': round(length / unit, 3),
            'share_of_voice': round(length / (t1 - t0), 3),
            'returns': len(mem),
            'time_on_pitch': round(on_pitch / length, 3),
            'time_within_step': round(near / length, 3),
            'top_height': int(max(height[x + 1] for x in mem)),
            'returns_per_8_units': round(len(mem) / (length / unit) * 8, 3),
        })
        spans[-1]['focal'] = bool(spans[-1]['returns_per_8_units'] >= min_density
                                  and spans[-1]['time_within_step'] >= min_within_step)
    # nesting: a span inside a longer span is subordinate to it (listed in 'inside');
    # 'inside_focal' counts only focal containers
    spans.sort(key=lambda s: (s['start'], -s['end']))
    for s in spans:
        outer = [o for o in spans if o is not s and o['start'] <= s['start'] and o['end'] >= s['end']
                 and (o['end'] - o['start']) > (s['end'] - s['start'])]
        s['inside'] = [o['pitch'] + f"@m{o['measures'][0]}" for o in outer]
        s['inside_focal'] = [o['pitch'] + f"@m{o['measures'][0]}" for o in outer if o['focal']]
    return spans


def dominant_spans(spans):
    """Focal spans not inside a longer focal span: the top layer of focal pitches, in order."""
    return [s for s in spans if s['focal'] and not s['inside_focal']]


def pitch_profile(notes, weights, start=None, end=None):
    """Time-weighted share of each pitch between start and end, each note weighted by
    ``weights[idx]`` (e.g. 1 for every note, or its height + 1 to favour structural notes)."""
    tot, prof = 0.0, {}
    for v in notes:
        if start is not None and v.end <= start:
            continue
        if end is not None and v.onset >= end:
            continue
        x = v.dur * weights[v.idx]
        prof[v.pitch] = prof.get(v.pitch, 0.0) + x
        tot += x
    return {p: round(x / tot, 3) for p, x in sorted(prof.items(), key=lambda kv: -kv[1])} if tot else {}
