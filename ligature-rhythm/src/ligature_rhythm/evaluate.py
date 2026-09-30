"""Comparing realised clausulae with edition-based encodings.

A *benchmark spec* (JSON) names the CANDR runs and, for each edition encoding, the run holding its
concordance::

    {"runs":   {"F": {"settings": [865, 866, ...], "incipit": "DCCACDCBCDAFA"}, ...},
     "pieces": {"3": {"edition": "Dominus3.xml", "run": "F"}, ...},
     "exclude_from_training": ["10"]}

Editions are MusicXML with the duplum as the first part and the tenor as the second, in 3/8.
Measures (notes matched to the edition by pitch letter):

* ``dur``    same value as the edition
* ``onset``  same onset after one global offset (strict: one misplaced rest shifts the rest)
* ``local``  same onset within the edition's ordo
* ``vert``   the duplum note sounds over the same tenor note as in the edition
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

from .candr import notes_of
from .features import Model
from .realise import realise
from .segment import split


# --------------------------------------------------------------------------- editions
def edition_events(path, part: int) -> list:
    """[(onset, duration, name or None)] in sixteenths, ties merged"""
    root = ET.parse(path).getroot()
    P = list(root.iter('part'))[part]
    t, div, ev = 0, 1, []
    for m in P.findall('measure'):
        for el in m:
            if el.tag == 'attributes' and el.findtext('divisions'):
                div = int(el.findtext('divisions'))
            elif el.tag == 'backup':
                t -= int(el.findtext('duration'))
            elif el.tag == 'forward':
                t += int(el.findtext('duration'))
            elif el.tag == 'note' and el.find('chord') is None:
                d = int(el.findtext('duration', '0'))
                q, on = 4 * d // div, 4 * t // div
                p = el.find('pitch')
                ties = [x.get('type') for x in el.findall('tie')]
                if p is None:
                    ev.append([on, q, None])
                else:
                    a = int(float(p.findtext('alter', '0')))
                    name = p.findtext('step') + ('b' if a == -1 else '#' if a == 1 else '')
                    if 'stop' in ties and ev and ev[-1][2] == name and ev[-1][0] + ev[-1][1] == on:
                        ev[-1][1] += q
                    else:
                        ev.append([on, q, name])
                t += d
    return [tuple(e) for e in ev]


def realised_events(events) -> list:
    return [(e.onset, e.duration, None if e.pitch is None else e.pitch[0] + ('b' if e.pitch[1] == -1 else ''))
            for e in events]


# --------------------------------------------------------------------------- alignment
def align(a, b) -> list:
    """align edition notes a with realised notes b by pitch letter (b may hold extra material at
    either end) -> [(i, j)] of matched pairs"""
    A = [x[2][0] for x in a]
    B = [x[2][0] for x in b]
    n, m = len(A), len(B)
    H = [[0.0] * (m + 1) for _ in range(n + 1)]
    P = [[''] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        H[i][0], P[i][0] = -i * 0.5, 'u'
    for j in range(1, m + 1):
        P[0][j] = 'l'
    for i in range(1, n + 1):
        Hi, Hp, Pi = H[i], H[i - 1], P[i]
        for j in range(1, m + 1):
            d = Hp[j - 1] + (2 if A[i - 1] == B[j - 1] else -1)
            u, l = Hp[j] - 1, Hi[j - 1] - 1
            if d >= u and d >= l:
                Hi[j], Pi[j] = d, 'd'
            elif u >= l:
                Hi[j], Pi[j] = u, 'u'
            else:
                Hi[j], Pi[j] = l, 'l'
    j, i, pairs = max(range(m + 1), key=lambda k: H[n][k]), n, []
    while i > 0 and j > 0:
        p = P[i][j]
        if p == 'd':
            if A[i - 1] == B[j - 1]:
                pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif p == 'u':
            i -= 1
        else:
            j -= 1
    return pairs[::-1]


def _sounding(ev, t):
    for on, d, p in ev:
        if p and on <= t < on + d:
            return p[0]
    return None


def compare(ed_up, ed_te, my_up, my_te) -> dict:
    """measures for one clausula (lists of (onset, duration, name))"""
    out = {}
    for name, g_all, m_all in (('dup', ed_up, my_up), ('ten', ed_te, my_te)):
        g = [e for e in g_all if e[2]]
        me = [e for e in m_all if e[2]]
        pr = align(g, me)
        if not pr:
            continue
        off = Counter(me[j][0] - g[i][0] for i, j in pr).most_common(1)[0][0]
        ordo, start, k, rest = [], None, -1, True
        for on, d, p in g_all:
            if p is None:
                rest = True
                continue
            if rest:
                k, start, rest = k + 1, on, False
            ordo.append(k)
        loc = {}
        for i, j in pr:
            loc.setdefault(ordo[i], me[j][0] - g[i][0])
        out[f'{name}_n'] = len(g)
        out[f'{name}_matched'] = len(pr) / len(g)
        out[f'{name}_dur'] = sum(g[i][1] == me[j][1] for i, j in pr) / len(pr)
        out[f'{name}_onset'] = sum(me[j][0] - off == g[i][0] for i, j in pr) / len(pr)
        out[f'{name}_local'] = sum(me[j][0] - loc[ordo[i]] == g[i][0] for i, j in pr) / len(pr)
        if name == 'dup':
            same = [_sounding(ed_te, g[i][0]) == _sounding(my_te, me[j][0]) for i, j in pr]
            out['vert'] = sum(same) / len(pr)
    return out


# --------------------------------------------------------------------------- benchmark
@dataclass
class Benchmark:
    spec: dict
    candr_dir: Path
    edition_dir: Path
    _cache: dict = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls, spec_path, candr_dir, edition_dir) -> 'Benchmark':
        return cls(json.loads(Path(spec_path).read_text()), Path(candr_dir), Path(edition_dir))

    @property
    def pieces(self) -> list:
        return list(self.spec['pieces'])

    def edition(self, piece) -> Path:
        return self.edition_dir / self.spec['pieces'][piece]['edition']

    def clausulae(self, run: str) -> tuple:
        if run not in self._cache:
            r = self.spec['runs'][run]
            paths = [self.candr_dir / f'setting_{i:04d}.mei' for i in r['settings']]
            kw = {k: r[k] for k in ('min_gap',) if k in r}
            self._cache[run] = tuple(split(paths, incipit=r.get('incipit'), **kw)[0])
        return self._cache[run]

    def clausula_for(self, piece):
        """the clausula of the piece's run whose upper voice covers most of the edition's duplum"""
        g = [e for e in edition_events(self.edition(piece), 0) if e[2]]
        best = None
        for c in self.clausulae(self.spec['pieces'][piece]['run']):
            me = [(0, 0, n.pname.upper()) for t in c.upper for n in notes_of(t)]
            pr = len(align(g, me))
            val = pr / len(g) + 0.05 * pr / max(1, len(me))
            if best is None or val > best[0]:
                best = (val, c)
        return best[1]

    def evaluate(self, model: Optional[Model] = None, pieces=None) -> pd.DataFrame:
        model = model or Model()
        rows = []
        for p in pieces or self.pieces:
            c = self.clausula_for(p)
            res = realise(c.upper, c.tenor, model)
            m = compare(edition_events(self.edition(p), 0), edition_events(self.edition(p), 1),
                        realised_events(res.upper), realised_events(res.tenor))
            rows.append(dict(piece=p, run=self.spec['pieces'][p]['run'], **m,
                             lead=res.info['lead'], synch_dropped=len(res.info['synch_dropped'])))
        return pd.DataFrame(rows).set_index('piece')
