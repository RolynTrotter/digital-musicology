"""Render the annotated MEI with verovio and draw the Schenkerian beam on the SVG."""
from __future__ import annotations

import re
from pathlib import Path

import verovio
from lxml import etree

from .mei import Graph, annotate_mei, SVG_NS, XLINK

DEFAULT_OPTIONS = {
    'pageWidth': 2100, 'pageHeight': 2970, 'scale': 40, 'footer': 'none', 'header': 'auto',
    'spacingSystem': 16, 'bottomMarginHeader': 14, 'spacingStaff': 10, 'breaks': 'auto', 'adjustPageHeight': True,
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
    annotate_mei(root, graph, voice_pitches)
    return etree.tostring(root, xml_declaration=True, encoding='UTF-8').decode('utf-8')


def render(mei: str, graph: Graph, fundamental_ids, options=None) -> list[str]:
    """Render every page; ``fundamental_ids`` is one beamed line (a list of MEI note ids) or a
    list of such lines (e.g. the fundamental line on the original staff and on a reduction staff)."""
    tk = _toolkit(options)
    if not tk.loadData(mei):
        raise ValueError('verovio could not load the annotated MEI')
    lines = [fundamental_ids] if fundamental_ids and isinstance(fundamental_ids[0], str) else fundamental_ids
    lefts = [list(l) for l in lines]
    pages = []
    for p in range(1, tk.getPageCount() + 1):
        svg = tk.renderToSVG(p)
        for ids_left in lefts:
            svg = draw_beams(svg, graph, ids_left)
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


def is_first_hint(si, first_global):
    return si == 0 and first_global


def is_last_hint(si, systems, on_page, total_before):
    return si == len(systems) - 1 and len(on_page) == total_before


def _highest_control(system, sg, x0, x1):
    """Top of slurs and directives that sit above this staff between x0 and x1, so the beam
    clears them."""
    top = sg['top']
    band_lo = sg['top'] - 12 * sg['space']
    for el in system.iter(f'{{{SVG_NS}}}g'):
        c = _cls(el)
        if not ({'slur', 'dir', 'bracketSpan', 'tuplet', 'ligature', 'dynam', 'tempo'} & set(c)):
            continue
        for pth in el.iter(f'{{{SVG_NS}}}path'):
            nums = [float(v) for v in re.findall(r'-?\d+(?:\.\d+)?', pth.get('d', ''))]
            pts = list(zip(nums[0::2], nums[1::2]))
            for x, y in pts:
                if x0 - sg['space'] <= x <= x1 + sg['space'] and band_lo < y < top:
                    top = min(top, y)
        for t in el.iter(f'{{{SVG_NS}}}text'):
            try:
                x, y = float(t.get('x', 'nan')), float(t.get('y', 'nan'))
            except ValueError:
                continue
            if x0 <= x <= x1 and band_lo < y < top:
                top = min(top, y - 1.5 * sg['space'])
    return top


def draw_beams(svg: str, graph: Graph, ids_left: list[str]) -> str:
    """Draw stems and a beam for the fundamental notes found on this page. ``ids_left`` is the
    remaining fundamental line in order; notes drawn here are removed from it, so the beam can
    show that it continues from the previous page or on to the next."""
    root = etree.fromstring(svg.encode('utf-8'))
    by_id = {el.get('id'): el for el in root.iter(f'{{{SVG_NS}}}g') if 'note' in _cls(el)}
    on_page = [i for i in ids_left if i in by_id]
    if not on_page:
        return svg
    first_global = ids_left and ids_left[0] == on_page[0]
    total_before = len(ids_left)
    systems: list[tuple] = []          # (system_el, staff_el, [geom...])
    for nid in on_page:
        g = by_id[nid]
        staff = _ancestor(g, 'staff')
        system = _ancestor(g, 'system')
        geo = _note_geometry(g)
        if geo is None or staff is None or system is None:
            continue
        geo['id'] = nid
        if systems and systems[-1][0].get('id') == system.get('id'):
            systems[-1][2].append(geo)
        else:
            systems.append((system, staff, [geo]))

    # head width from any up-stemmed note on the page (stem sits at the head's right edge)
    widths = []
    for g in by_id.values():
        geo = _note_geometry(g)
        if geo and geo['stem_x'] is not None:
            widths.append(geo['stem_x'] - geo['hx'])
    head_w = sorted(widths)[len(widths) // 2] if widths else None

    color = graph.colors['fundamental']
    # systems on this page that the line passes through without a fundamental note
    page_systems = [el for el in root.iter(f'{{{SVG_NS}}}g') if 'system' in _cls(el)]
    sys_index = {el.get('id'): i for i, el in enumerate(page_systems)}
    first_sys = sys_index[systems[0][0].get('id')] if systems else 0
    last_sys = sys_index[systems[-1][0].get('id')] if systems else -1
    more_after = len(on_page) < total_before
    lo = 0 if not first_global else first_sys
    hi = len(page_systems) - 1 if more_after else last_sys
    have = {s_[0].get('id') for s_ in systems}
    staff_pos = None
    if systems:
        # which staff of the system carries the line: same order index as in the first system
        st_list = [el for el in systems[0][0].iter(f'{{{SVG_NS}}}g') if 'staff' in _cls(el)]
        first_measure_staves = []
        for el in st_list:
            geo_ = _staff_geometry(el)
            if geo_ and all(abs(geo_['top'] - t) > 1 for t in first_measure_staves):
                first_measure_staves.append(geo_['top'])
        first_measure_staves.sort()
        sg0 = _staff_geometry(systems[0][1])
        staff_pos = first_measure_staves.index(min(first_measure_staves, key=lambda t: abs(t - sg0['top'])))
    for i in range(lo, hi + 1):
        el = page_systems[i]
        if el.get('id') in have or staff_pos is None:
            continue
        tops, geos_ = [], []
        for st in el.iter(f'{{{SVG_NS}}}g'):
            if 'staff' in _cls(st):
                geo_ = _staff_geometry(st)
                if geo_:
                    geos_.append(geo_)
        levels = sorted({round(g_['top']) for g_ in geos_})
        if staff_pos >= len(levels):
            continue
        top = levels[staff_pos]
        row = [g_ for g_ in geos_ if abs(g_['top'] - top) < 1]
        sgx = {'top': top, 'space': row[0]['space'], 'x0': min(g_['x0'] for g_ in row),
               'x1': max(g_['x1'] for g_ in row)}
        highest = min(top, _highest_control(el, sgx, sgx['x0'], sgx['x1']))
        beam_y = highest - graph.beam_gap * sgx['space']
        layer = etree.SubElement(el, f'{{{SVG_NS}}}g')
        layer.set('class', 'schenker-beam')
        layer.set('color', color)
        bm = etree.SubElement(layer, f'{{{SVG_NS}}}rect')
        bm.set('x', f"{sgx['x0'] + 3.5 * sgx['space']:.1f}")
        bm.set('y', f'{beam_y:.1f}')
        bm.set('width', f"{sgx['x1'] - sgx['x0'] - 3.5 * sgx['space']:.1f}")
        bm.set('height', f"{graph.beam_thickness * sgx['space']:.1f}")
        bm.set('fill', color)
    all_ids = on_page
    for si, (system, staff, geos) in enumerate(systems):
        sg = _staff_geometry(staff)
        if sg is None:
            continue
        # staves are drawn measure by measure: take the line's full width across the system
        for other in system.iter(f'{{{SVG_NS}}}g'):
            if 'staff' in _cls(other):
                og = _staff_geometry(other)
                if og and abs(og['top'] - sg['top']) < 0.5 * sg['space']:
                    sg['x0'] = min(sg['x0'], og['x0'])
                    sg['x1'] = max(sg['x1'], og['x1'])
        sp = sg['space']
        hw = head_w if head_w is not None else 1.2 * sp
        for geo in geos:
            if geo['stem_x'] is None:
                geo['stem_x'] = geo['hx'] + hw - 0.05 * sp
                geo['stem_top'] = geo['hy']
        highest = min(min(g['hy'] for g in geos), sg['top'])
        highest = min(highest, _highest_control(system, sg, geos[0]['stem_x'] if is_first_hint(si, first_global) else sg['x0'],
                                                geos[-1]['stem_x'] if is_last_hint(si, systems, on_page, total_before) else sg['x1']))
        beam_y = highest - graph.beam_gap * sp
        thick = graph.beam_thickness * sp
        layer = etree.SubElement(system, f'{{{SVG_NS}}}g')
        layer.set('class', 'schenker-beam')
        layer.set('color', color)
        for geo in geos:
            st = etree.SubElement(layer, f'{{{SVG_NS}}}path')
            st.set('d', f"M{geo['stem_x']:.1f} {geo['hy']:.1f} L{geo['stem_x']:.1f} {beam_y:.1f}")
            st.set('stroke', color)
            st.set('style', f'stroke:{color}')
            st.set('stroke-width', f'{0.12 * sp:.1f}')
        x_start = geos[0]['stem_x']
        x_end = geos[-1]['stem_x']
        # continues from an earlier system / page, or on to a later one
        is_first_of_line = (si == 0 and first_global)
        is_last_of_line = (si == len(systems) - 1 and len(on_page) == total_before)
        if not is_first_of_line:
            x_start = sg['x0'] + 3.5 * sp
        if not is_last_of_line:
            x_end = sg['x1']
        if x_end - x_start > 1:
            bm = etree.SubElement(layer, f'{{{SVG_NS}}}rect')
            bm.set('x', f'{x_start - 0.06 * sp:.1f}')
            bm.set('y', f'{beam_y:.1f}')
            bm.set('width', f'{x_end - x_start + 0.12 * sp:.1f}')
            bm.set('height', f'{thick:.1f}')
            bm.set('fill', color)
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
