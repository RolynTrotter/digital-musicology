"""Build a graph specification from a melodic-reduction analysis, and the one-call API."""
from __future__ import annotations

import json
from pathlib import Path

from .mei import Graph, staff_notes
from .render import annotated_mei, render, write_pages

LICENSED = {'PASS', 'FILL', 'NEI', 'NEI_LEAP', 'INC_L', 'INC_R'}


def _pitch_label(p):
    return p.replace('-', '♭').replace('#', '♯')


def graph_from_analysis(a: dict, middleground='auto', focal=True, modules=4, slurs=True,
                        label_focal=True, staff=None, module_brackets=False) -> Graph:
    """``middleground``: 'auto' (a quarter of the fundamental line's span threshold), 'span:T',
    or None. ``modules``: how many module groups to bracket (0 for none)."""
    notes = a['notes']
    fund = list(a['fundamental']['notes'])
    fset = set(fund)
    g = Graph(staff=(staff if staff is not None else a.get('part', 0) + 1), fundamental=fund)

    mid = []
    if middleground:
        if middleground == 'auto':
            T = min(notes[i]['span_units'] for i in fund) / 4 if fund else 4
        else:
            T = float(str(middleground).split(':')[1])
        mid = [n['idx'] for n in notes if n['span_units'] >= T and n['idx'] not in fset]
    g.middleground = mid
    shown = fset | set(mid)

    if slurs:
        seen = set()
        for k in mid:
            n = notes[k]
            i, j = n['parent']
            if i is None or j is None or n['relation'] not in LICENSED:
                continue
            if (i, j) in seen:
                continue
            seen.add((i, j))
            g.slurs.append({'from': i, 'to': j, 'style': 'solid', 'place': 'below'})

    if focal:
        for span in a.get('focal_pitches', []):
            if not span.get('focal', True) or span.get('inside_focal', span.get('inside')):
                continue
            mem = [m for m in span['members'] if m in shown] or span['members']
            solid = {(x['from'], x['to']) for x in g.slurs}
            for x, y in zip(mem, mem[1:]):
                if (x in fset and y in fset) or (x, y) in solid:
                    continue          # the beam or a prolongation slur already joins them
                g.slurs.append({'from': x, 'to': y, 'style': 'dashed', 'place': 'below'})
            if label_focal:
                g.labels.append({'at': span['first'], 'place': 'below',
                                 'text': f"{_pitch_label(span['pitch'])} focal, {span['returns']} returns"})

    for m in a.get('modules', [])[:modules]:
        if m.get('varied'):
            continue
        for o in m['occurrences']:
            t = o['transposition_steps']
            txt = m['label'] + (f' ({t:+d})' if t else '')
            if module_brackets:
                g.brackets.append({'from': o['first'], 'to': o['last'], 'text': txt, 'place': 'above'})
            else:
                g.labels.append({'at': o['first'], 'text': txt, 'place': 'above', 'size': 'small', 'bold': True})
    return g


def _dep_slur(k, pi, pj):
    """The slur that shows note k's place in its group: over its parent interval when it has
    both ends, else from k to the note it leads to (or from the note it follows)."""
    if pi is not None and pj is not None:
        return pi, pj
    if pj is not None:
        return k, pj
    if pi is not None:
        return pi, k
    return None


def thin_slurs(graph: Graph, max_stack: int = 3) -> int:
    """Hide slurs (``hidden``: kept in the graph and the analysis, not printed) where more than
    ``max_stack`` would stack up on one side of a staff. A slur's height is 1 if it encloses no
    other slur on its side, else 1 + the largest height it encloses. The innermost ``max_stack``
    - 1 layers (the notes' own elaborations) and the outermost slur of each nest (the span of
    the ordo or group) stay; the layers between are hidden. Returns the number hidden."""
    hidden = 0
    for place in ('above', 'below'):
        ss = [s for s in graph.slurs if s.get('place', 'below') == place and s['from'] != s['to']]
        span = [tuple(sorted((s['from'], s['to']))) for s in ss]
        inside = lambda i, j: (span[j][0] <= span[i][0] and span[i][1] <= span[j][1]
                               and span[i] != span[j])          # i inside j
        height = {}
        for i in sorted(range(len(ss)), key=lambda i: span[i][1] - span[i][0]):
            height[i] = 1 + max((height[j] for j in height if inside(j, i)), default=0)
        for i, s in enumerate(ss):
            outer = not any(inside(i, j) for j in range(len(ss)))
            s['hidden'] = (not outer) and height[i] >= max_stack
            hidden += s['hidden']
    return hidden


