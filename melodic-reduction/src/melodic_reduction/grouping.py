"""Formal grouping: ordines, pairs of ordines, pairs of pairs, ... up to the whole voice.

The lowest level is the *ordo*: the notes between rests. Where an edition joins ordines without a
rest (a voice running through the other voice's rest), a group much longer than the voice's usual
ordo period is cut on that period's grid, so every level-1 group is one ordo.

Higher levels group the units below into twos, allowing threes (and a lone unit at the end, a
tag) at a cost. The choice is a dynamic programme over the whole voice that prefers, for every
group:

* two members (the modal pairing of ordines and of pairs), then three, then one;
* members of equal length;
* ending on a strong cadence: the group's last note long and in perfect consonance with the other
  voice (unison / octave strongest, then fifth);
* members that resemble each other (a with a', b with b') -- parallelism.

Optionally, ligatures (MusicXML brackets) form a level below the ordo.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from .voice import VNote


@dataclass
class Group:
    level: int                 # 0 = ligature, 1 = ordo, 2 = pair, 3 = pair of pairs, ...
    first: int                 # first note index
    last: int                  # last note index (inclusive)
    children: list = field(default_factory=list)   # Groups one level down (empty for the lowest)
    head: int | None = None    # note index of the head, filled by the reduction
    label: str | None = None   # module label (a, a', b ...) for pairs

    def notes(self):
        return list(range(self.first, self.last + 1))

    def to_dict(self, notes):
        return {'level': self.level, 'first': self.first, 'last': self.last,
                'measures': [notes[self.first].measure, notes[self.last].measure],
                'head': self.head, 'label': self.label,
                'children': [c.to_dict(notes) for c in self.children]}


LEVEL_NAMES = {0: 'ligature', 1: 'ordo', 2: 'pair', 3: 'pair of pairs', 4: 'section', 5: 'half', 6: 'whole'}


def level_name(level: int, top: int) -> str:
    if level == top:
        return 'piece'
    return LEVEL_NAMES.get(level, f'level {level}')


# ------------------------------------------------------------------ ordines

def ordo_period(notes: list[VNote]) -> float | None:
    """Most common distance between the starts of successive rest-delimited groups."""
    starts = []
    for v in notes:
        if v.after_rest:
            starts.append(v.onset)
    d = [round(b - a, 4) for a, b in zip(starts, starts[1:])]
    if not d:
        return None
    return Counter(d).most_common(1)[0][0]


def ordines(notes: list[VNote], period: float | None = 'auto', split_long=True) -> list[tuple[int, int]]:
    """(first, last) note indices of each ordo."""
    groups: list[list[int]] = []
    for v in notes:
        if v.after_rest or not groups:
            groups.append([])
        groups[-1].append(v.idx)
    if period == 'auto':
        period = ordo_period(notes)
    out = []
    for g in groups:
        span = notes[g[-1]].end - notes[g[0]].onset
        if not split_long or not period or span <= period * 1.25:
            out.append((g[0], g[-1]))
            continue
        # cut on the period grid measured from the group's start
        start = notes[g[0]].onset
        cur = [g[0]]
        k = 1
        for i in g[1:]:
            if notes[i].onset >= start + k * period - 1e-6:
                out.append((cur[0], cur[-1]))
                cur = []
                while notes[i].onset >= start + (k + 1) * period - 1e-6:
                    k += 1
                k += 1
            cur.append(i)
        out.append((cur[0], cur[-1]))
    return out


def ligatures(score_part, notes: list[VNote]) -> list[tuple[int, int]]:
    """Ligature brackets (music21 Line spanners) as (first, last) note indices."""
    from music21 import spanner
    onset_idx = {round(v.onset, 4): v.idx for v in notes}
    out = []
    for sp in score_part.recurse().getElementsByClass(spanner.Line):
        a, b = sp.getFirst(), sp.getLast()
        try:
            oa = round(float(a.getOffsetInHierarchy(score_part)), 4)
            ob = round(float(b.getOffsetInHierarchy(score_part)), 4)
        except Exception:
            continue
        if oa in onset_idx and ob in onset_idx:
            out.append((onset_idx[oa], onset_idx[ob]))
    return sorted(set(out))


# ------------------------------------------------------------------ similarity (parallelism)

def _seq(notes, first, last):
    return [(notes[i].dnum, round(notes[i].dur, 4)) for i in range(first, last + 1)]


def seq_similarity(a, b, max_shift=2):
    """Similarity in [0, 1] of two note sequences (diatonic number, duration): global alignment
    where a note matches fully if pitch and duration agree, half if only one of them does or
    the pitch is a step off; transposition allowed at a small cost."""
    if not a or not b:
        return 0.0
    best = 0.0
    for t in range(-max_shift, max_shift + 1):
        n, m = len(a), len(b)
        D = np.zeros((n + 1, m + 1))
        D[:, 0] = -0.5 * np.arange(n + 1)
        D[0, :] = -0.5 * np.arange(m + 1)
        for i in range(1, n + 1):
            for j in range(1, m + 1):
                pa, da = a[i - 1]
                pb, db = b[j - 1]
                dp = abs(pa + t - pb)
                s = (1.0 if dp == 0 else 0.4 if dp == 1 else 0.0) * 0.6 + (0.4 if da == db else 0.0)
                D[i, j] = max(D[i - 1, j - 1] + s, D[i - 1, j] - 0.5, D[i, j - 1] - 0.5)
        sim = max(0.0, D[n, m] / max(n, m)) - 0.1 * abs(t)
        best = max(best, sim)
    return best


def _ref_rhythm(ref_notes, t0, t1):
    """The other voice's notes sounding from t0 to t1 as (0, duration, onset offset) tokens:
    its rhythm only, so the tenor's modal pattern marks where pairs begin."""
    if not ref_notes:
        return []
    return [(0, round(r.dur, 4)) for r in ref_notes if t0 - 1e-6 <= r.onset < t1 - 1e-6]


