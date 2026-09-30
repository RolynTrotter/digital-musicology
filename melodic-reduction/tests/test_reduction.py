import json

import numpy as np

import melodic_reduction as mr
from melodic_reduction.mop import _relations, parse
from melodic_reduction.features import find_modules
from melodic_reduction.voice import load_voice
from conftest import make_score


def test_relations():
    dk = np.array([30.0, 31.0, 29.0, 33.0])   # E4 F4 D4 A4 between D4 (29) and F4 (31)
    rel = _relations(29.0, 31.0, dk, True, True)
    assert list(rel) == ['PASS', 'REP', 'REP', 'OTHER']
    rel = _relations(31.0, 31.0, np.array([30.0, 32.0, 28.0]), True, True)
    assert list(rel) == ['NEI', 'NEI', 'NEI_LEAP']


def test_passing_note_is_subordinate():
    w = mr.load_weights('default')
    d = [29, 30, 31]                  # D E F, E short and off the beat
    sal = [2.0, 0.0, 2.0]
    t = parse(d, sal, [0.0, 1.5, 2.0], 3.5, 1.5, w)
    assert t.relation[2] == 'PASS' and t.height[2] == 0


def test_focal_pitch_found(focal_score):
    a = mr.analyze(focal_score)
    dom = a['dominant_focal_pitches']
    assert dom and dom[0]['pitch'] == 'F4'
    assert a['notes'][0]['relation'] == 'FRAME'
    fund = [a['notes'][i]['pitch'] for i in a['fundamental']['notes']]
    assert fund[0] == 'F4' and fund[-1] == 'D4'
    # every note has a parent interval that contains it
    for n in a['notes']:
        i, j = n['parent']
        if n['relation'] != 'FRAME':
            assert (i is None or i < n['idx']) and (j is None or j > n['idx'])


def test_reductions_are_nested(focal_score):
    a = mr.analyze(focal_score)
    prev = None
    for T in sorted(a['levels_by_span_units'], key=float, reverse=True):
        cur = set(a['levels_by_span_units'][T])
        if prev is not None:
            assert prev <= cur
        prev = cur


def test_modules_find_transposed_repeat():
    motif = [('D4', 1.0), ('E4', 0.5), ('F4', 1.0), ('E4', 0.5), ('D4', 1.5)]
    up = [('E4', 1.0), ('F4', 0.5), ('G4', 1.0), ('F4', 0.5), ('E4', 1.5)]
    s = make_score(motif + [('r', 1.5)] + up + [('r', 1.5)] + [('C4', 1.5)])
    notes = load_voice(s, 0)
    mods = find_modules(notes, 5)
    assert mods and len(mods[0]['occurrences']) == 2
    assert mods[0]['occurrences'][1][2] == 1          # transposed up a step


def test_json_roundtrip(focal_score, tmp_path):
    a = mr.analyze(focal_score)
    mr.write_json(a, tmp_path / 'a.json')
    b = json.loads((tmp_path / 'a.json').read_text())
    assert len(b['notes']) == len(a['notes'])


def test_reduction_score(focal_score):
    from melodic_reduction.export import reduction_score
    a = mr.analyze(focal_score)
    red = reduction_score(focal_score, a, levels=('fundamental', 'span:2'))
    assert len(red.parts) == 4
    top = [n for n in red.parts[0].recurse().notes]
    assert len(top) == len(a['fundamental']['notes'])
