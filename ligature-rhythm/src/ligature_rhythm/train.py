"""Tuning the model's weights on edition-based encodings.

Gold standard
    Each CANDR note is aligned by pitch with the edition's encoding of the same clausula, which gives
    the edition's value for the note and the rest after each stroke. Notes the alignment cannot
    place (editorial pitch variants) stay unlabelled. The mode of each gold ordo is the one the
    theorists' rules find for the edition's values; each voice's home mode and ordo-ending style
    are the majority over its ordines.

Training
    Each voice is cut at the strokes where CANDR's synchronisation agrees with the edition. Between
    two such points the time is known, so each stretch is a small problem: read its notes from the
    edition's state at its start so that it ends at the edition's time. (The tenor is also trained
    once unsegmented, as it is read when it leads.) Starting from the theory prior, the weights are
    fitted to these stretches by an averaged passive-aggressive (PA-I) structured perceptron; the
    predicted structure includes the voice's home mode and ending style.

Evaluation
    ``cross_validate`` refits the model once per held-out group of pieces, in parallel.
"""
from __future__ import annotations

import logging
import random
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from typing import Optional

from .candr import notes_of
from .decoder import allowed_rests, allowed_values, decode
from .evaluate import Benchmark, edition_events
from .features import OLEN_MAX, RESTS, VALUES, Model, theory_weights
from .items import TENOR, UPPER, voice_items
from .realise import homorhythm, line_of, ordo_starts, read_pair, synch_targets

log = logging.getLogger(__name__)
C_PA = 0.01         # small steps keep the weights near the theory prior (generalises better)
EPOCHS = 8
STEPS = 'cdefgab'


