"""Features and weights of the rhythm model.

Every decision the reader makes is scored by a sum of weights of *features*: small tuples such as
``('grid', 'up', 1, 4, 2)`` = "upper voice, mode 1, a breve starting at position 4 of the
perfection". The weights are stored as a dict {feature tuple: weight} (``weights.json``), and for
decoding they are compiled into dense numpy arrays, one per feature template (``Tensors``), so that
scoring a whole beam of states is array indexing.

Units: one sixteenth = 1. B (brevis) = 2, L (longa) = 4, L. (perfect long) = 6 = one perfection =
one 3/8 bar, duplex long = 12.
"""
from __future__ import annotations

import json
from collections import Counter
from importlib import resources
from pathlib import Path
from typing import Optional

import numpy as np

VALUES = (2, 4, 6, 12, 18, 24)          # note values
RESTS = (0, 2, 4, 6, 8, 12)             # rests after a stroke
MODES = (1, 2, 3, 5)                    # rhythmic modes
STYLES = ('P', 'I', 'B')                # ordo endings: L. + L. rest, L + B rest, B + L rest
STYLE_END = {'P': (6, 6), 'I': (4, 2), 'B': (2, 4)}
HOMES = {'te': (5, 1, 2), 'up': (1, 2)}
HOME_PEN = 1.0                          # default cost per note read outside the home mode
OLEN_MAX = 48

VOICES = ('up', 'te')
_HEADS = ('L', 'C')
_POS_IN_LIG = ('1.0', '2.0', '2.1', '3.0', '3.1', '3.2', 'n.0', 'n.m', 'n.p', 'n.z')
CTX = ['S', 'S+pl'] + [h + p + pl for h in _HEADS for p in _POS_IN_LIG for pl in ('', '+pl')] + ['-']
NEXT = ('end', 'S', 'lig', 'in')
GROUPS = (1, 2, 3, 4)
GROUP_TUPLES = [(g,) for g in GROUPS] + [(g, h) for g in GROUPS for h in GROUPS]
INTERVALS = ('1', '2', '3', '4', '5', 'rest')    # unison/octave, 2nd/7th, 3rd/6th, 4th, 5th


def pos_of(mode: int, t: int) -> int:
    """position of time t in the mode's metrical cycle (12 in the third mode, else 6)"""
    return t % 12 if mode == 3 else t % 6


def interval_class(step: int, other: Optional[int]) -> str:
    if other is None:
        return 'rest'
    return ('1', '2', '3', '4', '5', '3', '2')[abs(step - other) % 7]


# --------------------------------------------------------------------------- feature functions
def note_features(v, m, t, prev, d, it, line=None) -> list:
    """features of giving note item `it` the value d, at time t, after value `prev`, in mode m.
    `line`: the other voice (time -> step number), for the consonance features."""
    c = it.ctx
    f = []
    if it.osig:
        s = it.osig
        f += [('osig1', v, m, s[0], s[1]), ('osig2', v, m, s[2]), ('osig3', v, m, s[3])]
    if line is not None:
        ic = interval_class(it.note.step, line.get(t))
        f += [('cons', v, m, pos_of(m, t), ic), ('consd', v, m, ic, d)]
    return f + [('grid', v, m, pos_of(m, t), d),
                ('mctx', v, m, c, d),
                ('prev', v, m, prev, d),
                ('nxt', v, m, c, it.next, d)]


def stroke_features(v, m, m2, t, r, prev, it, olen, po=0, style=None, starts=None) -> list:
    """features of a rest r at stroke item `it` (time t, ordo so far `olen` long), moving to mode m2.
    `starts`: the other voice's ordo starting times."""
    L = min(olen + r, OLEN_MAX)
    f = []
    if style and not it.short:
        f.append(('stymatch', v, STYLE_END[style] == (prev, r)))
    if starts is not None and not it.short:
        f.append(('coinc', v, (t + r) in starts))
    f += [('rctx', v, m, it.after, r),
          ('rest', v, m, pos_of(m, t), r),
          ('rshort', v, it.short, r),
          ('ostart', v, m2, pos_of(m2, t + r)),
          ('olen', v, m, L)]
    if v == 'te' and po and not it.short:
        f.append(('osame', v, L == po))
    if m2 != m:
        f.append(('mchg', v, m, m2))
    return f