def unit_similarity(notes, u, v, ref_notes=None, ref_weight=0.3):
    """Similarity of two groups: member by member when they have the same number of members,
    else as flat note sequences; with ``ref_notes``, the other voice's rhythm over the same
    stretch counts for ``ref_weight``."""
    if u.children and v.children and len(u.children) == len(v.children):
        return float(np.mean([unit_similarity(notes, a, b, ref_notes, ref_weight)
                              for a, b in zip(u.children, v.children)]))
    s = seq_similarity(_seq(notes, u.first, u.last), _seq(notes, v.first, v.last))
    if ref_notes:
        ru = _ref_rhythm(ref_notes, notes[u.first].onset, notes[u.last].end)
        rv = _ref_rhythm(ref_notes, notes[v.first].onset, notes[v.last].end)
        if ru and rv:
            s = (1 - ref_weight) * s + ref_weight * seq_similarity(ru, rv, max_shift=0)
    return s


# ------------------------------------------------------------------ grouping DP

def _cadence(notes, i):
    v = notes[i]
    c = {'perfect': 1.0, 'medial': 0.6}.get(v.ref_class, 0.0) if v.ref_class else 0.3
    return c


def group_level(notes, units: list[Group], level: int, w: dict, ref_notes=None) -> list[Group]:
    """Partition ``units`` (consecutive Groups) into groups of 1-3 by dynamic programming."""
    n = len(units)
    size_cost = {1: w.get('size1', -2.0), 2: 0.0, 3: w.get('size3', -1.2)}
    lens = [notes[u.last].end - notes[u.first].onset for u in units]
    typical = float(np.median(lens)) if lens else 1.0
    sims = {}

    def sim(a, b):
        if (a, b) not in sims:
            sims[(a, b)] = unit_similarity(notes, units[a], units[b], ref_notes)
        return sims[(a, b)]

    wins = {}

    def window_sim(a, c, k):
        key = (a, c, k)
        if key not in wins:
            wins[key] = float(np.mean([sim(min(a + i, c + i), max(a + i, c + i)) for i in range(k)]))
        return wins[key]

    def repeats(a, k):
        """How well the window a..a+k-1 recurs elsewhere in the same phase (parallelism
        between groups: a pair that recurs as a pair)."""
        best = 0.0
        for c in range(a % k, n - k + 1, k):
            if abs(c - a) >= k:
                best = max(best, window_sim(a, c, k))
        return best

    def score(a, b):   # group of units a..b-1
        k = b - a
        s = size_cost[k]
        if k == 1 and b == n:
            s = w.get('tag', -0.3)        # a lone unit at the end: a tag
        member = [lens[i] / typical for i in range(a, b)]
        s -= w.get('unequal', 0.5) * float(np.std(member)) if k > 1 else 0.0
        wc = w.get('cadence', 0.8) if level <= 2 else w.get('cadence_high', 0.8)
        s += wc * _cadence(notes, units[b - 1].last)
        if k > 1:
            wp = w.get('parallel', 1.0) * (w.get('parallel_pairs', 0.3) if level == 2 else 1.0)
            s += wp * float(np.mean([sim(i, i + 1) for i in range(a, b - 1)]))
            s += w.get('repeat', 1.0) * repeats(a, k)
        return s

    best = [-math.inf] * (n + 1)
    back = [0] * (n + 1)
    best[0] = 0.0
    for b in range(1, n + 1):
        for k in (1, 2, 3):
            a = b - k
            if a < 0:
                continue
            s = best[a] + score(a, b)
            if s > best[b]:
                best[b], back[b] = s, a
    out = []
    b = n
    while b > 0:
        a = back[b]
        out.append(Group(level=level, first=units[a].first, last=units[b - 1].last,
                         children=units[a:b]))
        b = a
    return out[::-1]


