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


def engrave(score_path, graph: Graph, voice_pitches, out_prefix, formats=('svg', 'png', 'pdf'),
            options=None, keep_mei=True, extra_beam_staves=(), beam_voice=True):
    """``extra_beam_staves``: staves (1-based) whose notes are all beamed as a line as well,
    e.g. the 'fundamental' staff of a stacked reduction."""
    mei = annotated_mei(score_path, graph, voice_pitches, options)
    from lxml import etree
    root = etree.fromstring(mei.encode('utf-8'))
    xid = '{http://www.w3.org/XML/1998/namespace}id'
    ids = [n.get(xid) for n in staff_notes(root, graph.staff)]
    lines = [[ids[k] for k in sorted(graph.fundamental)]] if beam_voice else []
    for st in extra_beam_staves:
        lines.append([n.get(xid) for n in staff_notes(root, st)])
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
    auto_kw = {k: kw.pop(k) for k in list(kw) if k in ('middleground', 'focal', 'modules', 'slurs', 'label_focal', 'module_brackets')}
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
        tmp = Path(str(out_prefix) + '_stacked.musicxml')
        tmp.parent.mkdir(parents=True, exist_ok=True)
        red.write('musicxml', fp=str(tmp))
        g.staff = len(stacked) + analysis['part'] + 1
        extra = (1,) if stacked[0] == 'fundamental' else ()
        # beam the fundamental staff; on the original voice the line is shown by colour and stems
        return engrave(tmp, g, pitches, out_prefix, extra_beam_staves=extra,
                       beam_voice=not extra, **kw), g, analysis
    return engrave(score_path, g, pitches, out_prefix, **kw), g, analysis