def path_features(items, v, values, modes, init=None, style=None, home=None, line=None, starts=None,
                  final_mode=None) -> Counter:
    """feature counts of a complete reading (used in training). `final_mode`: the mode chosen after
    a closing stroke (default: unchanged)"""
    c = Counter()
    if init is not None:
        t, o, prev, _, po = init
    else:
        t, o, prev, po = 0, 0, 0, 0
        c[('m0', v, modes[0] if items else 1)] += 1
    c[('home0', v, home)] += 1
    c[('sty0', v, style)] += 1
    for k, it in enumerate(items):
        m = modes[k]
        if it.is_note:
            d = values[k]
            c.update(note_features(v, m, t, prev, d, it, line))
            if home is not None and m != home:
                c[('offhome', v)] += 1
            t += d
            prev = d
        else:
            r = values[k]
            m2 = modes[k + 1] if k + 1 < len(items) else (final_mode or m)
            c.update(stroke_features(v, m, m2, t, r, prev, it, t - o, po, style, starts))
            if v == 'te' and not it.short:
                po = min(t + r - o, OLEN_MAX)
            t += r
            o = t
    return c


# --------------------------------------------------------------------------- theory prior
def theory_weights() -> dict:
    """Initial weights from the theorists' readings (Garlandia, Anonymous IV); higher is better."""
    w = {}
    grid = {
        1: {(0, 6): 0, (0, 4): 0, (4, 2): 0, (0, 12): -1.0, (0, 2): -1.2, (2, 2): -1.2,
            (2, 4): -2.5, (4, 4): -3, (4, 6): -3, (0, 18): -2.0, (0, 24): -2.5},
        2: {(0, 2): 0, (2, 4): 0, (0, 6): -0.6, (0, 12): -1.2, (2, 2): -1.2, (4, 2): -1.2, (0, 4): -2.0, (4, 4): -2.5},
        3: {(0, 6): 0, (6, 2): 0, (8, 4): 0, (0, 12): -1.0, (6, 6): -0.8, (0, 4): -1.5, (4, 2): -1.5, (6, 4): -2,
            (8, 2): -1.5, (10, 2): -1.5},
        5: {(0, 6): 0, (0, 12): -0.3, (0, 18): -1.5, (0, 4): -2.0, (4, 2): -2.0, (0, 24): -2.5},
    }
    shape = {(1, 2): 'BL', (1, 3): 'LBL', (2, 2): 'BL', (2, 3): 'BLP', (3, 2): 'BL', (3, 3): 'BLP',
             (5, 2): 'PP', (5, 3): 'PPP'}
    ok = {'B': (2,), 'L': (4, 6), 'P': (6,)}
    for v in VOICES:
        for m in MODES:
            for p in range(0, 12 if m == 3 else 6, 2):
                for d in VALUES:
                    w[('grid', v, m, p, d)] = grid[m].get((p, d), -6.0)
        for (m, k), s in shape.items():
            for i, ch in enumerate(s):
                for d in VALUES:
                    for pl in ('', '+pl'):
                        w[('mctx', v, m, f'L{k}.{i}{pl}', d)] = 0 if d in ok[ch] else -1.0
        for m in MODES:
            for d in VALUES:
                for c in ('C3.0', 'C3.1', 'Cn.0', 'Cn.m', 'Cn.p'):
                    w[('mctx', v, m, c, d)] = 0 if d == 2 else -1.5
                for c in ('Cn.z', 'C3.2'):
                    w[('mctx', v, m, c, d)] = 0 if d in (4, 6) else -1.0
                for c in ('Ln.0', 'Ln.m', 'Ln.p'):
                    w[('mctx', v, m, c, d)] = 0 if d in (2, 4) else -1.0
                if v == 'up':
                    w[('mctx', v, m, 'S', d)] = ({6: -0.2, 4: 0, 2: 0, 12: -1.0} if m in (2, 3) else
                                                  {6: 0, 4: -0.3, 2: -0.6, 12: -0.8}).get(d, -2)
                else:
                    w[('mctx', v, m, 'S', d)] = ({6: 0, 4: 0, 2: -0.3, 12: -0.8} if m in (1, 2) else
                                                  {6: 0, 12: -0.5, 18: -1.2, 4: -0.8, 2: -1.5}).get(d, -2)
            for p in range(0, 12, 2):
                base = {0: {6: 0, 12: -1.0, 0: -1.0}, 4: {2: -0.3, 8: -0.8}, 2: {4: -0.3, 0: -1.0}}.get(p % 6, {})
                for r in RESTS:
                    w[('rest', v, m, p, r)] = base.get(r, -3.0)
                w[('ostart', v, m, p)] = 0 if p % 6 == 0 else -2.5
        for r in RESTS:
            w[('rshort', v, True, r)] = 0.8 if r == 0 else 0
        w[('osame', v, True)] = 1.0
        w[('stymatch', v, True)] = 1.0
        w[('coinc', v, True)] = 0.5
        w[('offhome', v)] = -HOME_PEN
        for g0 in GROUPS:
            for g1 in GROUPS:
                w[('osig1', v, 1, g0, g1)] = 0.5 if g0 == 3 else 0
                w[('osig1', v, 2, g0, g1)] = 0.5 if g1 == 3 and g0 != 3 else 0
                w[('osig1', v, 5, g0, g1)] = 0.3 if g0 == g1 and g0 in (1, 3) else 0
                w[('osig2', v, 3, (g0, g1))] = 0.5 if (g0, g1) == (1, 3) else 0
        for m in MODES:
            for m2 in MODES:
                w[('mchg', v, m, m2)] = -1.0
            w[('m0', v, m)] = 0 if (m == 1 and v == 'up') or (m == 5 and v == 'te') else -1.0
    return w


