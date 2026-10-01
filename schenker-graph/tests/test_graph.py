import re

import pytest
from music21 import stream, note, meter

import melodic_reduction as mr
import schenker_graph as sg


@pytest.fixture
def score_path(tmp_path):
    s = stream.Score()
    d = ['F4', 'E4', 'F4', 'G4', 'F4', 'E4', 'D4', 'F4', 'G4', 'F4', 'E4', 'D4', 'C4', 'D4'] * 3
    t = ['F3', 'C4', 'F3', 'A3', 'F3', 'D3', 'D3'] * 3
    for name, seq, ql in (('Duplum', d, 1.5), ('Tenor', t, 3.0)):
        p = stream.Part()
        p.partName = name
        p.append(meter.TimeSignature('3/8'))
        for x in seq:
            p.append(note.Note(x, quarterLength=ql))
        s.insert(0, p.makeMeasures())
    path = tmp_path / 's.musicxml'
    s.write('musicxml', fp=str(path))
    return path


def test_overlay_graph(score_path, tmp_path):
    files, g, a = sg.schenker_graph(score_path, out_prefix=tmp_path / 'g', formats=('svg',))
    svgs = [f for f in files if str(f).endswith('.svg')]
    assert svgs
    text = ''.join(open(f).read() for f in svgs)
    assert 'schenker-beam' in text
    # one stem per fundamental note
    stems = len(re.findall(r'<path d="M[\d.]+ [\d.]+ L[\d.]+ [\d.]+" stroke="#b3261e"', text))
    assert stems == len(g.fundamental) + sum(len(o.fundamental) for o in g.others)
    mei = [f for f in files if str(f).endswith('.mei')][0].read_text()
    assert 'slur' in mei


def test_hand_spec_addresses(score_path, tmp_path):
    a = mr.analyze(score_path)
    first = a['notes'][0]['address']
    last = a['notes'][-1]['address']
    spec = {'replace': True, 'fundamental': [first, last],
            'labels': [{'at': first, 'text': 'hello'}]}
    files, g, _ = sg.schenker_graph(score_path, analysis=a, graph=spec,
                                    out_prefix=tmp_path / 'h', formats=('svg',))
    assert g.fundamental == [0, len(a['notes']) - 1]
    assert 'hello' in ''.join(open(f).read() for f in files if str(f).endswith('.svg'))


def test_mop_graph(score_path, tmp_path):
    a = mr.analyze(score_path, method='mop')
    files, g, _ = sg.schenker_graph(score_path, analysis=a, out_prefix=tmp_path / 'm', formats=('svg',))
    assert g.fundamental == a['fundamental']['notes']


def test_stacked(score_path, tmp_path):
    files, g, a = sg.schenker_graph(score_path, out_prefix=tmp_path / 's', formats=('svg',),
                                    stacked=('fundamental', 'ordo'))
    assert g.staff == 3
    assert any(str(f).endswith('.svg') for f in files)


def test_every_note_accounted_and_no_collisions(score_path, tmp_path):
    from schenker_graph.graph import graph_from_tree, unaccounted
    from schenker_graph.collide import collisions
    a = mr.analyze(score_path)
    g = graph_from_tree(a)
    assert unaccounted(g, len(a['notes'])) == []
    assert unaccounted(g.others[0], len(a['reference_voice']['notes'])) == []
    files, g, _ = sg.schenker_graph(score_path, analysis=a, out_prefix=tmp_path / 'c', formats=('svg',))
    for f in files:
        if str(f).endswith('.svg'):
            assert [c for c in collisions(open(f).read()) if c[0] == 'slur-text'] == []


def test_thin_slurs_keeps_inner_and_outer():
    from schenker_graph.mei import Graph
    from schenker_graph.graph import thin_slurs, unaccounted
    # five nested slurs below the staff: 0-9 encloses 1-8 encloses 2-7 encloses 3-6 encloses 4-5
    g = Graph(slurs=[{'from': i, 'to': 9 - i, 'place': 'below'} for i in range(5)])
    assert thin_slurs(g, max_stack=3) == 2
    shown = sorted((s['from'], s['to']) for s in g.slurs if not s['hidden'])
    assert shown == [(0, 9), (3, 6), (4, 5)]            # outermost + two innermost layers
    assert unaccounted(g, 10) == []


def test_system_splitting_prefers_pair_boundaries():
    from schenker_graph.graph import _make_splitter, system_load
    notes, groups = [], []
    for k in range(8):                                 # 8 ordines of 4 bars, 3 notes each
        for j in range(3):
            notes.append({'idx': len(notes), 'onset': (4 * k + j) * 1.5, 'measure': 4 * k + j + 1})
    ordo = lambda k: {'level': 1, 'first': 3 * k, 'last': 3 * k + 2, 'children': []}
    pair = lambda k: {'level': 2, 'first': 3 * k, 'last': 3 * k + 5, 'children': [ordo(k), ordo(k + 1)]}
    pop = lambda k: {'level': 3, 'first': 3 * k, 'last': 3 * k + 11, 'children': [pair(k), pair(k + 2)]}
    a = {'notes': notes, 'groups': {'level': 4, 'first': 0, 'last': 23, 'children': [pop(0), pop(4)]}}
    split = _make_splitter(a)
    assert split(1, 16) == 9                           # the second pair starts at m. 9
    assert system_load(notes, [], 1, 16) == 12 + 16
