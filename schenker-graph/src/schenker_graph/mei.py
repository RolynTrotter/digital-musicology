"""Engrave a score with Schenkerian overlays.

Pipeline: MusicXML --(verovio)--> MEI --(add colour, slurs, labels)--> SVG pages
--(draw stems and beams for the fundamental line)--> SVG / PNG / PDF.

Verovio engraves everything it can natively (slurs, dashed slurs, text directives), because it
knows where notes land and breaks slurs across systems itself. The one thing MEI cannot say
is the Schenkerian beam: a beam joining non-adjacent notes across barlines and systems, while the
notes keep their own rhythmic stems and beams. That is drawn on the SVG afterwards from the
notehead positions verovio reports.
"""
from __future__ import annotations

import copy
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

MEI_NS = 'http://www.music-encoding.org/ns/mei'
XML_ID = '{http://www.w3.org/XML/1998/namespace}id'
SVG_NS = 'http://www.w3.org/2000/svg'
XLINK = '{http://www.w3.org/1999/xlink}href'
NS = {'m': MEI_NS}


def _q(tag):
    return f'{{{MEI_NS}}}{tag}'


# ------------------------------------------------------------------ the graph specification

@dataclass
class Graph:
    """What to draw. Note references are indices into the analysed voice (ties merged, rests
    skipped), exactly as melodic-reduction numbers them; ``staff`` is 1-based."""
    staff: int = 1
    fundamental: list[int] = field(default_factory=list)       # beamed, stemmed, coloured
    middleground: list[int] = field(default_factory=list)      # coloured (second colour)
    slurs: list[dict] = field(default_factory=list)            # {from, to, style solid|dashed, place above|below}
    labels: list[dict] = field(default_factory=list)           # {at, text, place}
    brackets: list[dict] = field(default_factory=list)         # {from, to, text, place}
    colors: dict = field(default_factory=lambda: {
        'fundamental': '#b3261e', 'middleground': '#1f5fa8', 'slur': '#1f5fa8',
        'focal': '#6b6b6b', 'label': '#333333', 'bracket': '#555555'})
    beam_gap: float = 2.0        # staff spaces between the highest fundamental notehead and the beam
    beam_thickness: float = 0.5  # staff spaces
    beam_direction: str = 'up'   # 'up' (beam above the staff) or 'down' (below: a lower voice)
    title: str | None = None
    voice_pitches: list | None = None   # pitches of the analysed voice, to check the alignment
    others: list = field(default_factory=list)   # overlays for other staves (Graphs)

    @classmethod
    def from_dict(cls, d):
        g = cls()
        for k, v in d.items():
            if k == 'colors':
                g.colors.update(v)
            elif k == 'others':
                g.others = [o if isinstance(o, Graph) else Graph.from_dict(o) for o in v]
            elif hasattr(g, k):
                setattr(g, k, v)
        return g

    def to_dict(self):
        d = {k: getattr(self, k) for k in ('staff', 'fundamental', 'middleground', 'slurs',
                                           'labels', 'brackets', 'colors', 'beam_gap',
                                           'beam_thickness', 'beam_direction', 'title')}
        d['others'] = [o.to_dict() for o in self.others]
        return d


# ------------------------------------------------------------------ MEI note mapping

def staff_notes(mei_root, staff_n: int):
    """MEI <note> elements of one staff in score order with tie continuations removed (so the
    list lines up with a ties-merged voice), plus the ids of those continuations."""
    tie_ends = set()
    for tie in mei_root.iter(_q('tie')):
        e = tie.get('endid')
        if e:
            tie_ends.add(e.lstrip('#'))
    for n in mei_root.iter(_q('note')):
        if n.get('tie') in ('m', 't'):
            tie_ends.add(n.get(XML_ID))
    out = []
    for staff in mei_root.iter(_q('staff')):
        if staff.get('n') != str(staff_n):
            continue
        for n in staff.iter(_q('note')):
            if n.getparent().tag == _q('chord'):
                # a chord counts once: its highest note (melodic-reduction takes the top)
                ch = n.getparent()
                if n is not max(ch.findall(_q('note')), key=_note_height):
                    continue
            if n.get('grace'):
                continue
            if n.get(XML_ID) in tie_ends:
                continue
            out.append(n)
    return out