# --------------------------------------------------------------------------- storage
def _tup(x):
    return tuple(_tup(y) for y in x) if isinstance(x, list) else x


PACKAGED = {'default': 'weights.json', 'dominus': 'weights_dominus.json'}


def load_weights(path=None) -> dict:
    """{feature: weight} from a weights file, or one of the packaged sets:
    'default' (tuned conservatively on the Dominus clausulae; for new repertory) or
    'dominus' (fitted closely to the Dominus editions; best for those pieces, generalises worse)"""
    if path is None or str(path) in PACKAGED:
        name = PACKAGED[str(path) if path is not None else 'default']
        raw = json.loads(resources.files('ligature_rhythm').joinpath('data/' + name).read_text())
    else:
        raw = json.loads(Path(path).read_text())
    return {_tup(json.loads(k)): v for k, v in raw.items()}


def save_weights(w: dict, path: Path) -> None:
    Path(path).write_text(json.dumps({json.dumps(list(k)): round(v, 4) for k, v in w.items() if abs(v) > 1e-9},
                                     indent=0))


# --------------------------------------------------------------------------- dense form
class Tensors:
    """The weights of one voice as dense arrays (index conventions below)."""
    MI = {m: i for i, m in enumerate(MODES)}
    DI = {d: i for i, d in enumerate(VALUES)}
    PI = {p: i for i, p in enumerate((0,) + VALUES)}          # previous value (0 = none)
    RI = {r: i for i, r in enumerate(RESTS)}
    CI = {c: i for i, c in enumerate(CTX)}
    NI = {n: i for i, n in enumerate(NEXT)}
    GI = {g: i for i, g in enumerate(GROUPS)}
    TI = {t: i for i, t in enumerate(GROUP_TUPLES)}
    II = {x: i for i, x in enumerate(INTERVALS)}
    HI = {h: i for i, h in enumerate((None,) + MODES)}
    SI = {s: i for i, s in enumerate((None,) + STYLES)}

    def __init__(self, w: dict, v: str):
        z = np.zeros
        nm, nd, npv, nr, nc = len(MODES), len(VALUES), len(self.PI), len(RESTS), len(CTX)
        self.grid, self.mctx, self.prev = z((nm, 12, nd)), z((nm, nc, nd)), z((nm, npv, nd))
        self.nxt = z((nm, nc, len(NEXT), nd))
        self.osig1, self.osig2, self.osig3 = z((nm, 4, 4)), z((nm, len(GROUP_TUPLES))), z((nm, len(GROUP_TUPLES)))
        self.cons, self.consd = z((nm, 12, len(INTERVALS))), z((nm, len(INTERVALS), nd))
        self.rest, self.rctx, self.rshort = z((nm, 12, nr)), z((nm, nc, nr)), z((2, nr))
        self.ostart, self.olen, self.mchg = z((nm, 12)), z((nm, OLEN_MAX + 1)), z((nm, nm))
        self.osame, self.stymatch, self.coinc = z(2), z(2), z(2)
        self.m0, self.home0, self.sty0 = z(nm), z(len(self.HI)), z(len(self.SI))
        self.offhome = w.get(('offhome', v), -HOME_PEN)
        M, D, P, R, C = self.MI, self.DI, self.PI, self.RI, self.CI
        for k, x in w.items():
            if k[1] != v:
                continue
            name, a = k[0], k[2:]
            try:
                if name == 'grid':
                    self.grid[M[a[0]], a[1], D[a[2]]] = x
                elif name == 'mctx':
                    self.mctx[M[a[0]], C[a[1]], D[a[2]]] = x
                elif name == 'prev':
                    self.prev[M[a[0]], P[a[1]], D[a[2]]] = x
                elif name == 'nxt':
                    self.nxt[M[a[0]], C[a[1]], self.NI[a[2]], D[a[3]]] = x
                elif name == 'osig1':
                    self.osig1[M[a[0]], self.GI[a[1]], self.GI[a[2]]] = x
                elif name == 'osig2':
                    self.osig2[M[a[0]], self.TI[tuple(a[1])]] = x
                elif name == 'osig3':
                    self.osig3[M[a[0]], self.TI[tuple(a[1])]] = x
                elif name == 'cons':
                    self.cons[M[a[0]], a[1], self.II[a[2]]] = x
                elif name == 'consd':
                    self.consd[M[a[0]], self.II[a[1]], D[a[2]]] = x
                elif name == 'rest':
                    self.rest[M[a[0]], a[1], R[a[2]]] = x
                elif name == 'rctx':
                    self.rctx[M[a[0]], C[a[1]], R[a[2]]] = x
                elif name == 'rshort':
                    self.rshort[int(a[0]), R[a[1]]] = x
                elif name == 'ostart':
                    self.ostart[M[a[0]], a[1]] = x
                elif name == 'olen':
                    self.olen[M[a[0]], a[1]] = x
                elif name == 'mchg':
                    self.mchg[M[a[0]], M[a[1]]] = x
                elif name == 'osame':
                    self.osame[int(a[0])] = x
                elif name == 'stymatch':
                    self.stymatch[int(a[0])] = x
                elif name == 'coinc':
                    self.coinc[int(a[0])] = x
                elif name == 'm0':
                    self.m0[M[a[0]]] = x
                elif name == 'home0':
                    self.home0[self.HI[a[0]]] = x
                elif name == 'sty0':
                    self.sty0[self.SI[a[0]]] = x
            except (KeyError, IndexError):
                continue                    # a feature this model version does not use
        np.fill_diagonal(self.mchg, 0.0)    # mchg only fires on a change of mode


class Model:
    """Weights plus their dense form (rebuilt when the weights change)."""

    def __init__(self, weights: Optional[dict] = None):
        self.w = dict(load_weights() if weights is None else weights)
        self._t = {}

    def tensors(self, v: str) -> Tensors:
        if v not in self._t:
            self._t[v] = Tensors(self.w, v)
        return self._t[v]

    def update(self, delta: dict, scale: float) -> None:
        for k, x in delta.items():
            self.w[k] = self.w.get(k, 0.0) + scale * x
        self._t.clear()

    @classmethod
    def theory(cls) -> 'Model':
        return cls(theory_weights())
