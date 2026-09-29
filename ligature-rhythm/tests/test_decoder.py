"""The vectorised Viterbi must find the best-scoring reading (checked against exhaustive search)."""
import itertools
import random

import pytest

from ligature_rhythm.candr import upper_and_tenor
from ligature_rhythm.decoder import allowed_rests, allowed_values, decode, decode_one
from ligature_rhythm.features import MODES, Model, path_features, theory_weights
from ligature_rhythm.items import TENOR, UPPER, voice_items


def path_score(model, items, v, values, modes, style=None, home=None, final_mode=None):
    f = path_features(items, v, values, modes, style=style, home=home, final_mode=final_mode)
    s = sum(model.w.get(k, 0.0) * c for k, c in f.items() if k[0] != 'offhome')
    return s + f.get(('offhome', v), 0) * model.w.get(('offhome', v), -1.0)


def brute_force(model, items, v, style=None, home=None):
    choices = [allowed_values(v, it) if it.is_note else allowed_rests(v) for it in items]
    n_ordines = 1 + sum(1 for it in items if not it.is_note)
    best = None
    for vals in itertools.product(*choices):
        for om in itertools.product(MODES, repeat=n_ordines):
            modes, o = [], 0
            for it in items:
                modes.append(om[o])
                if not it.is_note:
                    o += 1
            s = path_score(model, items, v, list(vals), modes, style, home, final_mode=om[-1])
            if best is None or s > best[0] + 1e-9:
                best = (s, list(vals), modes)
    return best


@pytest.mark.parametrize('v,spec', [(UPPER, 'D (EC) |'), (UPPER, 'D (ECD) | E'), (TENOR, '(CAC) | D')])
@pytest.mark.parametrize('seed', [0, 1])
def test_viterbi_is_exact(make_mei, v, spec, seed):
    up, te = upper_and_tenor(make_mei(spec, spec))
    items = voice_items(up if v == UPPER else te, v)
    rnd = random.Random(seed)
    w = {k: x + rnd.uniform(-1, 1) for k, x in theory_weights().items()}
    model = Model(w)
    for style in (None, 'P'):
        r = decode_one(items, v, model, style=style, home=None, beam=10**6)
        s, vals, modes = brute_force(model, items, v, style)
        assert r.score == pytest.approx(s)
        assert path_score(model, items, v, r.values, r.modes, style, final_mode=r.final_mode) == pytest.approx(r.score)


def test_targets_are_met(make_mei):
    up, _ = upper_and_tenor(make_mei('D E F | (ECD) C | D E F |', 'D |'))
    items = voice_items(up, UPPER)
    strokes = [k for k, it in enumerate(items) if not it.is_note]
    r = decode(items, UPPER, Model(), targets={strokes[0]: 24, strokes[1]: 48})
    t, times = 0, {}
    for k, val in enumerate(r.values):
        t += val
        times[k] = t
    assert times[strokes[0]] == 24 and times[strokes[1]] == 48 and not r.dropped


def test_impossible_target_is_dropped(make_mei):
    up, _ = upper_and_tenor(make_mei('D E |', 'D |'))
    items = voice_items(up, UPPER)
    r = decode(items, UPPER, Model(), targets={2: 200})
    assert r.dropped == [2]
