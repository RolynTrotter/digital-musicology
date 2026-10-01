"""Find collisions in a rendered graph: slurs against text labels, slurs against the added
Schenkerian beams and stems, and slurs crossing each other's ends.

Geometry is read from verovio's SVG. Slurs are filled shapes made of cubic curves; they are
sampled into points. Text boxes are estimated from the font size and string length.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from lxml import etree

SVG_NS = 'http://www.w3.org/2000/svg'


def _cls(el):
    return (el.get('class') or '').split()


def _bezier(p0, p1, p2, p3, n=12):
    out = []
    for i in range(n + 1):
        t = i / n
        a = (1 - t) ** 3
        b = 3 * (1 - t) ** 2 * t
        c = 3 * (1 - t) * t ** 2
        d = t ** 3
        out.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
                    a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return out


def path_points(d: str):
    toks = re.findall(r'[MLCZmlcz]|-?\d+(?:\.\d+)?', d)
    pts, cur, cmd, i = [], (0.0, 0.0), None, 0
    while i < len(toks):
        t = toks[i]
        if t.isalpha():
            cmd = t
            i += 1
            if cmd in 'Zz':
                continue
            continue
        if cmd in ('M', 'L'):
            cur = (float(toks[i]), float(toks[i + 1]))
            pts.append(cur)
            i += 2
        elif cmd == 'C':
            p1 = (float(toks[i]), float(toks[i + 1]))
            p2 = (float(toks[i + 2]), float(toks[i + 3]))
            p3 = (float(toks[i + 4]), float(toks[i + 5]))
            pts.extend(_bezier(cur, p1, p2, p3)[1:])
            cur = p3
            i += 6
        else:
            i += 1
    return pts


@dataclass
class Box:
    kind: str
    ident: str
    x0: float
    y0: float
    x1: float
    y1: float
    text: str = ''

    def hits(self, pts, pad=0.0):
        return any(self.x0 - pad <= x <= self.x1 + pad and self.y0 - pad <= y <= self.y1 + pad for x, y in pts)


STEM_TRIM = 150.0   # the part of a stem next to its notehead, where slurs legitimately start


def _stem_box(pts, ident):
    (xa, ya), (xb, yb) = pts          # (xa, ya) is at the notehead
    if yb < ya:
        y0, y1 = yb, ya - STEM_TRIM
    else:
        y0, y1 = ya + STEM_TRIM, yb
    return Box('stem', ident, min(xa, xb) - 10, y0, max(xa, xb) + 10, y1)


def collect(svg: str):
    root = etree.fromstring(svg.encode('utf-8'))
    slurs, boxes = [], []
    for p in root.iter(f'{{{SVG_NS}}}path'):
        if 'schenker-stem' in _cls(p):
            pts = path_points(p.get('d', ''))
            if len(pts) == 2:
                boxes.append(_stem_box(pts, 'pedal-stem'))
    for g in root.iter(f'{{{SVG_NS}}}g'):
        c = _cls(g)
        if 'slur' in c or 'tie' in c:
            pts = []
            for p in g.iter(f'{{{SVG_NS}}}path'):
                pts += path_points(p.get('d', ''))
            if pts:
                slurs.append((('tie' if 'tie' in c else 'slur'), g.get('id'), pts))
        if 'dir' in c:
            for t in g.iter(f'{{{SVG_NS}}}text'):
                x0t, y0t = float(t.get('x', 0)), float(t.get('y', 0))
                anchor = t.get('text-anchor', 'start')
                # one box per line: a line starts at the text's x/y or at a tspan that sets its own
                lines, cur = [], [x0t, y0t, '', 0.0]
                for ts in t.iter(f'{{{SVG_NS}}}tspan'):
                    if ts.get('y') is not None:
                        if cur[2].strip():
                            lines.append(cur)
                        cur = [float(ts.get('x', x0t)), float(ts.get('y')), '', 0.0]
                    m = re.match(r'([\d.]+)px', ts.get('font-size', '') or '')
                    if m and ts.text and ts.text.strip():
                        cur[2] += ts.text.strip()
                        cur[3] = max(cur[3], float(m.group(1)))
                if cur[2].strip():
                    lines.append(cur)
                for x, y, txt, size in lines:
                    w = 0.5 * size * len(txt)
                    x0 = x - (w if anchor == 'end' else w / 2 if anchor == 'middle' else 0)
                    boxes.append(Box('text', g.get('id'), x0, y - 0.75 * size, x0 + w, y + 0.2 * size, txt))
        if 'schenker-beam' in c:
            for p in g.iter(f'{{{SVG_NS}}}path'):
                pts = path_points(p.get('d', ''))
                if len(pts) == 2:
                    boxes.append(_stem_box(pts, 'beam-stem'))
        if 'schenker-beam' in c:
            for r in g.iter(f'{{{SVG_NS}}}rect'):
                x, y = float(r.get('x')), float(r.get('y'))
                boxes.append(Box('beam', g.get('id') or 'beam', x, y, x + float(r.get('width')),
                                 y + float(r.get('height'))))
    return slurs, boxes


def collisions(svg: str, pad: float = 20.0, stem_trim: float = 120.0, attach: float = 260.0):
    """[(kind, a, b)] for each slur that runs through a text label, a beam, an added stem (away
    from the stem's own notehead: the first ``stem_trim`` units are where a slur may start), or a
    tie (two curves on top of each other)."""
    slurs, boxes = collect(svg)
    out = []
    for kind, sid, pts in slurs:
        if kind == 'tie':
            continue
        xs = [x for x, _ in pts]
        ends = (min(xs), max(xs))
        for b in boxes:
            bb = b
            if b.kind == 'stem' and any(abs((b.x0 + b.x1) / 2 - e) < attach for e in ends):
                continue            # the slur ends on this stem's note: slurs meet stems there
            if bb.y1 > bb.y0 and bb.hits(pts, pad):
                out.append((f'{kind}-{b.kind}', sid, b.text or b.ident, b.ident))
        for k2, tid, tpts in slurs:
            if k2 != 'tie':
                continue
            near = sum(1 for x, y in pts for u, v in tpts if abs(x - u) < 60 and abs(y - v) < 60)
            if near > 3:
                out.append(('slur-tie', sid, tid, tid))
    return out


STAFF_SPACE = 180      # verovio SVG units per staff space

# glyph boxes in staff spaces at verovio's default glyph scale (0.72), Leipzig font:
# (width, extent above the origin, extent below it); SVG y grows downwards
GLYPHS = {
    'E0A2': (1.75, 0.5, 0.5), 'E0A3': (1.26, 0.5, 0.5), 'E0A4': (1.26, 0.5, 0.5),   # noteheads
    'E260': (0.79, 1.75, 0.7), 'E261': (0.6, 1.4, 1.4), 'E262': (0.95, 1.4, 1.4),    # flat, natural, sharp
    'E240': (1.1, 0.0, 3.3), 'E241': (1.1, 3.3, 0.0),                                 # 8th flags up/down
    'E242': (1.1, 0.0, 3.3), 'E243': (1.1, 3.3, 0.0),
    'E4E4': (1.3, 0.6, 0.1), 'E4E5': (1.22, 1.5, 1.5), 'E4E6': (1.0, 1.0, 1.0),       # rests
}


ACCIDENTALS = {'E260', 'E261', 'E262'}


def _event_boxes(event):
    """Boxes (x0, x1, y0, y1, kind) of the glyphs and dots of one note or rest; kind is 'accid',
    'dot', 'flag', 'head' or 'rest'."""
    out = []
    for use in event.iter(f'{{{SVG_NS}}}use'):
        href = use.get('{http://www.w3.org/1999/xlink}href', '')
        code = href.lstrip('#').split('-')[0]
        mt = re.search(r'translate\(([-\d.]+),\s*([-\d.]+)\)\s*scale\(([-\d.]+)', use.get('transform', ''))
        if not mt or code not in GLYPHS:
            continue
        x, y, sc = float(mt.group(1)), float(mt.group(2)), float(mt.group(3))
        w, up, down = (v * STAFF_SPACE * sc / 0.72 for v in GLYPHS[code])
        kind = ('accid' if code in ACCIDENTALS else 'flag' if code.startswith('E24')
                else 'rest' if code.startswith('E4E') else 'head')
        out.append((x, x + w, y - up, y + down, kind))
    for e in event.iter(f'{{{SVG_NS}}}ellipse'):
        cx, cy, rx = float(e.get('cx')), float(e.get('cy')), float(e.get('rx'))
        out.append((cx - rx, cx + rx, cy - rx, cy + rx, 'dot'))
    return out


def crowded_systems(svg: str, min_gap: float = 1.65, pad: float = 0.12):
    """Systems whose notes are packed too tightly. On some staff either two neighbouring
    noteheads or rests (at different onsets) are less than ``min_gap`` staff spaces apart, or the
    glyphs of neighbouring notes touch: an accidental within ``pad`` staff spaces of the note
    before it (its notehead, flag or dot), or a dot of one note within ``pad`` of the next. Returns (first measure id, last measure id, smallest
    notehead gap in staff spaces)."""
    root = etree.fromstring(svg.encode('utf-8') if isinstance(svg, str) else svg)
    q = lambda el, c: [e for e in el.iter(f'{{{SVG_NS}}}g') if c in _cls(e)]
    P = pad * STAFF_SPACE
    out = []
    for system in q(root, 'system'):
        measures = q(system, 'measure')
        if not measures:
            continue
        rows = {}
        for m in measures:
            for k, staff in enumerate(e for e in m if 'staff' in _cls(e)):
                for ev in q(staff, 'note') + q(staff, 'rest'):
                    if 'note' in _cls(ev) and ev.getparent() is not None \
                            and 'chord' in _cls(ev.getparent()):
                        continue
                    boxes = _event_boxes(ev)
                    heads = [b for b in boxes if b[4] in ('head', 'rest')] or boxes
                    if boxes:
                        rows.setdefault(k, []).append((min(b[0] for b in heads), boxes))
        worst, touch = None, False
        for evs in rows.values():
            evs.sort(key=lambda t: t[0])
            xs = sorted({round(x) for x, _ in evs})
            gaps = [b - a for a, b in zip(xs, xs[1:]) if b - a > 0.2 * STAFF_SPACE]
            if gaps:
                worst = min(gaps) if worst is None else min(worst, min(gaps))
            for (xa, ba), (xb, bb) in zip(evs, evs[1:]):
                if abs(xb - xa) < 0.2 * STAFF_SPACE:
                    continue
                # an accidental running into the note before it, or a dot into the note after
                # it (verovio keeps noteheads and flags apart itself, not these)
                if any(a[0] < b[1] + P and b[0] < a[1] + P and a[2] < b[3] + P and b[2] < a[3] + P
                       for a in ba for b in bb if b[4] == 'accid' or a[4] == 'dot'):
                    touch = True
        if touch or (worst is not None and worst < min_gap * STAFF_SPACE):
            out.append((measures[0].get('id'), measures[-1].get('id'),
                        (worst or 0) / STAFF_SPACE))
    return out
