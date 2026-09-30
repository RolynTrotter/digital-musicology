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
    a = mr.analyze(focal_score, method='mop')
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
    a = mr.analyze(focal_score, method='mop')
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
    a = mr.analyze(focal_score, method='mop')
    mr.write_json(a, tmp_path / 'a.json')
    b = json.loads((tmp_path / 'a.json').read_text())
    assert len(b['notes']) == len(a['notes'])


def test_reduction_score(focal_score):
    from melodic_reduction.export import reduction_score
    a = mr.analyze(focal_score, method='mop')
    red = reduction_score(focal_score, a, levels=('fundamental', 'span:2'))
    assert len(red.parts) == 4
    top = [n for n in red.parts[0].recurse().notes]
    assert len(top) == len(a['fundamental']['notes'])


# ------------------------------------------------------------------ grouped tree

def _clausula_like(tmp_path, n_pairs=4):
    """Duplum ordines of 3 perfections + rest, in pairs a = (D E F | E C D) ending on D;
    a fifth-mode tenor with rests in the same places."""
    ordo1 = [('D4', 1.5), ('E4', 1.5), ('F4', 1.5), ('r', 1.5)]
    ordo2 = [('E4', 1.0), ('C4', 0.5), ('E4', 1.0), ('F4', 0.5), ('D4', 1.5), ('r', 1.5)]
    t1 = [('D3', 3.0), ('C3', 1.5), ('r', 1.5)]
    t2 = [('B2', 1.5), ('C3', 1.5), ('D3', 1.5), ('r', 1.5)]
    d, t = [], []
    for _ in range(n_pairs):
        d += ordo1 + ordo2
        t += t1 + t2
    s = make_score(d, t)
    path = tmp_path / 'clausula.musicxml'
    s.write('musicxml', fp=str(path))
    return path


def test_ordines_split_on_period():
    from melodic_reduction.grouping import ordines
    seq = [('D4', 1.5), ('E4', 1.5), ('F4', 1.5), ('r', 1.5)] * 3
    seq = seq[:8] + [('D4', 1.5), ('E4', 1.5), ('F4', 1.5), ('G4', 1.5), ('F4', 1.5), ('E4', 1.5), ('r', 1.5)]
    notes = load_voice(make_score(seq), 0)
    spans = ordines(notes)
    # the last rest-group runs 6 bars without a rest: cut on the 4-bar period
    assert [(notes[a].measure, notes[b].measure) for a, b in spans] == [(1, 3), (5, 7), (9, 12), (13, 14)]


def test_tree_pairs_and_home_notes(tmp_path):
    path = _clausula_like(tmp_path)
    a = mr.analyze(path)
    assert a['method'] == 'tree'
    pairs = [m['measures'] for m in a['modules']]
    assert pairs[0] == [1, 7] and pairs[1] == [9, 15]          # pairs of ordines, in phase
    assert all(m['label'] == 'a' for m in a['modules'])         # identical pairs share a label


def test_labels_follow_the_opening(tmp_path):
    # pairs open D-E-F (a) or C-D-E-F (b); the second ordo varies. A pair takes its letter from its
    # opening, a prime when the rest differs, and the same label when it matches a member whole.
    o = lambda ps: [(p, 1.5) for p in ps] + [('r', 1.5)]
    d = (o(['D4', 'E4', 'F4']) + o(['E4', 'C4', 'D4']) +       # a
         o(['C4', 'D4', 'F4']) + o(['E4', 'D4', 'D4']) +       # b (opens C-D-F: new letter)
         o(['D4', 'E4', 'F4']) + o(['F4', 'G4', 'E4']) +       # a' (opens like a)
         o(['D4', 'E4', 'F4']) + o(['E4', 'C4', 'D4']))        # a (same as the first)
    t = ([('D3', 3.0), ('C3', 1.5), ('r', 1.5)]) * 8
    path = tmp_path / 'labels.musicxml'
    make_score(d, t).write('musicxml', fp=str(path))
    a = mr.analyze(path)
    assert [m['label'] for m in a['modules']] == ['a', 'b', 'a′', 'a']
    # every pair ends on D, so every pair of pairs is heard as prolonging D
    assert all(sec['home'] == 'D4' for sec in a['sections'])
    assert any(sec['pedal'] and sec['pedal']['pitch'] == 'F4' for sec in a['sections'])
    # each ordo is reduced inside itself: dependencies at level 1 stay within the ordo
    notes = a['notes']
    for d in a['dependencies']:
        if d['level'] == 1:
            ends = [x for x in d['parent'] if x is not None]
            assert all(notes[x]['measure'] // 4 == notes[d['note']]['measure'] // 4 for x in ends)
    # the tenor is reduced too
    rv = a['reference_voice']
    assert rv['fundamental']['notes'] and any(n['level'] >= 1 for n in rv['notes'])


def test_tree_levels_nested(tmp_path):
    a = mr.analyze(_clausula_like(tmp_path))
    names = list(a['levels'])
    for lo, hi in zip(names, names[1:]):
        assert set(a['levels'][hi]) <= set(a['levels'][lo])
    assert len(a['levels']['piece']) == 1


def test_tree_reduction_score(tmp_path):
    from melodic_reduction.export import reduction_score
    path = _clausula_like(tmp_path)
    a = mr.analyze(path)
    red = reduction_score(path, a, levels=('fundamental', 'ordo'))
    assert len(red.parts) == 4


def test_unit_period_uses_tenor():
    from melodic_reduction.grouping import unit_period
    # duplum ordines of 8 and 4 bars over a tenor whose ordines are 4 bars: the unit is the tenor's
    d = ([('D4', 1.5)] * 7 + [('r', 1.5)] + [('E4', 1.5)] * 3 + [('r', 1.5)]) * 3
    t = ([('D3', 1.5)] * 3 + [('r', 1.5)]) * 9
    s = make_score(d, t)
    assert unit_period(load_voice(s, 0, 1), load_voice(s, 1, 0)) == 6.0
    # a duplum whose ordines are all 8 bars doubles the unit
    d2 = ([('D4', 1.5)] * 7 + [('r', 1.5)]) * 4
    s2 = make_score(d2, t[:32])
    assert unit_period(load_voice(s2, 0, 1), load_voice(s2, 1, 0)) == 12.0


def test_stepwise_line_into_home(tmp_path):
    # ordo heads F E F D in one pair of pairs -> a stepwise line F-E-D into the home D
    o = lambda p: [(p, 1.5), (p, 1.5), (p, 1.5), ('r', 1.5)]
    d = o('F4') + o('C4') + o('F4') + o('D4') + o('F4') + o('E4') + o('F4') + o('D4')
    t = ([('D3', 3.0), ('D3', 1.5), ('r', 1.5)]) * 8
    path = tmp_path / 'line.musicxml'
    make_score(d, t).write('musicxml', fp=str(path))
    a = mr.analyze(path)
    lines = [sec['line'] for sec in a['sections'] if sec['line']]
    assert len(a['sections']) == 2 and len(lines) == 1 and [x.split('@')[0] for x in lines[0]] == ['F4', 'E4', 'D4']
