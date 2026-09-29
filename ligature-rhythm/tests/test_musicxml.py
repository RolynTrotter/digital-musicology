import xml.etree.ElementTree as ET

from ligature_rhythm.musicxml import to_musicxml
from ligature_rhythm.realise import Event, realise
from ligature_rhythm.candr import upper_and_tenor


def bars(xml):
    root = ET.fromstring(xml.split('\n', 2)[2])
    return {p.get('id'): [sum(int(n.findtext('duration')) for n in m.findall('note')) for m in p.findall('measure')]
            for p in root.iter('part')}


def test_bars_are_full_and_long_notes_tie():
    up = [Event(0, 12, ('D', 0, 4)), Event(12, 4, ('E', 0, 4), lig=(1, 0, 2, 'square')),
          Event(16, 2, ('F', 0, 4), lig=(1, 1, 2, 'square'))]
    te = [Event(0, 18, ('D', 0, 3))]
    xml = to_musicxml(up, te, 'test')
    for part in bars(xml).values():
        assert all(b == 6 for b in part) and len(part) == 3
    assert xml.count('<tied type="start"') == 1 + 2      # D over two bars, tenor over three
    assert 'bracket' in xml


def test_realise_end_to_end(make_mei):
    up, te = upper_and_tenor(make_mei('D E F |a (ECD) C |b D E F |c (ECE) (FD) ||',
                                      'D C |a (CAC) |b D C |c (BCD) ||'))
    res = realise(up, te)
    assert res.info['synch_dropped'] == []
    end_up = max(e.onset + e.duration for e in res.upper if e.pitch)
    end_te = max(e.onset + e.duration for e in res.tenor if e.pitch)
    assert end_up == end_te                                  # the voices end together
    for part in bars(to_musicxml(res.upper, res.tenor)).values():
        assert all(b == 6 for b in part)
