from ligature_rhythm.candr import Ligature, Note, Stroke, parse_mei, show, upper_and_tenor
from ligature_rhythm.items import TENOR, UPPER, voice_items


def test_parse_roundtrip(make_mei):
    p = make_mei('D E F |a (ECD) C^ ||', 'D C |a (CAC) ||')
    up, te = upper_and_tenor(p)
    assert show(up) == 'D E F | (ECD) C^ ||'
    assert isinstance(up[3], Stroke) and up[3].synch == te[2].id
    assert isinstance(up[4], Ligature) and [n.pname for n in up[4].notes] == ['e', 'c', 'd']
    assert up[5].plica == 'up'


def test_items_context(make_mei):
    up, te = upper_and_tenor(make_mei('D E | (ECD) (FE) C || {GFED} E', 'D C |'))
    items = voice_items(up, UPPER)
    notes = [it for it in items if it.is_note]
    assert [it.ctx for it in notes][:8] == ['S', 'S', 'L3.0', 'L3.1', 'L3.2', 'L2.0', 'L2.1', 'S']
    assert notes[0].short and not notes[2].short              # two single notes: a separating stroke
    strokes = [it for it in items if not it.is_note]
    assert strokes[0].short and strokes[0].after == 'S'
    assert strokes[1].length == 6.5                           # merged double stroke keeps the longest
    assert notes[2].osig == (3, 1, (3, 2), (2, 1))
    assert notes[-1].final and notes[-1].ctx == 'S'
    assert [it.ctx for it in notes[8:12]] == ['Cn.0', 'Cn.m', 'Cn.p', 'Cn.z']


def test_tenor_short_is_one_note(make_mei):
    _, te = upper_and_tenor(make_mei('D', 'D C | A |'))
    items = voice_items(te, TENOR)
    assert not items[0].short and items[3].short
