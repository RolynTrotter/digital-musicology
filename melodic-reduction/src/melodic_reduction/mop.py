"""Optimal prolongational hierarchy of a melody by dynamic programming over triangulations.

A reduction is represented as a maximal outerplanar graph (MOP; Yust 2006, Kirlin & Jensen 2011):
the notes of the voice, plus a virtual START and END, are the vertices of a polygon, and a
triangulation of that polygon is a complete hierarchy. Each triangle (i, k, j) says that note k
elaborates the motion from i to j: k disappears one level before i and j do. Every note is the
middle of exactly one triangle, so a triangulation assigns every note a parent interval.

The best triangulation under an additive score is found exactly with a CKY-style dynamic program
(O(n^3); a few seconds for a 250-note duplum).

Each triangle is scored by

* the kind of elaboration k makes between i and j (``relation`` weights): repetition, neighbour,
  passing, leap-filling, incomplete neighbour, and 'other' (unlicensed);
* subordination: k should be less salient than the endpoints (``sub_min``, ``sub_max``);
* leaps: stepwise connections are preferred at every level (``leap``);
* same-pitch edges: an interval i..j that begins and ends on the same pitch prolongs that pitch
  (``same_pitch_edge``, ``same_pitch_span``). This is the focal-pitch prior. Set it to 0 to check
  that focal pitches emerge without it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

RELATIONS = ['REP', 'NEI', 'NEI_LEAP', 'PASS', 'FILL', 'INC_R', 'INC_L', 'OTHER',
             'EDGE_REP', 'EDGE_STEP', 'EDGE_LEAP', 'ROOT', 'FRAME']

REL_NAMES = {
    'REP': 'repetition', 'NEI': 'neighbour', 'NEI_LEAP': 'leap away and back (arpeggiated return)',
    'PASS': 'passing', 'FILL': 'leap-filling (between, not stepwise)',
    'INC_R': 'incomplete neighbour (steps into the right)', 'INC_L': 'incomplete neighbour (steps from the left)',
    'OTHER': 'unlicensed leap', 'EDGE_REP': 'repetition at the edge', 'EDGE_STEP': 'step at the edge',
    'EDGE_LEAP': 'leap at the edge', 'ROOT': 'head of the whole voice',
    'FRAME': 'first or last note (the frame of the hierarchy)',
}


@dataclass
class Tree:
    n: int                   # number of real notes
    split: np.ndarray        # split[i, j] = k of the triangle on base (i, j), node indices
    parent: list             # parent[k] = (i, j) in node indices for node k (1..n)
    relation: list           # relation[k] name for node k
    height: np.ndarray       # height[k] for node k (0 = surface leaf); index 0 and n+1 unused
    depth: np.ndarray
    score: float

    def note_parent(self, k: int):
        """Parent interval of note k (0-based) as note indices; None for START/END."""
        i, j = self.parent[k + 1]
        return (None if i == 0 else i - 1, None if j == self.n + 1 else j - 1)


def _relations(di, dj, dk, vi, vj):
    """Classify k (array) against endpoints i, j. vi / vj: endpoint is real."""
    n = len(dk)
    rel = np.full(n, 'OTHER', dtype=object)
    if not vi and not vj:
        rel[:] = 'ROOT'
        return rel
    if not vi or not vj:
        e = di if vi else dj
        a = np.abs(dk - e)
        rel[:] = 'EDGE_LEAP'
        rel[a == 1] = 'EDGE_STEP'
        rel[a == 0] = 'EDGE_REP'
        return rel
    a = dk - di
    b = dj - dk
    between = a * b > 0
    step_a, step_b = np.abs(a) == 1, np.abs(b) == 1
    rel[step_a] = 'INC_L'
    rel[step_b] = 'INC_R'
    rel[between & ~(step_a & step_b)] = 'FILL'
    rel[between & step_a & step_b] = 'PASS'
    if di == dj:
        rel[np.abs(a) > 1] = 'NEI_LEAP'
        rel[np.abs(a) == 1] = 'NEI'
    rel[(a == 0) | (b == 0)] = 'REP'
    return rel


def triangle_features(i, j, ks, d, sal, onset, real, unit):
    """Feature arrays (name -> array over ks) for triangles (i, k, j)."""
    dk = d[ks]
    rel = _relations(d[i], d[j], dk, real[i], real[j])
    f = {}
    for r in RELATIONS:
        m = rel == r
        if m.any():
            f['rel_' + r] = m.astype(float)
    ends = [sal[x] for x in (i, j) if real[x]]
    sk = sal[ks]
    if ends:
        f['sub_min'] = np.minimum(0.0, min(ends) - sk)
        f['sub_max'] = np.minimum(0.0, max(ends) - sk)
    else:
        f['root_sal'] = sk
    if len(ends) == 1:
        f['edge_sal'] = sk
    lp = np.zeros(len(ks))
    if real[i]:
        lp += np.maximum(np.abs(dk - d[i]) - 1, 0)
    if real[j]:
        lp += np.maximum(np.abs(d[j] - dk) - 1, 0)
    f['leap'] = lp
    if real[i] and real[j] and d[i] == d[j]:
        f['same_pitch_edge'] = np.ones(len(ks))
        f['same_pitch_span'] = np.full(len(ks), math.log2(max(onset[j] - onset[i], unit) / unit))
    return f, rel


def _score(f, w):
    tot = 0.0
    for name, arr in f.items():
        if name.startswith('rel_'):
            tot = tot + w['relation'].get(name[4:], 0.0) * arr
        else:
            tot = tot + w['triangle'].get(name, 0.0) * arr
    return tot


def parse(d_notes, sal_notes, onset_notes, end_time, unit, w, frame='notes') -> Tree:
    """Best triangulation.

    frame='notes'   the first and last notes are the top edge (Kirlin's MOP without START/FINISH);
                    they stand above everything else. Right for pieces that begin and end on
                    structural notes (clausulae do).
    frame='virtual' add a virtual START and END so the first and last notes can be elaborations
                    too (e.g. an anacrusis). Notes hanging from a virtual end pay the
                    ``EDGE_*`` relation weights.
    """
    n = len(d_notes)
    virtual = frame == 'virtual'
    pad = 1 if virtual else 0
    M = n + 2 * pad
    d = np.asarray(d_notes, float)
    sal = np.asarray(sal_notes, float)
    onset = np.asarray(onset_notes, float)
    real = np.ones(M, dtype=bool)
    if virtual:
        d = np.concatenate([[0], d, [0]])
        sal = np.concatenate([[0.0], sal, [0.0]])
        onset = np.concatenate([[onset[0]], onset, [end_time]])
        real[0] = real[-1] = False

    best = np.full((M, M), -np.inf)
    split = np.full((M, M), -1, dtype=np.int32)
    for i in range(M - 1):
        best[i, i + 1] = 0.0
    for gap in range(2, M):
        for i in range(0, M - gap):
            j = i + gap
            ks = np.arange(i + 1, j)
            f, _ = triangle_features(i, j, ks, d, sal, onset, real, unit)
            cand = best[i, ks] + best[ks, j] + _score(f, w)
            b = int(np.argmax(cand))
            best[i, j] = cand[b]
            split[i, j] = ks[b]

    # node index -> tree arrays indexed 1..n for notes (0 and n+1 unused) whatever the frame
    parent = [None] * (n + 2)
    relation = [None] * (n + 2)
    height = np.zeros(n + 2, dtype=int)
    depth = np.zeros(n + 2, dtype=int)
    nid = (lambda x: x) if virtual else (lambda x: x + 1)       # node -> 1-based note slot
    stack = [(0, M - 1, 0 if virtual else 1, False)]
    while stack:
        i, j, dep, done = stack.pop()
        if j - i < 2:
            continue
        k = int(split[i, j])
        if not done:
            parent[nid(k)] = (nid(i), nid(j))
            depth[nid(k)] = dep
            _, rel = triangle_features(i, j, np.array([k]), d, sal, onset, real, unit)
            relation[nid(k)] = rel[0]
            stack.append((i, j, dep, True))
            stack.append((i, k, dep + 1, False))
            stack.append((k, j, dep + 1, False))
        else:
            h = 0
            if k - i >= 2:
                h = max(h, height[nid(split[i, k])] + 1)
            if j - k >= 2:
                h = max(h, height[nid(split[k, j])] + 1)
            height[nid(k)] = h
    if not virtual and n >= 1:
        top = int(height[1:n + 1].max()) + 1 if n > 2 else 1
        for x in (1, n):
            parent[x] = (0, n + 1)
            relation[x] = 'FRAME'
            height[x] = top
    return Tree(n=n, split=split, parent=parent, relation=relation, height=height,
                depth=depth, score=float(best[0, M - 1]))


def tree_features(tree: Tree, d_notes, sal_notes, onset_notes, end_time, unit) -> dict:
    """Summed feature vector of a whole tree (for fitting weights)."""
    n = tree.n
    d = np.concatenate([[0], np.asarray(d_notes, float), [0]])
    sal = np.concatenate([[0.0], np.asarray(sal_notes, float), [0.0]])
    onset = np.concatenate([[onset_notes[0]], np.asarray(onset_notes, float), [end_time]])
    real = np.ones(n + 2, dtype=bool)
    real[0] = real[-1] = False
    tot: dict = {}
    for k in range(1, n + 1):
        if tree.relation[k] == 'FRAME':
            continue
        i, j = tree.parent[k]
        f, _ = triangle_features(i, j, np.array([k]), d, sal, onset, real, unit)
        for name, arr in f.items():
            tot[name] = tot.get(name, 0.0) + float(arr[0])
    return tot