_STEP = {'c': 0, 'd': 1, 'e': 2, 'f': 3, 'g': 4, 'a': 5, 'b': 6}


def _note_height(n):
    return int(n.get('oct', '4')) * 7 + _STEP.get(n.get('pname', 'c'), 0)


def check_alignment(mei_notes, voice_pitches):
    """Compare letter+octave of the MEI notes with the analysed voice ('B-4' -> b4)."""
    if len(mei_notes) != len(voice_pitches):
        raise ValueError(f'MEI staff has {len(mei_notes)} notes, analysis has {len(voice_pitches)}')
    bad = []
    for k, (n, p) in enumerate(zip(mei_notes, voice_pitches)):
        m = re.match(r'([A-Ga-g])[#\-~`]*(-?\d+)', p)
        want = (m.group(1).lower(), m.group(2))
        got = (n.get('pname'), n.get('oct'))
        if want != got:
            bad.append((k, p, got))
    if bad:
        raise ValueError(f'pitch mismatch between score and analysis at {bad[:5]}')


# ------------------------------------------------------------------ MEI annotation

def _control_parent(note_el):
    """The <measure> that holds a note (control events go there)."""
    p = note_el
    while p is not None and p.tag != _q('measure'):
        p = p.getparent()
    return p


_idc = [0]


def _nid(prefix):
    _idc[0] += 1
    return f'{prefix}{_idc[0]:05d}'


def annotate_mei(mei_root, graph: Graph, voice_pitches):
    notes = staff_notes(mei_root, graph.staff)
    if voice_pitches:
        check_alignment(notes, voice_pitches)
    ids = [n.get(XML_ID) for n in notes]

    for k in graph.middleground:
        notes[k].set('color', graph.colors['middleground'])
    for k in graph.fundamental:
        notes[k].set('color', graph.colors['fundamental'])
        notes[k].set('stem.dir', graph.beam_direction)

    for s in graph.slurs:
        a, b = s['from'], s['to']
        if a == b:
            continue
        el = etree.SubElement(_control_parent(notes[a]), _q('slur'))
        el.set(XML_ID, _nid('slur'))
        el.set('startid', '#' + ids[a])
        el.set('endid', '#' + ids[b])
        el.set('staff', str(graph.staff))
        el.set('curvedir', s.get('place', 'below'))
        if s.get('width'):
            el.set('lwidth', str(s['width']))
        if s.get('style') == 'dashed':
            el.set('lform', 'dashed')
        el.set('color', s.get('color', graph.colors['focal' if s.get('style') == 'dashed' else 'slur']))

    for lab in graph.labels:
        el = etree.SubElement(_control_parent(notes[lab['at']]), _q('dir'))
        el.set(XML_ID, _nid('dir'))
        el.set('startid', '#' + ids[lab['at']])
        el.set('staff', str(graph.staff))
        el.set('place', lab.get('place', 'above'))
        el.set('color', lab.get('color', graph.colors['label']))
        rend = etree.SubElement(el, _q('rend'))
        rend.set('fontsize', lab.get('size', 'small'))
        if lab.get('bold'):
            rend.set('fontweight', 'bold')
            rend.set('fontstyle', 'normal')
        rend.text = lab['text']

    for br in graph.brackets:
        el = etree.SubElement(_control_parent(notes[br['from']]), _q('dir'))
        el.set(XML_ID, _nid('brk'))
        el.set('startid', '#' + ids[br['from']])
        el.set('endid', '#' + ids[br['to']])
        el.set('staff', str(graph.staff))
        el.set('place', br.get('place', 'below'))
        el.set('extender', 'true')
        el.set('lform', 'solid')
        el.set('color', br.get('color', graph.colors['bracket']))
        rend = etree.SubElement(el, _q('rend'))
        rend.set('fontstyle', 'normal')
        rend.set('fontweight', 'bold')
        rend.text = br.get('text', '')

    if graph.title:
        for title in mei_root.iter(_q('title')):
            title.text = graph.title
            break
    for other in graph.others:
        annotate_mei(mei_root, other, other.voice_pitches or [])
    return ids
