from ligature_rhythm.segment import guess_incipit, restarts, split


def test_split_two_clausulae(make_mei):
    chant = 'D C C A C D C B'
    lig = lambda s: ' '.join(s.split())
    a = make_mei('F E D |a C D E ||', f'{lig(chant)} |a', 'setting_0001.mei')
    b = make_mei('G F E |b D C D ||', f'{lig(chant)} |b', 'setting_0002.mei')
    parts, head = split([a, b], incipit='DCCACDCB', min_gap=4)
    assert len(parts) == 2
    assert [n.pname for n in parts[0].tenor if hasattr(n, 'pname')][:3] == ['d', 'c', 'c']


def test_restart_in_mid_setting_is_a_second_cursus(make_mei):
    chant = 'D C C A C D C B'
    a = make_mei('F E D C D E F E D C D E F E D C', f'{chant} | {chant} |', 'setting_0001.mei')
    parts, _ = split([a], incipit='DCCACDCB', min_gap=4)
    assert len(parts) == 1
