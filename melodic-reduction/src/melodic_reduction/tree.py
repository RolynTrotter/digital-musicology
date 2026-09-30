"""Reduction as a tree over the formal groups, from the foreground up.

Each group is reduced on its own: the heads of its members (for an ordo, its notes; with
ligatures, the heads of its ligatures) are triangulated with the same prolongation rules as the
flat reducer (mop.py), inside a virtual frame so the analysis of one ordo never reaches into the
next. The most important member becomes the group's head and represents the group one level up.
A member's position in the triangulation says what it does inside its group (passing,
neighbour, ...), and that is what the slurs of a graph draw.

Every group level adds a cadential weight to its last member: the end of an ordo, a pair and a
pair of pairs is where the voice arrives (GTTM TSRPR 7, cadential retention), which is how a pair
of pairs comes to be heard as prolonging its last note.
"""
from __future__ import annotations

import numpy as np

from .grouping import Group, walk
from .mop import parse


def reduce_tree(notes, root: Group, sal: np.ndarray, w: dict, unit: float) -> dict:
    tw = w.get('tree', {})
    info = {v.idx: {'reduced_at': None, 'parent': [None, None], 'relation': None, 'head_of': []}
            for v in notes}
    dep = []   # (level, group first, group last, child note, parent i, parent j, relation)

    def heads_of(g: Group):
        if g.children:
            return [reduce_group(c) for c in g.children]
        return list(range(g.first, g.last + 1))

    def reduce_group(g: Group) -> int:
        members = heads_of(g)
        if len(members) == 1:
            g.head = members[0]
            info[g.head]['head_of'].append(g.level)
            return g.head
        lvl_sal = np.array([sal[k] for k in members], float)
        lvl_sal[-1] += tw.get('cadence', 1.5)
        lvl_sal[0] += tw.get('initial', 0.3)
        if g is root:
            # the piece's first and last notes frame the whole voice (structural beginning and
            # ending) -- only at the top, so they do not outweigh the cadences of inner groups
            for pos, k in enumerate(members):
                if k in (0, len(notes) - 1):
                    lvl_sal[pos] += tw.get('piece_edge', 2.0)
        d = [notes[k].dnum for k in members]
        on = [notes[k].onset for k in members]
        t = parse(d, lvl_sal, on, notes[g.last].end, unit, w, frame='virtual')
        head = None
        for pos, k in enumerate(members):
            rel = t.relation[pos + 1]
            pi, pj = t.parent[pos + 1]
            pi = members[pi - 1] if pi and 1 <= pi <= len(members) else None
            pj = members[pj - 1] if pj and 1 <= pj <= len(members) else None
            if rel == 'ROOT':
                head = k
                continue
            info[k].update(reduced_at=g.level, parent=[pi, pj], relation=rel,
                           local_height=int(t.height[pos + 1]))
            dep.append((g.level, g.first, g.last, k, pi, pj, rel))
        g.head = head
        info[head]['head_of'].append(g.level)
        return head

    reduce_group(root)
    info[root.head]['relation'] = 'ROOT'
    for k, d in info.items():
        d['level'] = max(d['head_of']) if d['head_of'] else (d['reduced_at'] - 1 if d['reduced_at'] else 0)
    return {'notes': info, 'dependencies': dep}


def heads_at(root: Group, level: int) -> list[int]:
    """Heads of the groups at ``level`` (and of shallower branches that stop above it), in order."""
    out = []

    def go(g):
        if g.level <= level or not g.children:
            out.append(g.head)
            return
        for c in g.children:
            go(c)
    go(root)
    return out


def section_summary(notes, root: Group, level: int, ordo_level=1) -> list[dict]:
    """For each group at ``level``: its home note (head), the line of its members' heads, and the
    pitch that recurs most among its ordo heads apart from the home pitch (a pedal or focal
    pitch, typically above the home note)."""
    out = []
    for g in walk(root):
        if g.level != level:
            continue
        ordo_heads = heads_at(g, ordo_level)
        home = notes[g.head].pitch
        counts = {}
        for k in ordo_heads:
            p = notes[k].pitch
            counts[p] = counts.get(p, 0) + 1
        others = sorted(((c, p) for p, c in counts.items() if p != home), reverse=True)
        pedal = None
        if others and others[0][0] >= 2:
            c, p = others[0]
            above = next(v.dnum for v in notes if v.pitch == p) > notes[g.head].dnum
            pedal = {'pitch': p, 'ordo_heads': c, 'of': len(ordo_heads),
                     'position': 'upper' if above else 'lower'}
        # a stepwise line through the ordo heads into the home note (e.g. F-E-D, a 3-line
        # descent): the longest chain of heads, in order, each a step from the next, all in one
        # direction, ending on the home note
        line = []
        hk = [k for k in ordo_heads]
        if hk and hk[-1] == g.head:
            best = {len(hk) - 1: [len(hk) - 1]}
            for i in range(len(hk) - 2, -1, -1):
                cands = []
                for j, chain in best.items():
                    if j <= i:
                        continue
                    step = notes[hk[j]].dnum - notes[hk[i]].dnum
                    if abs(step) != 1:
                        continue
                    if len(chain) > 1:
                        nxt = notes[hk[chain[1]]].dnum - notes[hk[j]].dnum
                        if nxt != step:
                            continue
                    cands.append([i] + chain)
                if cands:
                    best[i] = max(cands, key=len)
            longest = max(best.values(), key=len)
            if len(longest) >= 3:
                line = [f'{notes[hk[i]].pitch}@m{notes[hk[i]].measure}' for i in longest]
        out.append({'measures': [notes[g.first].measure, notes[g.last].measure],
                    'line': line,
                    'home': home, 'home_measure': notes[g.head].measure,
                    'ordo_head_line': [f'{notes[k].pitch}@m{notes[k].measure}' for k in ordo_heads],
                    'member_heads': [f'{notes[c.head].pitch}@m{notes[c.head].measure}' for c in g.children],
                    'pedal': pedal, 'labels': [c.label for c in g.children if c.label]})
    return out


def map_hierarchy(master: Group, master_notes, notes, ordo_spans) -> Group:
    """Group another voice's ordines under the master voice's groups (the tenor under the
    duplum's pairs and pairs of pairs): an ordo belongs to the master group in which it ends."""
    ords = [Group(level=1, first=f, last=l) for f, l in ordo_spans]

    def span(g):
        return master_notes[g.first].onset, master_notes[g.last].end

    def build(mg: Group, pool: list[Group]) -> Group | None:
        if mg.level <= 1:
            return None
        kids = []
        if all(c.level <= 1 for c in mg.children):
            kids = pool
        else:
            for c in mg.children:
                t0, t1 = span(c)
                sub = [o for o in pool if t0 - 1e-6 <= notes[o.last].onset < t1 - 1e-6]
                # the last master child also takes ordines that run past its end
                if c is mg.children[-1]:
                    sub += [o for o in pool if notes[o.last].onset >= t1 - 1e-6 and o not in sub]
                if c is mg.children[0]:
                    sub = [o for o in pool if notes[o.last].onset < t0 - 1e-6] + sub
                b = build(c, sub)
                if b is not None:
                    kids.append(b)
                elif sub:
                    kids.extend(sub)
        kids = [k for k in kids if k is not None]
        if not kids:
            return None
        if len(kids) == 1 and kids[0].level >= mg.level:
            return kids[0]
        return Group(level=mg.level, first=kids[0].first, last=kids[-1].last, children=kids)

    g = build(master, ords)
    return g
