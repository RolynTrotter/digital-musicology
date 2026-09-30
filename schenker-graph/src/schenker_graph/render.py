"""Render the annotated MEI with verovio and draw the Schenkerian beam on the SVG."""
from __future__ import annotations

import re
from pathlib import Path

import verovio
from lxml import etree

from .mei import Graph, annotate_mei, SVG_NS, XLINK

DEFAULT_OPTIONS = {
    'pageWidth': 2100, 'pageHeight': 2970, 'scale': 40, 'footer': 'none', 'header': 'auto',
    'spacingSystem': 22, 'bottomMarginHeader': 14, 'spacingStaff': 10, 'breaks': 'auto', 'adjustPageHeight': True,
    'svgViewBox': False,
}


def _toolkit(options):
    tk = verovio.toolkit()
    tk.setOptions({**DEFAULT_OPTIONS, **(options or {})})
    return tk


def annotated_mei(score_path, graph: Graph, voice_pitches, options=None) -> str:
    tk = _toolkit(options)
    if not tk.loadFile(str(score_path)):
        raise ValueError(f'verovio could not read {score_path}')
    root = etree.fromstring(tk.getMEI().encode('utf-8'))
    qstamps = {}
    try:
        tk.renderToSVG(1)       # the timemap needs a layout
        for ev in tk.renderToTimemap({'includeMeasures': False, 'includeRests': False}):
            for nid in ev.get('on', []):
                qstamps[nid] = float(ev.get('qstamp', 0.0))
    except Exception:
        qstamps = {}
    annotate_mei(root, graph, voice_pitches, qstamps)
    return etree.tostring(root, xml_declaration=True, encoding='UTF-8').decode('utf-8')


def render(mei: str, graph: Graph, fundamental_ids, options=None) -> list[str]:
    """Render every page; ``fundamental_ids`` is one beamed line (a list of MEI note ids) or a
    list of such lines (e.g. the fundamental line on the original staff and on a reduction staff)."""
    if graph.breaks or graph.break_measures:
        options = {'breaks': 'encoded', **(options or {})}
    tk = _toolkit(options)
    if not tk.loadData(mei):
        raise ValueError('verovio could not load the annotated MEI')
    lines = [fundamental_ids] if fundamental_ids and isinstance(fundamental_ids[0], str) else fundamental_ids
    # a line is a list of ids, or a dict {'ids': [...], 'direction': 'up'|'down', 'color': ...}
    lines = [l if isinstance(l, dict) else {'ids': l} for l in lines]
    lefts = [dict(l, ids=list(l['ids'])) for l in lines]
    pages = []
    for p in range(1, tk.getPageCount() + 1):
        svg = tk.renderToSVG(p)
        for l in lefts:
            if l.get('beam', True) is False:
                svg = draw_stems(svg, graph, l['ids'], l.get('direction', 'up'), l.get('color'), l.get('length', 3.5))
            elif l['ids']:
                before = len(l['ids'])
                svg = draw_beams(svg, graph, l['ids'], l.get('direction', 'up'), l.get('color'),
                                 started=l.get('started', False))
                if len(l['ids']) < before:
                    l['started'] = True
        pages.append(svg)
    return pages


# ------------------------------------------------------------------ SVG geometry helpers

def _cls(el):
    return (el.get('class') or '').split()


def _ancestor(el, cls):
    p = el.getparent()
    while p is not None and cls not in _cls(p):
        p = p.getparent()
    return p


def _translate(use):
    m = re.search(r'translate\(\s*([-\d.]+)[ ,]+([-\d.]+)\)', use.get('transform', ''))
    if m:
        return float(m.group(1)), float(m.group(2))
    return float(use.get('x', 0)), float(use.get('y', 0))


def _path_points(d):
    return [(float(a), float(b)) for a, b in re.findall(r'[ML]\s*([-\d.]+)[ ,]+([-\d.]+)', d)]


def _staff_geometry(staff):
    ys, xs = [], []
    for path in staff.findall(f'{{{SVG_NS}}}path'):
        pts = _path_points(path.get('d', ''))
        if len(pts) == 2 and abs(pts[0][1] - pts[1][1]) < 1e-6:
            ys.append(pts[0][1])
            xs += [pts[0][0], pts[1][0]]
    ys = sorted(ys)[:5]
    if len(ys) < 2:
        return None
    return {'top': ys[0], 'bottom': ys[-1], 'space': (ys[-1] - ys[0]) / (len(ys) - 1),
            'x0': min(xs), 'x1': max(xs)}


def _note_geometry(note_g):
    head = note_g.find(f'.//{{{SVG_NS}}}g[@class="notehead"]/{{{SVG_NS}}}use')
    if head is None:
        return None
    hx, hy = _translate(head)
    stem_x, stem_top = None, None
    for stem in note_g.iter(f'{{{SVG_NS}}}g'):
        if 'stem' in _cls(stem):
            pth = stem.find(f'{{{SVG_NS}}}path')
            if pth is not None:
                pts = _path_points(pth.get('d', ''))
                if len(pts) == 2:
                    (x1, y1), (x2, y2) = pts
                    if min(y1, y2) < hy:            # stem goes up
                        stem_x, stem_top = x1, min(y1, y2)
            break
    return {'hx': hx, 'hy': hy, 'stem_x': stem_x, 'stem_top': stem_top}


