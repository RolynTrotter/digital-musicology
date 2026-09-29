"""Test helpers: build small CANDR-style MEI settings from a compact notation.

``mei(upper, tenor)`` takes strings such as ``"D E F | (ECD) C ||"``: letters are notes (lower octave
3), ``(..)`` a square ligature, ``{..}`` currentes, ``^``/``v`` after a note a plica, ``|`` a stroke
(``||`` a long one). ``|a`` / ``|a`` on both voices with the same label are synchronised strokes.
"""
import re
import textwrap
from pathlib import Path

import pytest

NS = 'http://www.music-encoding.org/ns/mei'


def _layer(spec, prefix, synch_to=None):
    out, n, labels = [], 0, {}
    for tok in re.findall(r'\|\|?[a-z]?|\([^)]*\)|\{[^}]*\}|[A-G][\^v]?', spec):
        if tok.startswith('|'):
            n += 1
            sid = f'{prefix}d{n}'
            length = 6.5 if tok.startswith('||') else 3.0
            label = tok.lstrip('|')
            syn = ''
            if label:
                labels[label] = sid
                if synch_to and label in synch_to:
                    syn = f' synch="#{synch_to[label]}"'
            out.append(f'<divisione xml:id="{sid}" len="{length}"{syn}/>')
            continue
        def note(ch, k):
            pl = ''
            if len(ch) > 1:
                pl = f'<plica dir="{"up" if ch[1] == "^" else "down"}"/>'
            return (f'<note xml:id="{prefix}n{k}" pname="{ch[0].lower()}" oct="3">{pl}</note>'
                    if pl else f'<note xml:id="{prefix}n{k}" pname="{ch[0].lower()}" oct="3"/>')
        if tok[0] in '({':
            kind = 'square' if tok[0] == '(' else 'currentes'
            notes = re.findall(r'[A-G][\^v]?', tok)
            inner = ''
            for ch in notes:
                n += 1
                inner += note(ch, n)
            out.append(f'<ligature type="{kind}">{inner}</ligature>')
        else:
            n += 1
            out.append(note(tok, n))
    return ''.join(out), labels


def mei_text(upper, tenor):
    te, te_labels = _layer(tenor, 't')
    up, _ = _layer(upper, 'u', synch_to=te_labels)
    return textwrap.dedent(f'''<?xml version="1.0" encoding="utf-8"?>
    <mei xmlns="{NS}"><music><body><mdiv><section>
    <staff n="1"><layer>{up}</layer></staff>
    <staff n="2"><layer>{te}</layer></staff>
    </section></mdiv></body></music></mei>''')


@pytest.fixture
def make_mei(tmp_path):
    def make(upper, tenor, name='setting_0001.mei'):
        p = Path(tmp_path) / name
        p.write_text(mei_text(upper, tenor))
        return p
    return make
