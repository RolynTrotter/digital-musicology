"""Viterbi/beam search for the reading of one voice, vectorised with numpy.

A *state* is (t, o, prev, mode, po): the time, the start of the current ordo, the previous note
value, the current mode, and (tenor only) the length of the previous ordo. Each note item extends
every state by each allowed value; each stroke item by each allowed rest and next mode. States with
the same key are merged (best score kept) and the beam keeps the best ``beam`` of them.

Constraints:
* ``targets`` {stroke item: time}: after that stroke the next ordo must start at that time (CANDR's
  synchronisation with the other voice). While any state can still meet the next target, states that
  cannot are pruned; if none can, the target is dropped at cost ``drop`` (default SYNCH_DROP).
* ``end``: the voice's last note should end at this time (cost END_APART otherwise).
* ``fixed`` / ``modes_fixed`` {item: value / mode}: force a reading (used in training).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .features import (HOMES, MODES, OLEN_MAX, RESTS, STYLE_END, STYLES, VALUES, Model, Tensors,
                       path_features)

SYNCH_DROP = 100.0     # cost of giving up a synchronisation that no reading can keep
END_APART = 8.0        # cost of the voice not ending with the other voice
HOMO_BONUS = 1.5       # reward for copying the tenor's value in note-against-note passages
BEAM = 400
T_MAX = 1 << 13

_MODES = np.array(MODES)
_VALUES = np.array(VALUES)
_PREVS = np.array((0,) + VALUES)
_RESTS = np.array(RESTS)
_M3 = MODES.index(3)


@dataclass
class Reading:
    score: float
    values: list                   # value (note) or rest (stroke) per item
    modes: list                    # mode per item (for a stroke: the mode before it)
    dropped: list = field(default_factory=list)   # stroke items whose target was given up
    style: Optional[str] = None
    home: Optional[int] = None
    end_time: int = 0
    final_mode: Optional[int] = None  # mode after a closing stroke
    features: Optional[object] = None


def allowed_values(v: str, it) -> tuple:
    """values a note may take. In discant the upper voice moves in B, L and L.; only its final note
    may be longer."""
    if v == 'te':
        return VALUES if it.lig == 0 else (2, 4, 6, 12)
    if it.final:
        return (2, 4, 6, 12, 18)
    if it.ltype == 'currentes' and it.i < it.lig - 1:
        return (2, 4)
    return (2, 4, 6)


def allowed_rests(v: str) -> tuple:
    return RESTS if v == 'te' else (0, 2, 4, 6)


def _pos(mi, t):
    return np.where(mi == _M3, t % 12, t % 6)


def _key(t, o, pv, mi, po):
    return (((t.astype(np.int64) * T_MAX + o) * 8 + pv) * 4 + mi) * 64 + po


class _Beam:
    __slots__ = ('t', 'o', 'pv', 'mi', 'po', 'score', 'src', 'val', 'drop')

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    def __len__(self):
        return len(self.t)

    def take(self, idx):
        return _Beam(**{k: getattr(self, k)[idx] for k in self.__slots__})


def _merge_and_prune(b: _Beam, beam: int) -> _Beam:
    key = _key(b.t, b.o, b.pv, b.mi, b.po)
    order = np.lexsort((-b.score, key))
    first = np.ones(len(order), bool)
    first[1:] = key[order][1:] != key[order][:-1]
    b = b.take(order[first])
    if len(b) > beam:
        b = b.take(np.argpartition(-b.score, beam)[:beam])
    return b


def decode_one(items, v: str, model: Model, *, style=None, home=None, targets=None, fixed=None,
               modes_fixed=None, homo=None, line=None, starts=None, end=None, init=None,
               drop=None, beam=BEAM, with_features=False) -> Reading:
    """Best reading of one voice for a given ending style and home mode."""
    T: Tensors = model.tensors(v)
    targets, fixed, modes_fixed, homo = targets or {}, fixed or {}, modes_fixed or {}, homo or {}
    drop_cost = SYNCH_DROP if drop is None else drop
    tenor = v == 'te'
    hi = MODES.index(home) if home is not None else -1
    base = T.home0[T.HI[home]] + T.sty0[T.SI[style]]
    line_arr = None
    if line is not None:
        line_arr = np.full(T_MAX, -1000, np.int64)
        for k, x in line.items():
            if k < T_MAX:
                line_arr[k] = x
    starts_arr = None
    if starts is not None:
        starts_arr = np.zeros(T_MAX, bool)
        starts_arr[[s for s in starts if s < T_MAX]] = True
    if style:
        end_pair = STYLE_END[style]

    first_note = next((k for k, it in enumerate(items) if it.is_note), None)
    last_note = max((k for k, it in enumerate(items) if it.is_note), default=-1)
    if init is not None:
        t0, o0, p0, m0, po0 = init
        cur = _Beam(t=np.array([t0]), o=np.array([o0]), pv=np.array([T.PI[p0]]), mi=np.array([T.MI[m0]]),
                    po=np.array([po0]), score=np.array([base]), src=np.array([-1]), val=np.array([0]),
                    drop=np.array([False]))
    else:
        mf = modes_fixed.get(first_note)
        mis = np.array([T.MI[mf]]) if mf is not None else np.arange(len(MODES))
        n = len(mis)
        cur = _Beam(t=np.zeros(n, np.int64), o=np.zeros(n, np.int64), pv=np.zeros(n, np.int64), mi=mis,
                    po=np.zeros(n, np.int64), score=base + T.m0[mis], src=np.full(n, -1),
                    val=np.zeros(n, np.int64), drop=np.zeros(n, bool))
    # next target after each item, and how many notes lie before it (for pruning)
    nxt_tgt = [None] * len(items)
    pend = None
    for k in range(len(items) - 1, -1, -1):
        if k in targets:
            pend = (targets[k], 0)
        elif pend is not None and items[k].is_note:
            pend = (pend[0], pend[1] + 1)
        nxt_tgt[k] = pend
    maxv = max(VALUES) if tenor else 12

    history = []
    for k, it in enumerate(items):
        S = len(cur)
        if it.is_note:
            vals = np.array([fixed[k]] if k in fixed else allowed_values(v, it))
            di = np.array([T.DI[d] for d in vals])
            mi, t = cur.mi, cur.t
            pos = _pos(mi, t)
            c, nx = T.CI[it.ctx], T.NI[it.next]
            sc = (T.grid[mi, pos][:, di] + T.mctx[mi, c][:, di] + T.prev[mi, cur.pv][:, di]
                  + T.nxt[mi, c, nx][:, di])
            extra = np.zeros(S)
            if it.osig:
                s = it.osig
                extra += (T.osig1[mi, T.GI[s[0]], T.GI[s[1]]] + T.osig2[mi, T.TI[tuple(s[2])]]
                          + T.osig3[mi, T.TI[tuple(s[3])]])
            if line_arr is not None:
                other = line_arr[t]
                diff = np.abs(it.note.step - other) % 7
                ic = np.array([T.II[x] for x in ('1', '2', '3', '4', '5', '3', '2')])[diff]
                ic = np.where(other < -500, T.II['rest'], ic)
                extra += T.cons[mi, pos, ic]
                sc = sc + T.consd[mi, ic][:, di]
            if hi >= 0:
                extra += np.where(mi != hi, T.offhome, 0.0)
            if k in homo:
                sc = sc + np.where(vals == homo[k], HOMO_BONUS, 0.0)[None, :]
            sc = sc + extra[:, None] + cur.score[:, None]
            K = len(vals)
            nb = _Beam(t=(t[:, None] + vals[None, :]).ravel(), o=np.repeat(cur.o, K), pv=np.tile(di + 1, S),
                       mi=np.repeat(mi, K), po=np.repeat(cur.po, K), score=sc.ravel(),
                       src=np.repeat(np.arange(S), K), val=np.tile(vals, S), drop=np.zeros(S * K, bool))
            if k in modes_fixed:
                nb = nb.take(np.nonzero(nb.mi == T.MI[modes_fixed[k]])[0])
        else:
            rests = np.array([fixed[k]] if k in fixed else allowed_rests(v))
            ri = np.array([T.RI[r] for r in rests])
            mi, t = cur.mi, cur.t
            pos = _pos(mi, t)
            olen = t - cur.o
            nm, R = len(MODES), len(rests)
            # (S, R) parts
            sc = T.rest[mi, pos][:, ri] + T.rctx[mi, T.CI[it.after]][:, ri] + T.rshort[int(it.short), ri][None, :]
            L = np.minimum(olen[:, None] + rests[None, :], OLEN_MAX)
            sc = sc + T.olen[mi[:, None], L]
            if tenor and not it.short:
                sc = sc + np.where(cur.po[:, None] > 0, T.osame[(L == cur.po[:, None]).astype(int)], 0.0)
            prev_val = _PREVS[cur.pv]
            if style and not it.short:
                match = (prev_val[:, None] == end_pair[0]) & (rests[None, :] == end_pair[1])
                sc = sc + T.stymatch[match.astype(int)]
            tr = t[:, None] + rests[None, :]
            if starts_arr is not None and not it.short:
                sc = sc + T.coinc[starts_arr[np.minimum(tr, T_MAX - 1)].astype(int)]
            dropped = np.zeros((S, R), bool)
            if k in targets:
                dropped = tr != targets[k]
                sc = sc - np.where(dropped, drop_cost, 0.0)
            # (S, R, M2) with the next mode
            m2 = np.arange(nm)
            pos2 = np.where(m2[None, None, :] == _M3, tr[:, :, None] % 12, tr[:, :, None] % 6)
            full = (sc[:, :, None] + T.ostart[m2[None, None, :], pos2] + T.mchg[mi][:, None, :]
                    + cur.score[:, None, None])
            if tenor:
                npo = np.where(it.short, cur.po[:, None], np.minimum(tr - cur.o[:, None], OLEN_MAX))
            else:
                npo = np.zeros((S, R), np.int64)
            shape = (S, R, nm)
            nb = _Beam(t=np.broadcast_to(tr[:, :, None], shape).ravel(), o=np.broadcast_to(tr[:, :, None], shape).ravel(),
                       pv=np.broadcast_to(cur.pv[:, None, None], shape).ravel(),
                       mi=np.broadcast_to(m2[None, None, :], shape).ravel(),
                       po=np.broadcast_to(npo[:, :, None], shape).ravel(), score=full.ravel(),
                       src=np.broadcast_to(np.arange(S)[:, None, None], shape).ravel(),
                       val=np.broadcast_to(rests[None, :, None], shape).ravel(),
                       drop=np.broadcast_to(dropped[:, :, None], shape).ravel())
        if drop is None and k + 1 < len(items) and nxt_tgt[k + 1] is not None:
            Tg, n_left = nxt_tgt[k + 1]
            live = (nb.t + 2 * n_left <= Tg) & (Tg <= nb.t + maxv * n_left + 12 * (n_left + 1))
            if live.any():
                nb = nb.take(np.nonzero(live)[0])
        if end is not None and k == last_note:
            nb.score = nb.score - np.where(nb.t != end, END_APART, 0.0)
        if len(nb) == 0:
            raise ValueError(f'no reading at item {k}')
        nb = _merge_and_prune(nb, beam)
        history.append((nb, cur.mi))
        cur = nb

    j = int(np.argmax(cur.score))
    score = float(cur.score[j])
    final_mode = MODES[int(cur.mi[j])]
    values, modes, dropped = [0] * len(items), [0] * len(items), []
    for k in range(len(items) - 1, -1, -1):
        b, src_mi = history[k]
        values[k] = int(b.val[j])
        s = int(b.src[j])
        modes[k] = MODES[int(src_mi[s])]
        if b.drop[j]:
            dropped.append(k)
        j = s
    dropped.sort()
    end_time = (init[0] if init else 0) + sum(values[:last_note + 1])
    r = Reading(score, values, modes, dropped, style, home, end_time, final_mode)
    if with_features:
        r.features = path_features(items, v, values, modes, init=init, style=style, home=home,
                                   line=line, starts=starts, final_mode=final_mode)
    return r


def decode(items, v: str, model: Model, *, style='auto', home='auto', style_bonus=None, **kw) -> Reading:
    """Best reading of one voice, trying each ending style and home mode unless given."""
    styles = STYLES if style == 'auto' else (style,)
    if home == 'auto':
        homes = HOMES[v]
    elif isinstance(home, (tuple, list)):
        homes = tuple(home)
    else:
        homes = (home,)
    best = None
    for h in homes:
        for s in styles:
            try:
                r = decode_one(items, v, model, style=s, home=h, **kw)
            except ValueError:
                continue
            r.score += (style_bonus or {}).get(s, 0.0)
            if best is None or r.score > best.score:
                best = r
    if best is None:
        raise ValueError('no reading')
    return best