def _rows(system):
    """Staff rows of a system (staves are drawn measure by measure), top to bottom."""
    rows = []
    for st in system.iter(f'{{{SVG_NS}}}g'):
        if 'staff' not in _cls(st):
            continue
        g = _staff_geometry(st)
        if not g:
            continue
        for r in rows:
            if abs(r['top'] - g['top']) < 0.5 * g['space']:
                r['x0'], r['x1'] = min(r['x0'], g['x0']), max(r['x1'], g['x1'])
                break
        else:
            rows.append(dict(g))
    return sorted(rows, key=lambda r: r['top'])


def _control_extent(system, row, x0, x1, direction):
    """Outermost point of slurs, directives and brackets on the beam's side of the staff between
    x0 and x1, so the beam clears them. Up: smallest y above the staff; down: largest y below."""
    sp = row['space']
    edge = row['top'] if direction == 'up' else row['bottom']
    lo, hi = (row['top'] - 12 * sp, row['top']) if direction == 'up' else (row['bottom'], row['bottom'] + 12 * sp)
    out = edge
    for el in system.iter(f'{{{SVG_NS}}}g'):
        if not ({'slur', 'dir', 'bracketSpan', 'tuplet', 'ligature', 'dynam', 'tempo'} & set(_cls(el))):
            continue
        for pth in el.iter(f'{{{SVG_NS}}}path'):
            nums = [float(v) for v in re.findall(r'-?\d+(?:\.\d+)?', pth.get('d', ''))]
            for x, y in zip(nums[0::2], nums[1::2]):
                if x0 - sp <= x <= x1 + sp and lo < y < hi:
                    out = min(out, y) if direction == 'up' else max(out, y)
        for t in el.iter(f'{{{SVG_NS}}}text'):
            try:
                x, y = float(t.get('x', 'nan')), float(t.get('y', 'nan'))
            except ValueError:
                continue
            if x0 - sp <= x <= x1 + sp and lo < y < hi:
                out = min(out, y - 1.5 * sp) if direction == 'up' else max(out, y + 0.5 * sp)
    return out


def draw_stems(svg: str, graph: Graph, ids: list[str], direction: str = 'up', color: str | None = None,
               length: float = 3.5) -> str:
    """Extra stems (no beam) on the notes ``ids``: ``length`` staff spaces from the notehead."""
    root = etree.fromstring(svg.encode('utf-8'))
    by_id = {el.get('id'): el for el in root.iter(f'{{{SVG_NS}}}g') if 'note' in _cls(el)}
    color = color or graph.colors.get('pedal', '#6b3fa0')
    hit = False
    for nid in ids:
        g = by_id.get(nid)
        if g is None:
            continue
        staff = _ancestor(g, 'staff')
        geo = _note_geometry(g)
        sg = _staff_geometry(staff) if staff is not None else None
        if geo is None or sg is None:
            continue
        sp = sg['space']
        # notehead width from the glyph's own stem if it has one, else about 1.2 spaces
        w = (geo['stem_x'] - geo['hx']) if geo['stem_x'] is not None and geo['stem_x'] > geo['hx'] else 1.18 * sp
        x = geo['hx'] + w if direction == 'up' else geo['hx'] + 0.05 * sp
        y1 = geo['hy'] - length * sp if direction == 'up' else geo['hy'] + length * sp
        el = etree.SubElement(g.getparent(), f'{{{SVG_NS}}}path')
        el.set('class', 'schenker-stem')
        el.set('d', f"M{x:.1f} {geo['hy']:.1f} L{x:.1f} {y1:.1f}")
        el.set('stroke', color)
        el.set('style', f'stroke:{color}')
        el.set('stroke-width', f'{0.12 * sp:.1f}')
        hit = True
    return etree.tostring(root, encoding='unicode') if hit else svg