def build_hierarchy(notes, ordo_spans, lig_spans=None, w=None, max_levels=8, ref_notes=None) -> Group:
    """Groups from ligatures (optional) and ordines up to one group for the whole voice."""
    w = w or {}
    units = []
    for f, l in ordo_spans:
        g = Group(level=1, first=f, last=l)
        if lig_spans:
            inside = [(a, b) for a, b in lig_spans if a >= f and b <= l]
            kids, cur = [], f
            for a, b in inside:
                for i in range(cur, a):
                    kids.append(Group(level=0, first=i, last=i))
                kids.append(Group(level=0, first=a, last=b))
                cur = b + 1
            for i in range(cur, l + 1):
                kids.append(Group(level=0, first=i, last=i))
            if any(k.last > k.first for k in kids):
                g.children = kids
        units.append(g)
    level = 1
    while len(units) > 1 and level < max_levels:
        level += 1
        units = group_level(notes, units, level, w, ref_notes)
    if len(units) == 1:
        return units[0]
    return Group(level=level + 1, first=units[0].first, last=units[-1].last, children=units)


def walk(g: Group):
    yield g
    for c in g.children:
        yield from walk(c)


def label_modules(notes, root: Group, level=2, same=0.9, variant=0.6, member=0.7, ref_notes=None):
    """Label the groups at ``level`` (pairs) a, a′, b ... by duplum similarity.

    A group takes the label of an earlier group it matches at >= ``same``. Otherwise it joins a
    family (and gets a new prime) if it is >= ``variant`` like the family's first group or
    >= ``member`` like any member; otherwise it starts a new letter. The best match and its
    similarity are kept in ``similar_to`` so the labels can be checked."""
    gs = [g for g in walk(root) if g.level == level]
    labels, proto, primes = [], {}, {}
    for i, g in enumerate(gs):
        sims = [unit_similarity(notes, gs[j], g, ref_notes) for j in range(i)]
        bj = int(np.argmax(sims)) if sims else None
        best = sims[bj] if sims else 0.0
        lab = None
        if bj is not None and best >= same:
            lab = labels[bj]
        else:
            fam = None
            for letter, pj in proto.items():
                if sims[pj] >= variant:
                    fam = letter if fam is None or sims[pj] > sims[proto[fam]] else fam
            if fam is None and bj is not None and best >= member:
                fam = labels[bj].rstrip('′')
            if fam is not None:
                primes[fam] = primes.get(fam, 0) + 1
                lab = fam + '′' * primes[fam]
            else:
                lab = chr(ord('a') + len(proto))
                proto[lab] = i
        labels.append(lab)
        g.label = lab
        g.similar_to = (bj, round(float(best), 3))
    return gs
