"""Read T. B. Payne's DIAMM edition of F fascicle 5 (Finale vector PDF) into edition encodings.

Usage: python tools/payne_pdf.py F-Fascicle-5-Clausulae-a2-2026.pdf --out editions_payne

The edition is at https://www.diamm.ac.uk/documents/712/ ; its encodings are for local research use
and are not part of this repository.

The PDF keeps every music glyph as a character in the Maestro font, so notes are read from glyph
identity and position rather than from pixels:

* staves: 5 horizontal 0.3pt lines; systems: the blue-grey system bracket at the left margin;
  pieces: the blue header "N. F, f. 147r, I: ..." above their first system
* pitch: the notehead glyph's baseline sits on its staff position (half a space per step)
* value: notehead (quarter-type œ, half ˙, whole w) + stem + flags (J/j) or beams (filled black
  quadrilaterals at the stem end) + augmentation dots; rests Œ (4) and ‰ (2) with dots
* only black glyphs are notes; red is editorial apparatus (strokes, ficta, parenthesised notes)
* small noteheads (11.8pt) are Payne's plica notes

Values are in sixteenths as in ligature-rhythm (B = 2, L = 4, L. = 6). A stemless notehead or a
whole note is unmeasured (organal or final notes) and is kept with ``measured=False``.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

import pdfplumber

STEPS = 'CDEFGAB'
# bottom staff line as (step index, octave) for each clef glyph
CLEF_BOTTOM = {'V': (2, 3), '&': (2, 4), '?': (4, 2)}
HEADER = re.compile(r'^(\d+)\.\s+F, f\.\s*(\d+[rv]),\s*([IVX]+)(?:,\s*(\d+))?:\s*(.*)$')


def _black(c) -> bool:
    col = c.get('non_stroking_color')
    if col is None:
        return True
    col = tuple(col) if isinstance(col, (list, tuple)) else (col,)
    return all(abs(v) < 0.15 for v in col)


@dataclass
class Ev:
    sys: int                       # system index within the piece
    x: float
    dur: int                       # sixteenths (0 for unmeasured)
    pitch: tuple | None            # (step, alter, octave)
    measured: bool = True
    small: bool = False
    glyph: str = ''
    y: float = 0.0
    page: int = 0


@dataclass
class Piece:
    no: int
    folio: str
    system: str
    sub: str | None
    title: str
    page: int
    voices: dict = field(default_factory=lambda: {'D': [], 'T': []})
    warnings: list = field(default_factory=list)
    nsys: int = 0


# --------------------------------------------------------------------------- page geometry
def staves_of(page):
    hs = [l for l in page.lines if abs(l['top'] - l['bottom']) < 0.2 and l['x1'] - l['x0'] > 60
          and l['linewidth'] < 0.6 and _black_line(l)]
    rows = defaultdict(list)
    for l in hs:
        rows[round(l['top'], 1)].append(l)
    ys = sorted(rows)
    out, i = [], 0
    while i + 4 < len(ys):
        g = ys[i:i + 5]
        d = [g[k + 1] - g[k] for k in range(4)]
        if max(d) - min(d) < 0.3 and 2.5 < d[0] < 6:
            x0 = min(l['x0'] for l in rows[g[0]])
            x1 = max(l['x1'] for l in rows[g[0]])
            out.append(dict(top=g[0], bottom=g[4], sp=(g[4] - g[0]) / 4, x0=x0, x1=x1))
            i += 5
        else:
            i += 1
    return out


def _black_line(l):
    col = l.get('stroking_color')
    if col is None:
        return True
    col = tuple(col) if isinstance(col, (list, tuple)) else (col,)
    return all(abs(v) < 0.15 for v in col)


def systems_of(page, staves):
    """pair staves into two-staff systems using the system brackets"""
    br = [c for c in page.curves if c.get('fill') and len(c['pts']) == 6 and c['x1'] - c['x0'] < 12
          and c['bottom'] - c['top'] > 20 and c['x0'] < 120]
    out = []
    for b in sorted(br, key=lambda c: c['top']):
        inside = [s for s in staves if s['top'] >= b['top'] - 3 and s['bottom'] <= b['bottom'] + 3]
        if len(inside) == 2:
            out.append(inside)
    return out


def headers_of(page, pno):
    out = []
    for ln in page.extract_text_lines():
        m = HEADER.match(ln['text'])
        if m:
            out.append(dict(no=int(m.group(1)), folio=m.group(2), system=m.group(3), sub=m.group(4),
                            title=m.group(5), page=pno, top=ln['top']))
    return out


# --------------------------------------------------------------------------- one staff
def read_staff(page, staff, glyphs, vlines, beams, sysno, pno, warn):
    sp = staff['sp']
    half = sp / 2
    H = page.height
    lo, hi = staff["top"] - 5.5 * sp, staff["bottom"] + 5.5 * sp

    def base(c):
        return H - c['matrix'][5]

    mine = [c for c in glyphs if lo <= base(c) <= hi]
    clef = [c for c in mine if c['text'] in CLEF_BOTTOM and c['size'] > 12]
    if not clef:
        warn(f'p{pno}: staff at {staff["top"]:.0f} has no clef')
        return []
    clef = min(clef, key=lambda c: c['x0'])
    bstep, boct = CLEF_BOTTOM[clef['text']]
    cx = clef['matrix'][4]

    def pitch_at(y):
        k = round((staff['bottom'] - y) / half)
        n = bstep + k
        return STEPS[n % 7], boct + n // 7

    heads = sorted([c for c in mine if c['text'] in ('œ', '˙', 'w') and c['matrix'][4] > cx + 5],
                   key=lambda c: c['matrix'][4])
    first_x = heads[0]['matrix'][4] if heads else 1e9
    # key signature: flats between clef and first note, close to the clef
    keysig = set()
    for c in mine:
        if c['text'] == 'b' and cx < c['matrix'][4] < min(cx + 30, first_x - 3):
            keysig.add(pitch_at(base(c))[0])
    accs = [c for c in mine if c['text'] in ('b', 'n', '#') and c['matrix'][4] > cx + 5
            and c['size'] > 12]
    dots = [c for c in mine if c['text'] == '.' and c['size'] > 8]
    flags = [c for c in mine if c['text'] in ('J', 'j')]
    rests = [c for c in mine if c['text'] in ('Œ', '‰', '∑') and c['matrix'][4] > cx + 5]

    events = []
    for c in heads:
        x, y = c['matrix'][4], base(c)
        small = c['size'] < 13
        w = 7.0 * c['size'] / 16.8          # notehead width
        step, octv = pitch_at(y)
        alter = -1 if step in keysig else 0
        for a in accs:
            ax, ay = a['matrix'][4], base(a)
            if x - 12 < ax < x - 1 and abs(ay - y) < half * 1.2:
                alter = {'b': -1, 'n': 0, '#': 1}[a['text']]
        # stem: a vertical line touching the notehead at its left or right edge
        stem = None
        for v in vlines:
            if x - 0.8 <= v['x0'] <= x + w + 0.8 and v['top'] - 1.5 <= y <= v['bottom'] + 1.5 \
                    and v['bottom'] - v['top'] > 2.5 * sp * (0.7 if small else 1):
                stem = v
                break
        if c['text'] == 'w':
            dur, measured = 0, False
        elif stem is None:
            dur, measured = 0, False
        else:
            nflag = sum(1 for f in flags if abs(f['matrix'][4] - stem['x0']) < 1.2 and
                        stem['top'] - 3 <= base(f) <= stem['bottom'] + 3)
            end_y = stem['top'] if abs(stem['bottom'] - y) < abs(stem['top'] - y) else stem['bottom']
            sx = stem['x0']
            nbeam = 0
            for b in beams:
                if b['x0'] - 0.8 <= sx <= b['x1'] + 0.8 and b['top'] - 2.0 <= end_y <= b['bottom'] + 2.0:
                    nbeam += 1
                elif b['x0'] - 0.8 <= sx <= b['x1'] + 0.8 and b['kind'] == 'poly':
                    # sloped beam: interpolate its edge at the stem
                    yb = b['ya'] + (b['yb'] - b['ya']) * (sx - b['x0']) / max(1e-6, b['x1'] - b['x0'])
                    if abs(yb - end_y) < 3.2 * (sp / 4.2) + 1.2 * nbeam * 0 + 1.5:
                        nbeam += 1
            n = max(nflag, nbeam)
            base_val = 8 if c['text'] == '˙' else {0: 4, 1: 2, 2: 1}.get(n, 1)
            dur, measured = base_val, True
        # dots right of the notehead
        nd = sum(1 for d in dots if x + w - 0.5 < d['matrix'][4] < x + w + 6 and
                 -1.0 <= y - base(d) <= half + 1.0)
        if measured and nd:
            dur = dur * 3 // 2 if nd == 1 else dur * 7 // 4
        events.append(Ev(sysno, x, dur, (step, alter, octv), measured, small, c['text'], y, pno))
    for r in rests:
        x, y = r['matrix'][4], base(r)
        if r['text'] == '∑':
            events.append(Ev(sysno, x, 0, None, False, False, '∑', y, pno))
            continue
        dur = 4 if r['text'] == 'Œ' else 2
        rw = 6.0
        nd = sum(1 for d in dots if x + 2 < d['matrix'][4] < x + rw + 6 and abs(base(d) - y) < sp * 2.5)
        if nd:
            dur = dur * 3 // 2
        events.append(Ev(sysno, x, dur, None, True, False, r['text'], y, pno))
    events.sort(key=lambda e: e.x)
    return events


def beams_of(page):
    out = []
    for r in page.rects:
        if r.get('fill') and _black(r) and r['x1'] - r['x0'] > 4 and 1.2 < r['bottom'] - r['top'] < 3.5:
            out.append(dict(x0=r['x0'], x1=r['x1'], top=r['top'], bottom=r['bottom'], kind='rect'))
    for c in page.curves:
        if c.get('fill') and _black(c) and len(c['pts']) in (4, 5) and c['x1'] - c['x0'] > 4:
            pts = c['pts']
            xs = sorted(set(round(p[0], 1) for p in pts))
            if len(xs) < 2:
                continue
            left = [p[1] for p in pts if abs(p[0] - c['x0']) < 0.3]
            right = [p[1] for p in pts if abs(p[0] - c['x1']) < 0.3]
            if not left or not right:
                continue
            thick = max(left) - min(left)
            if not 1.0 < thick < 3.5:
                continue
            H = page.height
            # pdfplumber pts are in top-based coordinates
            out.append(dict(x0=c['x0'], x1=c['x1'], top=c['top'], bottom=c['bottom'], kind='poly',
                            ya=(min(left) + max(left)) / 2, yb=(min(right) + max(right)) / 2))
    return out


# --------------------------------------------------------------------------- whole document
def read_page(args):
    pdf_path, pno = args
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[pno - 1]
        staves = staves_of(page)
        systems = systems_of(page, staves)
        heads = headers_of(page, pno)
        glyphs = [c for c in page.chars if 'Maestro' in c['fontname'] and _black(c)]
        vlines = [l for l in page.lines if abs(l['x0'] - l['x1']) < 0.2 and _black_line(l)]
        vlines += [dict(x0=r['x0'], top=r['top'], bottom=r['bottom']) for r in page.rects
                   if r['x1'] - r['x0'] < 1.0 and r['bottom'] - r['top'] > 5 and _black(r)]
        beams = beams_of(page)
        H = page.height
        out = []
        for h in heads:
            out.append(('h', h['top'], h))
        for d_st, t_st in systems:
            mid = (d_st['bottom'] + t_st['top']) / 2
            gd = [c for c in glyphs if H - c['matrix'][5] < mid]
            gt = [c for c in glyphs if H - c['matrix'][5] >= mid]
            warns = []
            D = read_staff(page, d_st, gd, vlines, beams, -1, pno, warns.append)
            T = read_staff(page, t_st, gt, vlines, beams, -1, pno, warns.append)
            out.append(('s', d_st['top'], dict(D=D, T=T, warns=warns)))
        return sorted(out, key=lambda t: t[1])


def read(pdf_path, pages=None, workers=None):
    from concurrent.futures import ProcessPoolExecutor
    with pdfplumber.open(pdf_path) as pdf:
        n = len(pdf.pages)
    rng = list(pages or range(1, n + 1))
    with ProcessPoolExecutor(workers) as ex:
        results = list(ex.map(read_page, [(pdf_path, p) for p in rng]))
    pieces, cur = [], None
    for items in results:
        for kind, top, obj in items:
            if kind == 'h':
                cur = Piece(obj['no'], obj['folio'], obj['system'], obj['sub'], obj['title'], obj['page'])
                pieces.append(cur)
            elif cur is not None:
                for v in 'DT':
                    for e in obj[v]:
                        e.sys = cur.nsys
                    cur.voices[v] += obj[v]
                cur.warnings += obj['warns']
                cur.nsys += 1
    return pieces


# --------------------------------------------------------------------------- discant sections
@dataclass
class Section:
    piece: int
    k: int
    D: list
    T: list
    offset: int            # onset of the duplum's first event on the tenor's clock
    agree: int             # x-coincident pairs whose onsets agree
    pairs: int
    order_bad: int


def _key(e):
    return (e.sys, e.x)


def sections(piece, min_t=3, min_d=6):
    """measured stretches: tenor runs between unmeasured notes, the duplum over the same span"""
    T, D = piece.voices['T'], piece.voices['D']
    runs, cur = [], []
    for e in T:
        if e.measured:
            cur.append(e)
        else:
            if cur:
                runs.append((cur, _key(e)))
            cur = []
    if cur:
        runs.append((cur, (1e9, 0)))
    out = []
    for k, (trun, end) in enumerate(runs):
        start = _key(trun[0])
        # the duplum may start a little before the tenor's first event only via x-coincidence
        dsel = [e for e in D if start[0] < e.sys or (start[0] == e.sys and e.x >= start[1] - 0.8)]
        dsel = [e for e in dsel if _key(e) < end]
        # stop both voices at the first unmeasured duplum note
        for i, e in enumerate(dsel):
            if not e.measured:
                cut = _key(e)
                dsel = dsel[:i]
                trun = [t for t in trun if _key(t) < cut]
                break
        while trun and trun[-1].pitch is None:
            trun = trun[:-1]
        while dsel and dsel[-1].pitch is None:
            dsel = dsel[:-1]
        if sum(1 for e in trun if e.pitch) < min_t or sum(1 for e in dsel if e.pitch) < min_d:
            continue
        # onsets on each voice's own clock
        def clock(ev):
            t, r = 0, []
            for e in ev:
                r.append(t)
                t += e.dur
            return r
        ot, od = clock(trun), clock(dsel)
        from collections import Counter
        diffs = Counter()
        pairs = []
        for i, d in enumerate(dsel):
            for j, t in enumerate(trun):
                if d.sys == t.sys and abs(d.x - t.x) < 0.8:
                    diffs[ot[j] - od[i]] += 1
                    pairs.append((i, j))
        if not diffs:
            continue
        off, agree = diffs.most_common(1)[0]
        bad = 0
        for i, d in enumerate(dsel):
            for j, t in enumerate(trun):
                if d.sys == t.sys and abs(d.x - t.x) > 2.0:
                    if (d.x < t.x) != (od[i] + off < ot[j]) and od[i] + off != ot[j]:
                        bad += 1
        out.append(Section(piece.no, k, dsel, trun, off, agree, len(pairs), bad))
    return out


# --------------------------------------------------------------------------- command line
def write_sections(pieces, out):
    """MusicXML (duplum, tenor; 3/8) for every section whose staves agree in time, plus index.json"""
    import json
    from pathlib import Path
    from ligature_rhythm.musicxml import write
    from ligature_rhythm.realise import Event
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    meta = {}
    for p in pieces:
        secs = sections(p)
        for s in secs:
            if not (s.agree == s.pairs and s.order_bad == 0):
                continue
            def evs(voice, start):
                t, r = start, []
                for e in voice:
                    if e.pitch is not None:
                        r.append(Event(t, e.dur, e.pitch, None, e.small))
                    t += e.dur
                return r
            t0 = max(0, -s.offset)
            D, T = evs(s.D, s.offset + t0), evs(s.T, t0)
            name = f'F5_{p.no:03d}{"abcdefgh"[s.k] if len(secs) > 1 else ""}'
            write(out / f'{name}.xml', D, T,
                  title=f'{p.no}. F {p.folio} {p.system}: {p.title.split("[")[0].strip()}',
                  subtitle='from T. B. Payne, F fasc. 5 (DIAMM 2026)')
            meta[name] = dict(no=p.no, section=s.k, folio=p.folio, system=p.system, sub=p.sub,
                              title=p.title, page=p.page, nD=len(D), nT=len(T), pairs_checked=s.pairs)
    (out / 'index.json').write_text(json.dumps(meta, indent=1))
    return meta


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('pdf')
    ap.add_argument('--out', default='editions_payne')
    ap.add_argument('--workers', type=int)
    a = ap.parse_args()
    ps = read(a.pdf, workers=a.workers)
    meta = write_sections(ps, a.out)
    n = sum(len(sections(p)) for p in ps)
    print(f'{len(ps)} pieces, {n} measured sections, {len(meta)} written (staves agree note for note)')
