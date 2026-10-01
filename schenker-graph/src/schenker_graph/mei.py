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
    voice_onsets: list | None = None    # onsets (quarter notes) of the analysed voice: align by time
    others: list = field(default_factory=list)   # overlays for other staves (Graphs)
    stems: list = field(default_factory=list)    # stemmed notes without a beam: {notes, direction, length}
    breaks: list = field(default_factory=list)   # note indices: start a new system at their measure
    break_measures: list = field(default_factory=list)   # or measure numbers (used when given)
    systems_per_page: int = 5
    splitter: object = None      # (first, last measure) -> measure to break a crowded system at

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
                                           'beam_thickness', 'beam_direction', 'title', 'stems',
                                           'breaks', 'break_measures', 'systems_per_page')}
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


def _insert_breaks(mei_root, first_notes, per_page=5, measures=None):
    """System breaks (<sb/>) before the measures holding ``first_notes``, and a page break (<pb/>)
    every ``per_page`` systems. Render with verovio's breaks='encoded'."""
    # the source's own layout (MusicXML <print new-system/new-page>) is replaced
    for el in list(mei_root.iter(_q('sb'), _q('pb'))):
        el.getparent().remove(el)
    targets = []
    for n in first_notes:
        m = _control_parent(n)
        if m is not None and m not in targets:
            targets.append(m)
    if measures:
        want = {str(x) for x in measures}
        targets += [m for m in mei_root.iter(_q('measure')) if m.get('n') in want and m not in targets]
    measures = list(mei_root.iter(_q('measure')))
    order = {id(m): i for i, m in enumerate(measures)}
    targets = sorted((m for m in targets if order[id(m)] > 0), key=lambda m: order[id(m)])
    for i, m in enumerate(targets, 1):
        br = etree.Element(_q('pb') if i % per_page == 0 else _q('sb'))
        br.set(XML_ID, _nid('brk'))
        m.addprevious(br)


def staff_notes_by_onset(mei_root, staff_n: int, onsets, qstamps: dict):
    """The staff's MEI notes that sound at ``onsets`` (quarter notes from the start), using
    verovio's timemap (``qstamps``: note id -> onset). Robust to ties the encoding leaves
    dangling, which make tie-skipping and the analysis disagree about which notes exist."""
    by_q = {}
    for staff in mei_root.iter(_q('staff')):
        if staff.get('n') != str(staff_n):
            continue
        for n in staff.iter(_q('note')):
            q = qstamps.get(n.get(XML_ID))
            if q is None or n.get('grace'):
                continue
            key = round(q, 3)
            if key not in by_q or _note_height(n) > _note_height(by_q[key]):
                by_q[key] = n
    out = []
    for o in onsets:
        n = by_q.get(round(o, 3))
        if n is None:
            raise ValueError(f'no note on staff {staff_n} at quarter {o}')
        out.append(n)
    return out


def annotate_mei(mei_root, graph: Graph, voice_pitches, qstamps: dict | None = None):
    # align in note order (tie continuations skipped); if the encoding's ties make that disagree
    # with the analysis, align by onset through verovio's timemap
    notes = staff_notes(mei_root, graph.staff)
    try:
        if voice_pitches:
            check_alignment(notes, voice_pitches)
    except ValueError:
        if not (qstamps and graph.voice_onsets):
            raise
        notes = staff_notes_by_onset(mei_root, graph.staff, graph.voice_onsets, qstamps)
        if voice_pitches:
            check_alignment(notes, voice_pitches)
    ids = [n.get(XML_ID) for n in notes]
    graph.note_ids = ids

    for k in graph.middleground:
        notes[k].set('color', graph.colors['middleground'])
    for k in graph.fundamental:
        notes[k].set('color', graph.colors['fundamental'])
        notes[k].set('stem.dir', graph.beam_direction)
    for st in graph.stems:
        # the note's own stem, turned and lengthened: slurs then attach at its tip instead of
        # crossing it (length in staff spaces; MEI stem.len is in half spaces)
        for k in st['notes']:
            if k not in graph.fundamental:
                notes[k].set('stem.dir', st.get('direction', 'up'))
                notes[k].set('stem.len', f"{2 * st.get('length', 4.5):g}vu")
    if graph.break_measures:
        _insert_breaks(mei_root, [], graph.systems_per_page, measures=graph.break_measures)
    elif graph.breaks:
        _insert_breaks(mei_root, [notes[k] for k in graph.breaks], graph.systems_per_page)

    for s in graph.slurs:
        a, b = s['from'], s['to']
        if a == b or s.get('hidden'):       # hidden: kept in the analysis, not printed
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
        parts = str(lab['text']).split('\n')
        rend.text = parts[0]
        for extra in parts[1:]:
            lb = etree.SubElement(rend, _q('lb'))
            lb.tail = extra

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
        annotate_mei(mei_root, other, other.voice_pitches or [], qstamps)
    return ids
