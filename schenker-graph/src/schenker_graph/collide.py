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