def system_load(notes, ref_notes, m0, m1):
    """How much a system from measure m0 to m1 has to hold: the distinct onsets of both voices
    plus one per bar (barlines, rests). About 56 fits an A4 system at the default scale."""
    on = {n['onset'] for n in list(notes) + list(ref_notes or []) if m0 <= n['measure'] <= m1}
    return len(on) + (m1 - m0 + 1)


def _make_splitter(a: dict):
    """A function (m0, m1) -> the measure at which to split the system m0..m1 in two: a pair
    boundary if one is near the middle, else an ordo boundary, cutting the fewest ordines of
    either voice."""
    notes = a['notes']
    rv = a.get('reference_voice') or {}
    ref = rv.get('notes', [])

    def walk(x):
        yield x
        for c in x['children']:
            yield from walk(c)
    starts = {}
    for x in walk(a['groups']):
        if x['level'] in (1, 2):
            m = notes[x['first']]['measure']
            starts[m] = min(starts.get(m, 9), 0 if x['level'] == 2 else 1)
    ords = [(notes[x['first']]['measure'], notes[x['last']]['measure'])
            for x in walk(a['groups']) if x['level'] == 1]
    if rv.get('groups'):
        ords += [(ref[x['first']]['measure'], ref[x['last']]['measure'])
                 for x in walk(rv['groups']) if x['level'] == 1]
    for f, _ in ords:
        starts.setdefault(f, 2)          # the tenor's ordo starts, last resort

    def split(m0, m1):
        total = system_load(notes, ref, m0, m1)
        best = None
        for m, prio in starts.items():
            if not (m0 + 2 <= m <= m1 - 1):
                continue
            left, right = system_load(notes, ref, m0, m - 1), system_load(notes, ref, m, m1)
            cut = sum(1 for f, l in ords if f < m <= l)
            cost = 2 * prio + cut + 3 * abs(left - right) / total
            if best is None or cost < best[0]:
                best = (cost, m)
        return best[1] if best else None
    return split


