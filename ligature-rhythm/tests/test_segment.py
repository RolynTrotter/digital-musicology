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


def test_duplicate_setting_keeps_the_fullest_tenor(make_mei):
    # CANDR sometimes catalogues one system several times (once per clausula on it); every copy
    # repeats the upper voice, but only one holds the whole tenor
    up = 'F E D | C D E | F E D | C D E ||'
    a = make_mei(up, 'D C |', 'setting_0001.mei')
    b = make_mei(up, 'D C C A C D C B | D C C A |', 'setting_0002.mei')
    from ligature_rhythm.segment import chain
    u, t = chain([a, b])
    notes = [n.pname for _, x in t for n in ([x] if hasattr(x, 'pname') else getattr(x, 'notes', []))]
    assert len(notes) == 12
    assert len([x for _, x in u if hasattr(x, 'pname')]) == 12


def test_kfold_groups_never_split_a_group():
    from ligature_rhythm.train import kfold_groups
    groups = [['a', 'b'], ['c'], ['d', 'e', 'f'], ['g'], ['h']]
    folds = kfold_groups(groups, 3)
    assert sorted(p for f in folds for p in f) == list('abcdefgh')
    for g in groups:
        assert sum(all(p in f for p in g) for f in folds) == 1