def draw_beams(svg: str, graph: Graph, ids_left: list[str], direction: str = 'up', color: str | None = None,
               started: bool = False) -> str:
    """Draw stems and a beam joining the notes ``ids_left`` found on this page (up: stems up and
    the beam above the staff; down: below). ``ids_left`` is the rest of the line in order; notes
    drawn here are removed from it, so the beam can run on from the previous page and to the
    next, and through systems that have none of its notes."""
    root = etree.fromstring(svg.encode('utf-8'))
    by_id = {el.get('id'): el for el in root.iter(f'{{{SVG_NS}}}g') if 'note' in _cls(el)}
    on_page = [i for i in ids_left if i in by_id]
    if not on_page:
        return svg
    color = color or graph.colors['fundamental']
    starts_here = (not started) and ids_left[0] == on_page[0]
    ends_here = len(on_page) == len(ids_left)

    page_systems = [el for el in root.iter(f'{{{SVG_NS}}}g') if 'system' in _cls(el)]
    sys_index = {el.get('id'): i for i, el in enumerate(page_systems)}
    per_sys: dict[int, list] = {}
    row_pos = None
    for nid in on_page:
        g = by_id[nid]
        system, staff = _ancestor(g, 'system'), _ancestor(g, 'staff')
        geo = _note_geometry(g)
        if geo is None or system is None or staff is None:
            continue
        si = sys_index[system.get('id')]
        if row_pos is None:
            sg = _staff_geometry(staff)
            rows = _rows(system)
            row_pos = min(range(len(rows)), key=lambda r: abs(rows[r]['top'] - sg['top']))
        per_sys.setdefault(si, []).append(geo)
    if row_pos is None:
        return svg

    widths = [geo['stem_x'] - geo['hx'] for geo in (_note_geometry(g) for g in by_id.values())
              if geo and geo['stem_x'] is not None]
    head_w = sorted(widths)[len(widths) // 2] if widths else None

    first_sys = min(per_sys) if starts_here else 0
    last_sys = max(per_sys) if ends_here else len(page_systems) - 1
    for si in range(first_sys, last_sys + 1):
        system = page_systems[si]
        rows = _rows(system)
        if row_pos >= len(rows):
            continue
        row = rows[row_pos]
        sp = row['space']
        hw = head_w if head_w is not None else 1.2 * sp
        geos = per_sys.get(si, [])
        for geo in geos:
            if direction == 'up':
                if geo['stem_x'] is None:
                    geo['stem_x'] = geo['hx'] + hw - 0.05 * sp
            else:
                geo['stem_x'] = geo['hx'] + 0.05 * sp
        x_start = geos[0]['stem_x'] if (geos and si == first_sys and starts_here) else row['x0'] + 3.5 * sp
        x_end = geos[-1]['stem_x'] if (geos and si == last_sys and ends_here) else row['x1']
        if direction == 'up':
            ext = min([row['top']] + [g['hy'] for g in geos])
            ext = min(ext, _control_extent(system, row, x_start, x_end, 'up'))
            beam_y = ext - graph.beam_gap * sp
            rect_y = beam_y
        else:
            ext = max([row['bottom']] + [g['hy'] for g in geos])
            ext = max(ext, _control_extent(system, row, x_start, x_end, 'down'))
            beam_y = ext + graph.beam_gap * sp
            rect_y = beam_y - graph.beam_thickness * sp
        layer = etree.SubElement(system, f'{{{SVG_NS}}}g')
        layer.set('class', 'schenker-beam')
        layer.set('color', color)
        for geo in geos:
            st = etree.SubElement(layer, f'{{{SVG_NS}}}path')
            st.set('d', f"M{geo['stem_x']:.1f} {geo['hy']:.1f} L{geo['stem_x']:.1f} {beam_y:.1f}")
            st.set('stroke', color)
            st.set('style', f'stroke:{color}')
            st.set('stroke-width', f'{0.12 * sp:.1f}')
        if x_end - x_start > 1:
            bm = etree.SubElement(layer, f'{{{SVG_NS}}}rect')
            bm.set('x', f'{x_start - 0.06 * sp:.1f}')
            bm.set('y', f'{rect_y:.1f}')
            bm.set('width', f'{x_end - x_start + 0.12 * sp:.1f}')
            bm.set('height', f'{graph.beam_thickness * sp:.1f}')
            bm.set('fill', color)
            bm.set('style', f'fill:{color};stroke:none')
    for i in on_page:
        ids_left.remove(i)
    return etree.tostring(root, encoding='unicode')


# ------------------------------------------------------------------ output

def write_pages(pages: list[str], out_prefix, formats=('svg', 'png', 'pdf'), png_width=1600):
    out_prefix = Path(out_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    written = []
    import cairosvg
    pdf_parts = []
    for i, svg in enumerate(pages, 1):
        stem = out_prefix.with_name(f'{out_prefix.name}_p{i}')
        if 'svg' in formats:
            stem.with_suffix('.svg').write_text(svg)
            written.append(stem.with_suffix('.svg'))
        if 'png' in formats:
            cairosvg.svg2png(bytestring=svg.encode(), write_to=str(stem.with_suffix('.png')),
                             output_width=png_width, background_color='white')
            written.append(stem.with_suffix('.png'))
        if 'pdf' in formats:
            pdf_parts.append(cairosvg.svg2pdf(bytestring=svg.encode()))
    if pdf_parts:
        pdf_path = out_prefix.with_suffix('.pdf')
        try:
            from pypdf import PdfWriter, PdfReader
            import io
            w = PdfWriter()
            for part in pdf_parts:
                for pg in PdfReader(io.BytesIO(part)).pages:
                    w.add_page(pg)
            with open(pdf_path, 'wb') as fh:
                w.write(fh)
        except ImportError:
            if len(pdf_parts) == 1:
                pdf_path.write_bytes(pdf_parts[0])
            else:
                for i, part in enumerate(pdf_parts, 1):
                    out_prefix.with_name(f'{out_prefix.name}_p{i}').with_suffix('.pdf').write_bytes(part)
                pdf_path = None
        if pdf_path:
            written.append(pdf_path)
    return written
