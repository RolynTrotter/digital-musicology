import pytest
from music21 import stream, note, meter, clef


def make_score(duplum, tenor=None, ts='3/8'):
    """duplum/tenor: lists of (pitch or 'r', quarterLength)."""
    s = stream.Score()
    for name, seq in (('Duplum', duplum), ('Tenor', tenor)):
        if seq is None:
            continue
        p = stream.Part()
        p.partName = name
        p.append(meter.TimeSignature(ts))
        for pt, ql in seq:
            p.append(note.Rest(quarterLength=ql) if pt == 'r' else note.Note(pt, quarterLength=ql))
        s.insert(0, p.makeMeasures())
    return s


@pytest.fixture
def focal_score(tmp_path):
    # an F prolonged by lower and upper neighbours and a passing descent, over a tenor on F/C
    d = [('F4', 1.5), ('E4', 1.0), ('F4', 0.5), ('G4', 1.5), ('F4', 1.5), ('E4', 1.0), ('D4', 0.5),
         ('F4', 1.5), ('r', 1.5), ('F4', 1.5), ('G4', 1.0), ('F4', 0.5), ('E4', 1.5), ('F4', 1.5),
         ('E4', 1.0), ('D4', 0.5), ('C4', 1.5), ('D4', 1.5), ('r', 1.5)]
    t = [('F3', 3.0), ('C4', 3.0), ('F3', 3.0), ('r', 1.5), ('F3', 3.0), ('A3', 3.0), ('F3', 3.0),
         ('D3', 3.0), ('r', 1.5)]
    s = make_score(d, t)
    path = tmp_path / 'focal.musicxml'
    s.write('musicxml', fp=str(path))
    return path