def graph_from_tree(a: dict, slurs='all', labels=True, sections=True, reference=True,
                    staff=None, max_slur_level=None, pedal_stems=True, system_breaks=True,
                    max_slur_stack=3, max_system_load=60, substems=True,
                    substem_length=5.5) -> Graph:
    """Overlays for a grouped-tree analysis (method 'tree').

    * fundamental line: red, stems and beam (above the duplum; below the tenor);
    * heads of ordines and higher groups: blue noteheads;
    * slurs: every note's place in its group. Inside an ordo (the foreground) they go below the
      staff; between the heads of ordines and pairs above it, up to ``max_slur_level`` (default:
      the fundamental line's level; higher connections are what the beam shows).
      ``slurs='upper'`` keeps only the slurs above, ``None`` none. On the tenor only the
      connections between pair heads are slurred;
    * ``substems``: the top level of connections (the fundamental line's level) is drawn as
      sub-stems (``substem_length`` staff spaces, up on the duplum, down on the tenor) on the
      notes it joins, instead of slurs;
    * labels: the pair (module) letters above the staff, and at each pair of pairs its home note
      and pedal pitch below it.
    """
    notes = a['notes']
    fund = sorted(a['fundamental']['notes'])
    fset = set(fund)
    g = Graph(staff=(staff if staff is not None else a.get('part', 0) + 1), fundamental=fund,
              voice_pitches=[n['pitch'] for n in notes], voice_onsets=[n['onset'] for n in notes])
    g.middleground = [n['idx'] for n in notes if n['level'] >= 1 and n['idx'] not in fset]
    g.colors.setdefault('foreground', '#7a8fa8')

    def add_slurs(target, deps, lower_place, upper_place, keep_levels, stem_level=None,
                  stem_dir='up'):
        """Slurs for the dependencies at ``keep_levels``; those at ``stem_level`` (the top level)
        become sub-stems on the notes they join instead (Schenker's middleground stems)."""
        seen, stemmed = {}, set()
        for d in deps:
            if d['level'] not in keep_levels:
                continue
            sl = _dep_slur(d['note'], *d['parent'])
            if sl is None or sl[0] == sl[1]:
                continue
            if d['level'] == stem_level:
                stemmed.update(sl)
                continue
            seen[sl] = max(seen.get(sl, 0), d['level'])
        for (x, y), lev in sorted(seen.items()):
            if lev <= 1:
                target.slurs.append({'from': x, 'to': y, 'style': 'solid', 'place': lower_place,
                                     'color': target.colors['foreground']})
            else:
                target.slurs.append({'from': x, 'to': y, 'style': 'solid', 'place': upper_place,
                                     'color': target.colors['slur']})
        stemmed -= set(target.fundamental)
        if stemmed:
            target.middleground = sorted(set(target.middleground) | stemmed)
            target.stems.append({'notes': sorted(stemmed), 'direction': stem_dir,
                                 'length': substem_length, 'kind': 'substem'})

    top_slur = max_slur_level or a['fundamental'].get('level', 3)
    levels_all = {d['level'] for d in a['dependencies'] if d['level'] <= top_slur}
    if slurs:
        keep = levels_all if slurs == 'all' else {L for L in levels_all if L >= 2}
        add_slurs(g, a['dependencies'], 'below', 'above', keep,
                  stem_level=top_slur if substems and top_slur >= 2 else None, stem_dir='up')

    if pedal_stems:
        # the piece's pedal: the pitch that is the pedal of the most pairs of pairs (at least two);
        # its ordo heads get an extra up-stem (down-stem for a lower pedal)
        from collections import Counter
        cnt = Counter((sec['pedal']['pitch'], sec['pedal']['position'])
                      for sec in a.get('sections', []) if sec.get('pedal'))
        ped, pos = [], 'upper'
        if cnt and cnt.most_common(1)[0][1] >= 2:
            (pp, pos), _ = cnt.most_common(1)[0]
            ped = sorted({k for sec in a['sections'] if sec.get('pedal') and sec['pedal']['pitch'] == pp
                          for k in sec.get('pedal_notes', [])} - fset)
        if ped:
            g.colors.setdefault('pedal', '#6b3fa0')
            g.stems.append({'notes': ped, 'direction': 'up' if pos == 'upper' else 'down',
                            'length': 4.5})
    if system_breaks:
        # one system per pair of pairs (per pair when a pair of pairs is long): ordines never
        # straddle a system break, so the foreground slurs stay whole
        def walkg(x):
            yield x
            for c in x['children']:
                yield from walkg(c)
        pops = [x for x in walkg(a['groups']) if x['level'] == 3] or \
               [x for x in walkg(a['groups']) if x['level'] == 2]
        if pops:
            lens = [notes[x['last']]['onset'] + notes[x['last']]['dur'] - notes[x['first']]['onset'] for x in pops]
            med = sorted(lens)[len(lens) // 2]
            for x, L in zip(pops, lens):
                g.breaks.append(x['first'])
                if L > 1.3 * med:
                    # a long pair of pairs: fill systems pair by pair up to the usual length
                    start = notes[x['first']]['onset']
                    for c in x['children'][1:]:
                        c_end = notes[c['last']]['onset'] + notes[c['last']]['dur']
                        if c_end - start > 1.1 * med:
                            g.breaks.append(c['first'])
                            start = notes[c['first']]['onset']
            g.breaks = sorted(set(g.breaks))
            # move each break to the nearby barline (within two bars) that cuts the fewest ordines
            # of either voice: a voice whose ordines are out of phase with the other's should not
            # have its ordines split across systems
            def spans(voice_notes, groups):
                out = []
                def walk1(x):
                    if x['level'] <= 1:
                        out.append((voice_notes[x['first']]['measure'], voice_notes[x['last']]['measure']))
                        return
                    for c in x['children']:
                        walk1(c)
                walk1(groups)
                return out
            ords = spans(notes, a['groups'])
            if a.get('reference_voice'):
                ords += spans(a['reference_voice']['notes'], a['reference_voice']['groups'])
            last_m = max(n['measure'] for n in notes)
            chosen = []
            for k in g.breaks:
                b = notes[k]['measure']
                if b <= 1:
                    continue
                cands = [m for m in range(max(2, b - 2), min(last_m, b + 2) + 1)]
                cut = lambda m: sum(1 for f, l in ords if f < m <= l)
                chosen.append(min(cands, key=lambda m: (cut(m), abs(m - b))))
            g.break_measures = sorted(set(chosen))
            # note spacing: a system with too much in it is split (pair, then ordo boundary);
            # engrave() checks the printed spacing and splits further if notes still crowd
            g.splitter = _make_splitter(a)
            ref = (a.get('reference_voice') or {}).get('notes', [])
            if max_system_load:
                for _ in range(50):
                    bounds = [1] + g.break_measures + [last_m + 1]
                    over = [(m0, m1 - 1) for m0, m1 in zip(bounds, bounds[1:])
                            if system_load(notes, ref, m0, m1 - 1) > max_system_load]
                    new = [g.splitter(*mm) for mm in over]
                    new = [m for m in new if m]
                    if not new:
                        break
                    g.break_measures = sorted(set(g.break_measures + new))
            # a short last system (a tag) joins the one before it if that still fits
            if g.break_measures:
                b = g.break_measures[-1]
                prev = g.break_measures[-2] if len(g.break_measures) > 1 else 1
                if (last_m - b + 1 <= 6 and
                        (not max_system_load or system_load(notes, ref, prev, last_m) <= max_system_load)):
                    g.break_measures = g.break_measures[:-1]
    if labels:
        for m in a.get('modules', []):
            g.labels.append({'at': m['first'], 'text': m['label'].replace('′', "'"), 'place': 'above', 'bold': True})
    if sections:
        for sec in a.get('sections', []):
            first = next(n['idx'] for n in notes if n['measure'] >= sec['measures'][0])
            txt = f"home {_pitch_label(sec['home'][:-1])}"
            if sec.get('pedal'):
                txt += f", {sec['pedal']['position']} pedal {_pitch_label(sec['pedal']['pitch'][:-1])}"
            if sec.get('line'):
                txt += '\nline ' + '–'.join(_pitch_label(x.split('@')[0][:-1]) for x in sec['line'])
            g.labels.append({'at': first, 'text': txt, 'place': 'below'})

    rv = a.get('reference_voice')
    if reference and rv:
        t = Graph(staff=rv['part'] + 1, fundamental=sorted(rv['fundamental']['notes']),
                  beam_direction='down', voice_pitches=[n['pitch'] for n in rv['notes']],
                  voice_onsets=[n['onset'] for n in rv['notes']])
        tf = set(t.fundamental)
        t.middleground = [n['idx'] for n in rv['notes'] if n['level'] >= 1 and n['idx'] not in tf]
        t.colors.setdefault('foreground', '#7a8fa8')
        if slurs:
            tl = {d['level'] for d in rv['dependencies'] if d['level'] <= top_slur}
            if slurs != 'all':
                tl = {L for L in tl if L >= 2}
            # mirror of the duplum: the foreground inside each ordo between the staves (above the
            # tenor), connections between heads outside (below)
            add_slurs(t, rv['dependencies'], 'above', 'below', tl,
                      stem_level=top_slur if substems and top_slur >= 2 else None, stem_dir='down')
        g.others.append(t)
    if max_slur_stack:
        for gr in [g] + g.others:
            thin_slurs(gr, max_slur_stack)
    return g


def unaccounted(graph: Graph, n_notes: int) -> list[int]:
    """Notes of a staff that no slur spans or ends on and that are not on the beam: every note of
    a graph should be accounted for."""
    covered = set(graph.fundamental) | {k for st in graph.stems for k in st['notes']}
    for s in graph.slurs:
        if s.get('hidden'):
            continue
        a, b = sorted((s['from'], s['to']))
        covered.update(range(a, b + 1))
    return [k for k in range(n_notes) if k not in covered]


def engrave(score_path, graph: Graph, voice_pitches, out_prefix, formats=('svg', 'png', 'pdf'),
            options=None, keep_mei=True, extra_beam_staves=(), beam_voice=True, fix_labels=True,
            fix_spacing=True, min_gap=1.65):
    """``extra_beam_staves``: staves (1-based) whose notes are all beamed as a line as well,
    e.g. the 'fundamental' staff of a stacked reduction. ``fix_spacing``: systems whose notes come
    closer than ``min_gap`` staff spaces are split (see ``Graph.splitter``) and re-rendered."""
    mei = annotated_mei(score_path, graph, voice_pitches, options)
    from lxml import etree
    root = etree.fromstring(mei.encode('utf-8'))
    xid = '{http://www.w3.org/XML/1998/namespace}id'
    ids = getattr(graph, 'note_ids', None) or [n.get(xid) for n in staff_notes(root, graph.staff)]
    lines = [{'ids': [ids[k] for k in sorted(graph.fundamental)], 'direction': graph.beam_direction}] if beam_voice else []
    for other in graph.others:
        oids = getattr(other, 'note_ids', None) or [n.get(xid) for n in staff_notes(root, other.staff)]
        if other.fundamental:
            lines.append({'ids': [oids[k] for k in sorted(other.fundamental)],
                          'direction': other.beam_direction, 'color': other.colors['fundamental']})
    for st in extra_beam_staves:
        lines.append({'ids': [n.get(xid) for n in staff_notes(root, st)], 'direction': 'up'})
    for gr in [graph] + list(graph.others):
        gids = ids if gr is graph else (getattr(gr, 'note_ids', None) or [n.get(xid) for n in staff_notes(root, gr.staff)])
        for st in gr.stems:
            if st.get('drawn'):          # an extra stem drawn on the SVG instead of the note's own
                lines.append({'ids': [gids[k] for k in st['notes']], 'beam': False,
                              'direction': st.get('direction', 'up'), 'color': st.get('color'),
                              'length': st.get('length', 3.5)})
    pages = render(mei, graph, lines, options)
    from .collide import collisions as _coll, crowded_systems
    from .mei import _q as _mq, _insert_breaks
    # note spacing: split any system whose notes are still too close, then render again
    if fix_spacing and getattr(graph, 'splitter', None):
        for _ in range(6):
            root2 = etree.fromstring(mei.encode('utf-8'))
            mnum = {m.get(xid): int(m.get('n')) for m in root2.iter(_mq('measure'))
                    if (m.get('n') or '').isdigit()}
            new = []
            for pg in pages:
                for first, last, _gap in crowded_systems(pg, min_gap):
                    if first in mnum and last in mnum:
                        m = graph.splitter(mnum[first], mnum[last])
                        if m and m not in graph.break_measures:
                            new.append(m)
            if not new:
                break
            graph.break_measures = sorted(set(graph.break_measures) | set(new))
            _insert_breaks(root2, [], graph.systems_per_page, measures=graph.break_measures)
            mei = etree.tostring(root2, xml_declaration=True, encoding='UTF-8').decode('utf-8')
            pages = render(mei, graph, lines, options)
    # a label that a slur runs through goes to the other side of its staff, if that is cleaner
    def _bad(pgs):
        return {c[3] for pg in pgs for c in _coll(pg) if c[0] == 'slur-text'}

    def _count(pgs):
        return sum(1 for pg in pgs for c in _coll(pg) if c[0] == 'slur-text')

    # a label that a slur runs through: try it on the other side of its staff, then nudged
    # further out (1, 2, 3 staff spaces); keep whatever leaves fewest label collisions
    if fix_labels:
        for attempt in ('flip', 2, 4, 6):
            bad = _bad(pages)
            if not bad:
                break
            root2 = etree.fromstring(mei.encode('utf-8'))
            changed = 0
            for d in root2.iter(_mq('dir')):
                if d.get(xid) not in bad:
                    continue
                if attempt == 'flip':
                    d.set('place', 'above' if d.get('place') == 'below' else 'below')
                else:
                    sign = 1 if d.get('place', 'above') == 'above' else -1
                    d.set('vo', f'{sign * attempt}vu')
                changed += 1
            if not changed:
                break
            mei2 = etree.tostring(root2, xml_declaration=True, encoding='UTF-8').decode('utf-8')
            pages2 = render(mei2, graph, lines, options)
            if _count(pages2) < _count(pages):
                mei, pages = mei2, pages2
    written = write_pages(pages, out_prefix, formats)
    if keep_mei:
        p = Path(out_prefix).with_suffix('.mei')
        p.write_text(mei)
        written.append(p)
    return written


def resolve_refs(spec: dict, analysis: dict) -> dict:
    """Let a hand-written spec name notes by address ('3f4-1': measure 3, F4, first in the
    measure; accidentals as in music21, 'b-4' = B-flat) instead of index."""
    addr = {n['address']: n['idx'] for n in analysis['notes']}

    def one(x):
        if isinstance(x, int):
            return x
        key = str(x).strip().lower()
        if key.isdigit():
            return int(key)
        if key not in addr:
            raise KeyError(f'no note {x!r} (addresses look like {next(iter(addr))!r})')
        return addr[key]

    out = dict(spec)
    for k in ('fundamental', 'middleground'):
        if k in out:
            out[k] = [one(x) for x in out[k]]
    for k, fields in (('slurs', ('from', 'to')), ('labels', ('at',)), ('brackets', ('from', 'to'))):
        if k in out:
            out[k] = [{**d, **{f: one(d[f]) for f in fields}} for d in out[k]]
    return out


def graph_from_analysis_file(analysis_path, **kw):
    a = json.loads(Path(analysis_path).read_text())
    return a, graph_from_analysis(a, **kw)


def schenker_graph(score_path, analysis: dict | str | None = None, graph: dict | Graph | None = None,
                   out_prefix='graph', part=0, stacked=None, **kw):
    """One call: analyse (if no analysis is given) with melodic-reduction, build the overlay
    spec, engrave. ``graph`` overrides or replaces the automatic spec (hand analyses).
    ``stacked``: e.g. ('fundamental', 'span:4') to add reduction staves above the score."""
    if analysis is None:
        import melodic_reduction as mr
        analysis = mr.analyze(score_path, part=part)
    elif isinstance(analysis, (str, Path)):
        analysis = json.loads(Path(analysis).read_text())
    if analysis.get('method') == 'tree':
        auto_kw = {k: kw.pop(k) for k in list(kw) if k in ('slurs', 'labels', 'sections', 'reference', 'pedal_stems', 'max_slur_level', 'system_breaks', 'max_slur_stack', 'max_system_load', 'substems', 'substem_length')}
        for k in ('middleground', 'focal', 'modules', 'label_focal', 'module_brackets'):
            kw.pop(k, None)
        g = graph_from_tree(analysis, **auto_kw)
    else:
        auto_kw = {k: kw.pop(k) for k in list(kw) if k in ('middleground', 'focal', 'modules', 'slurs', 'label_focal', 'module_brackets')}
        for k in ('labels', 'sections', 'reference', 'pedal_stems', 'max_slur_level', 'system_breaks',
                  'max_slur_stack', 'max_system_load', 'substems', 'substem_length'):
            kw.pop(k, None)
        g = graph_from_analysis(analysis, **auto_kw)
    if graph is not None:
        if isinstance(graph, Graph):
            g = graph
        else:
            graph = resolve_refs(graph, analysis)
            if graph.get('replace'):
                g = Graph.from_dict({k: v for k, v in graph.items() if k != 'replace'})
            else:
                splitter = g.splitter
                g = Graph.from_dict({**g.to_dict(), **graph})
                if 'break_measures' not in graph and 'breaks' not in graph:
                    g.splitter = splitter
    pitches = [n['pitch'] for n in analysis['notes']]
    if stacked:
        # music21's ScoreReduction puts one staff per level above the score; the overlays go on
        # the original voice, and the top (fundamental) staff is beamed as well
        from melodic_reduction.export import reduction_score
        red = reduction_score(score_path, analysis, levels=stacked)
        from music21 import converter, metadata
        src_md = converter.parse(str(score_path)).metadata
        red.metadata = src_md if src_md is not None else metadata.Metadata()
        if g.title:
            red.metadata.title = g.title
        elif not (red.metadata.title and not str(red.metadata.title).endswith(('.xml', '.musicxml', '.mxl'))):
            red.metadata.title = (src_md.movementName if src_md is not None and src_md.movementName
                                  else Path(str(score_path)).stem)
        tmp = Path(str(out_prefix) + '_stacked.musicxml')
        tmp.parent.mkdir(parents=True, exist_ok=True)
        red.write('musicxml', fp=str(tmp))
        g.staff = len(stacked) + analysis['part'] + 1
        for o in g.others:
            o.staff += len(stacked)
        extra = (1,) if stacked[0] == 'fundamental' else ()
        # beam the fundamental staff; on the original voice the line is shown by colour and stems
        return engrave(tmp, g, pitches, out_prefix, extra_beam_staves=extra,
                       beam_voice=not extra, **kw), g, analysis
    return engrave(score_path, g, pitches, out_prefix, **kw), g, analysis
