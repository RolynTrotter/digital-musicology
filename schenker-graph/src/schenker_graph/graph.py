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


def graph_from_tree(a: dict, slurs='all', labels=True, sections=True, reference=True,
                    staff=None, max_slur_level=None) -> Graph:
    """Overlays for a grouped-tree analysis (method 'tree').

    * fundamental line: red, stems and beam (above the duplum; below the tenor);
    * heads of ordines and higher groups: blue noteheads;
    * slurs: every note's place in its group. Inside an ordo (the foreground) they go below the
      staff; between the heads of ordines and pairs above it, up to ``max_slur_level`` (default:
      the fundamental line's level; higher connections are what the beam shows).
      ``slurs='upper'`` keeps only the slurs above, ``None`` none. On the tenor only the
      connections between pair heads are slurred;
    * labels: the pair (module) letters above the staff, and at each pair of pairs its home note
      and pedal pitch below it.
    """
    notes = a['notes']
    fund = sorted(a['fundamental']['notes'])
    fset = set(fund)
    g = Graph(staff=(staff if staff is not None else a.get('part', 0) + 1), fundamental=fund,
              voice_pitches=[n['pitch'] for n in notes])
    g.middleground = [n['idx'] for n in notes if n['level'] >= 1 and n['idx'] not in fset]
    g.colors.setdefault('foreground', '#7a8fa8')

    def add_slurs(target, deps, lower_place, upper_place, keep_levels):
        seen = {}
        for d in deps:
            if d['level'] not in keep_levels:
                continue
            sl = _dep_slur(d['note'], *d['parent'])
            if sl is None or sl[0] == sl[1]:
                continue
            seen[sl] = max(seen.get(sl, 0), d['level'])
        for (x, y), lev in sorted(seen.items()):
            if lev <= 1:
                target.slurs.append({'from': x, 'to': y, 'style': 'solid', 'place': lower_place,
                                     'color': target.colors['foreground']})
            else:
                target.slurs.append({'from': x, 'to': y, 'style': 'solid', 'place': upper_place,
                                     'color': target.colors['slur']})

    top_slur = max_slur_level or a['fundamental'].get('level', 3)
    levels_all = {d['level'] for d in a['dependencies'] if d['level'] <= top_slur}
    if slurs:
        keep = levels_all if slurs == 'all' else {L for L in levels_all if L >= 2}
        add_slurs(g, a['dependencies'], 'below', 'above', keep)

    if labels:
        for m in a.get('modules', []):
            g.labels.append({'at': m['first'], 'text': m['label'].replace('′', "'"), 'place': 'above', 'bold': True})
    if sections:
        for sec in a.get('sections', []):
            first = next(n['idx'] for n in notes if n['measure'] >= sec['measures'][0])
            txt = f"home {_pitch_label(sec['home'][:-1])}"
            if sec.get('pedal'):
                txt += f", {sec['pedal']['position']} pedal {_pitch_label(sec['pedal']['pitch'][:-1])}"
            g.labels.append({'at': first, 'text': txt, 'place': 'below'})

    rv = a.get('reference_voice')
    if reference and rv:
        t = Graph(staff=rv['part'] + 1, fundamental=sorted(rv['fundamental']['notes']),
                  beam_direction='down', voice_pitches=[n['pitch'] for n in rv['notes']])
        tf = set(t.fundamental)
        t.middleground = [n['idx'] for n in rv['notes'] if n['level'] >= 1 and n['idx'] not in tf]
        t.colors.setdefault('foreground', '#7a8fa8')
        if slurs:
            add_slurs(t, rv['dependencies'], 'below', 'below',
                      {d['level'] for d in rv['dependencies'] if 2 <= d['level'] <= top_slur - 1})
        g.others.append(t)
    return g


def engrave(score_path, graph: Graph, voice_pitches, out_prefix, formats=('svg', 'png', 'pdf'),
            options=None, keep_mei=True, extra_beam_staves=(), beam_voice=True):
    """``extra_beam_staves``: staves (1-based) whose notes are all beamed as a line as well,
    e.g. the 'fundamental' staff of a stacked reduction."""
    mei = annotated_mei(score_path, graph, voice_pitches, options)
    from lxml import etree
    root = etree.fromstring(mei.encode('utf-8'))
    xid = '{http://www.w3.org/XML/1998/namespace}id'
    ids = [n.get(xid) for n in staff_notes(root, graph.staff)]
    lines = [{'ids': [ids[k] for k in sorted(graph.fundamental)], 'direction': graph.beam_direction}] if beam_voice else []
    for other in graph.others:
        oids = [n.get(xid) for n in staff_notes(root, other.staff)]
        if other.fundamental:
            lines.append({'ids': [oids[k] for k in sorted(other.fundamental)],
                          'direction': other.beam_direction, 'color': other.colors['fundamental']})
    for st in extra_beam_staves:
        lines.append({'ids': [n.get(xid) for n in staff_notes(root, st)], 'direction': 'up'})
    pages = render(mei, graph, lines, options)
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
        auto_kw = {k: kw.pop(k) for k in list(kw) if k in ('slurs', 'labels', 'sections', 'reference')}
        for k in ('middleground', 'focal', 'modules', 'label_focal', 'module_brackets'):
            kw.pop(k, None)
        g = graph_from_tree(analysis, **auto_kw)
    else:
        auto_kw = {k: kw.pop(k) for k in list(kw) if k in ('middleground', 'focal', 'modules', 'slurs', 'label_focal', 'module_brackets')}
        for k in ('labels', 'sections', 'reference'):
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
                g = Graph.from_dict({**g.to_dict(), **graph})
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
