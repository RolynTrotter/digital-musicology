"""Note salience (how structural a note is on its own) and modular repetition.

Salience is a weighted sum of local features. Each feature is one of the rules in the
literature the defaults were taken from (see ``rules.md``):

    metric       beat strength of the onset                     GTTM TSRPR 1 (metrical position)
    duration     log2 of the note's length in the unit          GTTM TSRPR 2 / agogic accent
    cons_*       consonance class against the reference voice   GTTM TSRPR 2 (harmony) -> Garlandia
    ref_onset    a reference-voice note starts with this note   'structural points' (Bean 2020)
    group_start  first note after a rest (ordo start)           GTTM TSRPR 3/7 (grouping, cadence)
    group_end    last note before a rest (ordo end)             GTTM TSRPR 7 (cadential retention)
    piece_edge   first or last note of the piece                Schenker: the line's endpoints
    extreme      local highest / lowest point of the contour    registral accent (Huron/Thomassen)

Modular repetition (``find_modules``) finds passages that recur with the same rhythm and the same
diatonic intervals (so transposed repeats count) and ``parallelise`` makes corresponding notes of
the occurrences equally salient (GTTM TSRPR 4 / MPR 1, parallelism).
"""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

from .voice import VNote


def base_features(notes: list[VNote], unit: float) -> list[dict]:
    feats = []
    n = len(notes)
    for k, v in enumerate(notes):
        f = {
            'metric': v.beat_strength,
            'duration': math.log2(max(v.dur, 1e-6) / unit),
            'group_start': 1.0 if v.after_rest else 0.0,
            'group_end': 1.0 if v.before_rest else 0.0,
            'piece_edge': 1.0 if k in (0, n - 1) else 0.0,
            'ref_onset': 1.0 if v.ref_onset else 0.0,
        }
        if v.ref_class is not None:
            f['cons_' + v.ref_class] = 1.0
        lo = notes[k - 1].dnum if k > 0 else None
        hi = notes[k + 1].dnum if k + 1 < n else None
        nb = [x for x in (lo, hi) if x is not None]
        if nb and all(v.dnum > x for x in nb):
            f['extreme'] = 1.0
        elif nb and all(v.dnum < x for x in nb):
            f['extreme'] = 1.0
        feats.append(f)
    return feats


def salience(feats: list[dict], w: dict) -> np.ndarray:
    ws = w['salience']
    return np.array([sum(ws.get(k, 0.0) * x for k, x in f.items()) for f in feats], dtype=float)


# ---------------------------------------------------------------- modular repetition

def _tokens(notes, loose=False):
    """One token per note: its duration and the diatonic step to the next note.
    ``loose`` keeps only the direction of the step (contour), for varied repeats (a, a')."""
    toks = []
    for k, v in enumerate(notes):
        step = notes[k + 1].dnum - v.dnum if k + 1 < len(notes) else None
        rest_after = (k + 1 < len(notes)) and (notes[k + 1].onset - v.end > 1e-6)
        if loose and step is not None:
            step = (step > 0) - (step < 0)
        toks.append((round(v.dur, 4), step, rest_after))
    return toks


def find_modules(notes: list[VNote], min_notes: int = 5, loose: bool = False,
                 min_span: float = 0.0) -> list[dict]:
    """Maximal repeated passages (same rhythm, same diatonic intervals; with ``loose`` the same
    rhythm and contour). Returns groups sorted by coverage, each with its occurrences
    ``[(start_idx, end_idx_inclusive, transposition_in_steps)]``. Occurrences never overlap;
    a group needs two or more."""
    toks = _tokens(notes, loose)
    n = len(toks)
    if n < 2 * min_notes:
        return []
    # the last note of a window must match on duration only (its step leads outside)
    L = np.zeros((n + 1, n + 1), dtype=np.int32)
    for a in range(n - 1, -1, -1):
        for b in range(n - 1, a, -1):
            if toks[a] == toks[b]:
                L[a, b] = L[a + 1, b + 1] + 1
    found: dict[tuple, set] = defaultdict(set)
    for a in range(n):
        for b in range(a + 1, n):
            m = int(L[a, b])               # notes matched on duration and on the step onward
            # the note after the matched steps has the same relative pitch; include it if its
            # duration matches too (its own onward step may differ: the module ends there)
            if m and b + m < n and notes[a + m].dur == notes[b + m].dur:
                m += 1
            m = min(m, b - a)              # no overlap
            if m < min_notes:
                continue
            if a > 0 and toks[a - 1] == toks[b - 1]:
                continue                   # not left-maximal
            span = notes[a + m - 1].end - notes[a].onset
            if span < min_span:
                continue
            key = (a, m)
            found[key].add(b)
    # merge (a, m) with its matches into groups keyed by the token pattern
    groups: dict[tuple, dict] = {}
    for (a, m), bs in found.items():
        pat = tuple(toks[a:a + m - 1]) + (toks[a + m - 1][0],)
        g = groups.setdefault(pat, {'length': m, 'starts': set()})
        g['starts'].add(a)
        g['starts'].update(bs)
    out = []
    for pat, g in groups.items():
        starts = sorted(g['starts'])
        m = g['length']
        occ, last_end = [], -1
        for s in starts:
            if s > last_end:
                occ.append(s)
                last_end = s + m - 1
        if len(occ) < 2:
            continue
        ref = notes[occ[0]].dnum
        out.append({'length': m, 'loose': loose,
                    'occurrences': [(s, s + m - 1, notes[s].dnum - ref) for s in occ],
                    'coverage': sum(notes[s + m - 1].end - notes[s].onset for s in occ)})
    # drop groups whose occurrences all sit inside occurrences of a longer group
    out.sort(key=lambda g: (-g['length'], -g['coverage']))
    kept = []
    for g in out:
        inside = all(any(o[0] >= h[0] and o[1] <= h[1] for k in kept for h in k['occurrences'])
                     for o in g['occurrences'])
        if not inside:
            kept.append(g)
    kept.sort(key=lambda g: -g['coverage'])
    for i, g in enumerate(kept):
        g['label'] = _label(i) + ("'" if loose else '')
    return kept


def _label(i):
    s = ''
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def parallelise(sal: np.ndarray, modules: list[dict], alpha: float) -> np.ndarray:
    """Pull corresponding notes of each module's occurrences toward their mean salience."""
    if alpha <= 0:
        return sal
    out = sal.copy()
    for g in modules:
        m = g['length']
        for p in range(m):
            idx = [o[0] + p for o in g['occurrences']]
            mean = sal[idx].mean()
            for i in idx:
                out[i] = (1 - alpha) * out[i] + alpha * mean
    return out