# --------------------------------------------------------------------------- gold standard
def _nw_align(A, B) -> list:
    """global alignment with free end gaps; substitutions allowed (editorial pitch variants)"""
    n, m = len(A), len(B)
    H = [[0.0] * (m + 1) for _ in range(n + 1)]
    P = [[''] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        P[i][0] = 'u'
    for j in range(1, m + 1):
        P[0][j] = 'l'
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            H[i][j], P[i][j] = max((H[i - 1][j - 1] + (2 if A[i - 1] == B[j - 1] else -1.2), 'd'),
                                   (H[i - 1][j] - 1.5, 'u'), (H[i][j - 1] - 1.5, 'l'))
    _, i, j = max([(H[n][j], n, j) for j in range(m + 1)] + [(H[i][m], i, m) for i in range(n + 1)])
    pairs = []
    while i > 0 and j > 0:
        p = P[i][j]
        if p == 'd':
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif p == 'u':
            i -= 1
        else:
            j -= 1
    return pairs[::-1]


def gold_values(items, edition) -> dict:
    """{item: the edition's value (note) or rest (stroke)} where the edition fixes it"""
    X = []
    for k, it in enumerate(items):
        if it.is_note:
            X.append((k, False, it.note.pname.upper()))
            if it.note.plica:
                i = STEPS.index(it.note.pname) + (1 if it.note.plica == 'up' else -1)
                X.append((k, True, STEPS[i % 7].upper()))
    G = [e for e in edition if e[2] is not None]
    pairs = dict(_nw_align([x[2] for x in X], [g[2][0] for g in G]))
    on, dur = {}, {}
    for xi, (k, pl, _) in enumerate(X):
        j = pairs.get(xi)
        if not pl:
            if j is not None:
                on[k], dur[k] = G[j][0], G[j][1]
        elif k in dur and j is not None and G[j][0] == on[k] + dur[k]:
            dur[k] += G[j][1]
        elif not (k in dur and j is None):
            dur.pop(k, None)
    fixed = {}
    notes = [k for k, it in enumerate(items) if it.is_note]
    for a, b in zip(notes, notes[1:]):
        if a in dur and b in on:
            gap = on[b] - (on[a] + dur[a])
            between = [k for k in range(a + 1, b) if not items[k].is_note]
            if gap == 0 and not between:
                fixed[a] = dur[a]
            elif between and gap >= 0 and gap in RESTS:
                fixed[a] = dur[a]
                fixed[between[0]] = gap
                for s in between[1:]:
                    fixed[s] = 0
    if notes and notes[-1] in dur:
        fixed[notes[-1]] = dur[notes[-1]]
    return fixed


def gold_style(items, fixed) -> str:
    c = Counter()
    for k, it in enumerate(items):
        if not it.is_note and not it.short and k in fixed and (k - 1) in fixed and items[k - 1].is_note:
            c[{(6, 6): 'P', (4, 2): 'I', (2, 4): 'B'}.get((fixed[k - 1], fixed[k]))] += 1
    c.pop(None, None)
    return c.most_common(1)[0][0] if c else 'P'


def fifth_mode_ordines(items, fixed) -> dict:
    """{tenor note: 5} for ordines the edition reads in the fifth mode: every labelled note a
    perfect or duplex long, except that the last may be a long before a breve rest (how editions
    such as Payne's close fifth-mode ordines). The theorists' prior alone reads that close as
    first mode, which mislabels whole fifth-mode tenors."""
    ordines, cur = [], []
    for k, it in enumerate(items):
        if it.is_note:
            cur.append(k)
        elif cur:
            ordines.append(cur)
            cur = []
    if cur:
        ordines.append(cur)
    out = {}
    for o in ordines:
        v = [fixed[k] for k in o if k in fixed]
        if v and all(x in (6, 12) for x in v[:-1]) and v[-1] in ((4, 6, 12) if len(v) > 1 else (6, 12)):
            last = o[-1]
            if v[-1] == 4 and fixed.get(last + 1) != 2:
                continue
            out.update({k: 5 for k in o})
    return out


@dataclass
class Example:
    piece: str
    ui: list
    ti: list
    fu: dict
    ft: dict
    mu: dict = field(default_factory=dict)
    mt: dict = field(default_factory=dict)
    su: str = 'P'
    st: str = 'P'
    hu: int = 1
    ht: int = 5


def build_example(piece: str, bench: Benchmark) -> Example:
    c = bench.clausula_for(piece)
    ui, ti = voice_items(c.upper, UPPER), voice_items(c.tenor, TENOR)
    ed = bench.edition(piece)
    fu, ft = gold_values(ui, edition_events(ed, 0)), gold_values(ti, edition_events(ed, 1))
    fu = {k: x for k, x in fu.items() if (x in allowed_rests(UPPER) if not ui[k].is_note else x in allowed_values(UPPER, ui[k]))}
    ft = {k: x for k, x in ft.items() if (x in allowed_rests(TENOR) if not ti[k].is_note else x in allowed_values(TENOR, ti[k]))}
    su, st = gold_style(ui, fu), gold_style(ti, ft)
    th = Model.theory()
    gt = decode(ti, TENOR, th, fixed=ft, style=st)
    gu = decode(ui, UPPER, th, fixed=fu, style=su, targets=synch_targets(ti, gt.values, ui, True))
    mt = {k: m for k, m in enumerate(gt.modes) if ti[k].is_note}
    mt.update(fifth_mode_ordines(ti, ft))
    mu = {k: m for k, m in enumerate(gu.modes) if ui[k].is_note}
    # home modes are voted by the notes the edition labels: a CANDR clausula often runs on past
    # the edited section, and its unlabelled notes only carry the prior's guess
    vote = lambda modes, fixed: Counter(m for k, m in modes.items() if k in fixed) or Counter(modes.values())
    hu = 2 if su == 'B' else vote(mu, fu).most_common(1)[0][0]
    ht = vote(mt, ft).most_common(1)[0][0]
    return Example(piece, ui, ti, fu, ft, mu, mt, su, st, hu, ht)


# --------------------------------------------------------------------------- training stretches
@dataclass
class Stretch:
    items: list
    v: str
    fixed: dict
    modes: dict
    targets: dict
    style: str
    home: int
    init: Optional[tuple] = None
    homo: dict = field(default_factory=dict)
    line: Optional[dict] = None
    starts: Optional[set] = None


def _states_along(items, v, reading) -> list:
    out, t, o, prev, po = [], 0, 0, 0, 0
    for k, it in enumerate(items):
        out.append((t, o, prev, reading.modes[k], po))
        val = reading.values[k]
        if it.is_note:
            t += val
            prev = val
        else:
            if v == TENOR and not it.short:
                po = min(t + val - o, OLEN_MAX)
            t += val
            o = t
    return out


def _cut(items, v, gold, targets, fixed, modes, style, home, homo=None, line=None, starts=None) -> list:
    st = _states_along(items, v, gold)
    out, start = [], 0
    for b in sorted(targets) + [len(items) - 1]:
        if b < start:
            continue
        sh = lambda d: {k - start: x for k, x in (d or {}).items() if start <= k <= b}
        out.append(Stretch(items[start:b + 1], v, sh(fixed), sh(modes),
                           {b - start: targets[b]} if b in targets else {}, style, home,
                           None if start == 0 else st[start], sh(homo), line, starts))
        start = b + 1
    return [s for s in out if s.fixed]


def _consistent(items, v, model, targets, fixed, modes, style) -> dict:
    g = decode(items, v, model, targets=targets, fixed=fixed, modes_fixed=modes, style=style)
    return {k: x for k, x in targets.items() if k not in g.dropped}


def stretches(ex: Example) -> list:
    th = Model.theory()
    ui, ti = ex.ui, ex.ti
    gt = decode(ti, TENOR, th, fixed=ex.ft, modes_fixed=ex.mt, style=ex.st)
    tt = _consistent(ui, UPPER, th, synch_targets(ti, gt.values, ui, True), ex.fu, ex.mu, ex.su)
    gu = decode(ui, UPPER, th, targets=tt, fixed=ex.fu, modes_fixed=ex.mu, style=ex.su)
    ut = _consistent(ti, TENOR, th, synch_targets(ui, gu.values, ti, False), ex.ft, ex.mt, ex.st)
    gt = decode(ti, TENOR, th, targets=ut, fixed=ex.ft, modes_fixed=ex.mt, style=ex.st)
    whole = Stretch(ti, TENOR, ex.ft, ex.mt, {}, ex.st, ex.ht)
    return ([whole] + _cut(ti, TENOR, gt, ut, ex.ft, ex.mt, ex.st, ex.ht)
            + _cut(ui, UPPER, gu, tt, ex.fu, ex.mu, ex.su, ex.hu, homorhythm(ui, ti, tt, gt.values),
                   line_of(ti, gt.values), ordo_starts(ti, gt.values)))


# --------------------------------------------------------------------------- fitting
def _errors(reading, fixed) -> int:
    return sum(reading.values[k] != x for k, x in fixed.items())


def fit(examples, epochs: int = EPOCHS, seed: int = 0, c_pa: float = C_PA) -> Model:
    """averaged PA-I structured perceptron over the training stretches"""
    segs = [s for ex in examples for s in stretches(ex)]
    model = Model.theory()
    acc = {}
    c = 1
    rnd = random.Random(seed)
    for ep in range(epochs):
        rnd.shuffle(segs)
        err = 0
        for s in segs:
            kw = dict(targets=s.targets, homo=s.homo, init=s.init, line=s.line, starts=s.starts,
                      with_features=True)
            try:
                pred = decode(s.items, s.v, model, **kw)
                gold = decode(s.items, s.v, model, fixed=s.fixed, modes_fixed=s.modes, style=s.style,
                              home=s.home, **kw)
            except ValueError:
                continue
            loss = _errors(pred, s.fixed) + (pred.home != s.home) + (pred.style != s.style)
            if loss:
                err += loss
                delta = {k: gold.features.get(k, 0) - pred.features.get(k, 0)
                         for k in set(gold.features) | set(pred.features)}
                delta = {k: x for k, x in delta.items() if x}
                if delta:
                    margin = sum(model.w.get(k, 0.0) * x for k, x in delta.items())
                    tau = min(c_pa, max(0.0, (loss - margin) / sum(x * x for x in delta.values())))
                    model.update(delta, tau)
                    for k, x in delta.items():
                        acc[k] = acc.get(k, 0.0) + c * tau * x
            c += 1
        log.info('epoch %d: %d wrong decisions in %d stretches', ep, err, len(segs))
    return Model({k: x - acc.get(k, 0.0) / c for k, x in model.w.items()})


def value_accuracy(examples, model: Model) -> list:
    """per piece: share of labelled note values and rests the joint reading gets right"""
    rows = []
    for ex in examples:
        tr, ur, how = read_pair(ex.ui, ex.ti, model)
        row = dict(piece=ex.piece, lead=how)
        for name, items, fixed, r in (('upper', ex.ui, ex.fu, ur), ('tenor', ex.ti, ex.ft, tr)):
            notes = [k for k in fixed if items[k].is_note]
            row[name] = sum(r.values[k] == fixed[k] for k in notes) / max(1, len(notes))
            row[f'{name}_n'] = len(notes)
        rows.append(row)
    return rows


def _example(args):
    piece, bench = args
    try:
        return build_example(piece, bench)
    except Exception as e:                      # a piece the reader cannot label is left out
        log.warning('%s: no training example (%s)', piece, e)
        return None


def _fold(args):
    bench, held_out, epochs, c_pa, examples = args
    if examples is None:
        examples = {p: build_example(p, bench) for p in bench.pieces}
    excl = set(bench.spec.get('exclude_from_training', []))
    train = [ex for p, ex in examples.items() if ex is not None and p not in held_out and p not in excl]
    test = [examples[p] for p in held_out if examples.get(p) is not None]
    model = fit(train, epochs=epochs, c_pa=c_pa)
    rows = value_accuracy(test, model)
    df = bench.evaluate(model, [ex.piece for ex in test])
    for r in rows:
        r.update(df.loc[r['piece']].to_dict())
    return rows


def kfold_groups(groups: list, k: int, seed: int = 0) -> list:
    """merge groups into k folds of similar size (groups are never split)"""
    rnd = random.Random(seed)
    groups = list(groups)
    rnd.shuffle(groups)
    folds = [[] for _ in range(k)]
    for g in sorted(groups, key=len, reverse=True):
        min(folds, key=len).extend(g)
    return [f for f in folds if f]


def cross_validate(bench: Benchmark, groups: Optional[list] = None, epochs: int = EPOCHS,
                   workers: Optional[int] = None, c_pa: float = C_PA, k: Optional[int] = None,
                   examples: Optional[dict] = None):
    """Held-out estimate, folds run in parallel. Pieces that are the same clausula (or share
    material) should be in one group (spec key "groups"). Leave-one-group-out by default; with
    ``k``, the groups are merged into k folds (for benchmarks with many pieces). Examples are built
    once, in parallel, and shared by the folds."""
    import pandas as pd
    groups = groups or bench.spec.get('groups') or [[p] for p in bench.pieces]
    if k:
        groups = kfold_groups(groups, k)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        if examples is None:
            examples = dict(zip(bench.pieces, pool.map(_example, [(p, bench) for p in bench.pieces])))
        results = list(pool.map(_fold, [(bench, g, epochs, c_pa, examples) for g in groups]))
    return pd.DataFrame([r for rows in results for r in rows]).set_index('piece')


def fit_benchmark(bench: Benchmark, epochs: int = EPOCHS, c_pa: float = C_PA) -> Model:
    ex = [build_example(p, bench) for p in bench.pieces if p not in bench.spec.get('exclude_from_training', [])]
    return fit(ex, epochs=epochs, c_pa=c_pa)
