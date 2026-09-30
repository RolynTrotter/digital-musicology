"""Top-level analysis: voice -> hierarchy -> reductions, fundamental line, focal pitches, modules."""
from __future__ import annotations

import copy
import json
import math
from importlib import resources
from pathlib import Path

import numpy as np

from . import features as F
from . import focal as FO
from .mop import parse, REL_NAMES
from .voice import load_score, load_voice


def load_weights(name_or_path='default') -> dict:
    if isinstance(name_or_path, dict):
        return copy.deepcopy(name_or_path)
    p = Path(str(name_or_path))
    if p.suffix == '.json' and p.exists():
        return json.loads(p.read_text())
    with resources.files('melodic_reduction').joinpath(f'data/weights_{name_or_path}.json').open() as fh:
        return json.load(fh)


def bar_length(score) -> float:
    from music21 import meter
    ts = score.recurse().getElementsByClass(meter.TimeSignature).first()
    return float(ts.barDuration.quarterLength) if ts else 4.0


def analyze(score, part: int = 0, reference='auto', weights='default', method: str = 'tree', **kw) -> dict:
    """Reduce one voice. ``method='tree'`` (default) reduces group by group from the ordo up
    (see analyze_tree); ``method='mop'`` is the flat reducer (one triangulation of the whole
    voice, see analyze_mop)."""
    if method == 'tree':
        return analyze_tree(score, part=part, reference=reference, weights=weights, **kw)
    return analyze_mop(score, part=part, reference=reference, weights=weights, **kw)


def analyze_mop(score, part: int = 0, reference='auto', weights='default', unit: float | None = None,
                fundamental='auto', min_focal_units: float = 2.0, modules: bool = True,
                frame: str = 'notes') -> dict:
    """Reduce one voice with one triangulation of the whole voice.

    score      path or music21 Score
    part       index of the voice to reduce (duplum = 0 in the Dominus files)
    reference  index of the voice to measure consonance against; 'auto' = the other part of a
               two-part score, None = none
    unit       quarterLength of one metrical unit for spans and durations (default: one bar)
    fundamental 'auto', 'span:T' (keep notes whose parent interval spans >= T units),
               'height:H', or 'count:K' (the span threshold that keeps about K notes)
    frame      'notes' (first and last notes are the top of the hierarchy) or 'virtual'
    """
    s = load_score(score)
    w = load_weights(weights)
    nparts = len(s.parts)
    if reference == 'auto':
        reference = (1 - part) if nparts == 2 else None
    unit = unit or bar_length(s)
    notes = load_voice(s, part, reference)
    if len(notes) < 2:
        raise ValueError('voice has fewer than two notes')

    feats = F.base_features(notes, unit)
    sal0 = F.salience(feats, w)
    mods = []
    if modules:
        mods = F.find_modules(notes, int(w.get('module_min_notes', 5)))
        loose = F.find_modules(notes, int(w.get('module_min_notes', 5)) + 1, loose=True)
        # keep loose (varied) groups only where they add occurrences the exact groups lack
        exact_starts = {o[0] for g in mods for o in g['occurrences']}
        loose = [g for g in loose if any(o[0] not in exact_starts for o in g['occurrences'])]
    else:
        loose = []
    sal = F.parallelise(sal0, mods, float(w.get('parallel_alpha', 0.0)))

    end_time = notes[-1].end
    tree = parse([v.dnum for v in notes], sal, [v.onset for v in notes], end_time, unit, w, frame=frame)

    out_notes = []
    for v in notes:
        k = v.idx
        pi, pj = tree.note_parent(k)
        t_i = notes[pi].onset if pi is not None else notes[0].onset
        t_j = notes[pj].onset if pj is not None else end_time
        d = v.to_dict()
        d.update({
            'salience': round(float(sal[k]), 4),
            'salience_raw': round(float(sal0[k]), 4),
            'height': int(tree.height[k + 1]),
            'depth': int(tree.depth[k + 1]),
            'parent': [pi, pj],
            'relation': tree.relation[k + 1],
            'span_units': round((t_j - t_i) / unit, 4),
            'features': {a: round(b, 4) for a, b in feats[k].items()},
        })
        out_notes.append(d)

    spans = sorted({n['span_units'] for n in out_notes})
    fund = choose_fundamental(out_notes, fundamental, unit, len(notes), end_time - notes[0].onset)
    focal = FO.focal_spans(notes, tree, unit, min_focal_units)
    maxh = int(max(n['height'] for n in out_notes))
    levels = {str(h): [n['idx'] for n in out_notes if n['height'] >= h] for h in range(maxh + 1)}
    span_levels = {}
    for T in (1, 2, 4, 8, 16, 32, 64):
        keep = [n['idx'] for n in out_notes if n['span_units'] >= T]
        if keep:
            span_levels[str(T)] = keep

    prof_all = FO.pitch_profile(notes, [1.0] * len(notes))
    prof_struct = FO.pitch_profile(notes, [float(tree.height[k + 1] + 1) for k in range(len(notes))])

    return {
        'format': 'melodic-reduction/1', 'method': 'mop',
        'source': str(score) if not hasattr(score, 'parts') else None,
        'part': part, 'reference': reference, 'unit_ql': unit, 'frame': frame,
        'weights': w,
        'notes': out_notes,
        'levels_by_height': levels,
        'levels_by_span_units': span_levels,
        'fundamental': fund,
        'focal_pitches': focal,
        'dominant_focal_pitches': [{'pitch': x['pitch'], 'measures': x['measures'],
                                    'length_units': x['length_units'], 'returns': x['returns'],
                                    'returns_per_8_units': x['returns_per_8_units'],
                                    'time_within_step': x['time_within_step']}
                                   for x in FO.dominant_spans(focal)],
        'modules': [_mod_json(g, notes) for g in mods + loose],
        'pitch_profile': {'all_notes': prof_all, 'height_weighted': prof_struct},
        'relations_legend': REL_NAMES,
        'tree_score': tree.score,
    }


def _mod_json(g, notes):
    return {'label': g['label'], 'length_notes': g['length'], 'varied': g['loose'],
            'occurrences': [{'first': a, 'last': b, 'transposition_steps': t,
                             'measures': [notes[a].measure, notes[b].measure],
                             'start_pitch': notes[a].pitch} for a, b, t in g['occurrences']]}


def choose_fundamental(out_notes, spec, unit, n_notes, dur_ql):
    if spec in (None, 'auto'):
        target = max(4, round(dur_ql / unit / 8))
        spec = f'count:{target}'
    kind, _, val = str(spec).partition(':')
    if kind == 'span':
        T = float(val)
        keep = [n['idx'] for n in out_notes if n['span_units'] >= T]
        return {'rule': f'span>={T}', 'notes': keep}
    if kind == 'height':
        H = int(val)
        return {'rule': f'height>={H}', 'notes': [n['idx'] for n in out_notes if n['height'] >= H]}
    if kind == 'count':
        K = int(val)
        spans = sorted({n['span_units'] for n in out_notes}, reverse=True)
        best, best_keep = None, None
        for T in spans:
            keep = [n['idx'] for n in out_notes if n['span_units'] >= T]
            if best is None or abs(len(keep) - K) < abs(len(best_keep) - K) or (
                    abs(len(keep) - K) == abs(len(best_keep) - K) and len(keep) > len(best_keep)):
                best, best_keep = T, keep
            if len(keep) > 2 * K:
                break
        return {'rule': f'span>={best} (about {K} notes)', 'notes': best_keep}
    if kind == 'notes':
        return {'rule': 'given', 'notes': [int(x) for x in val.split(',') if x]}
    raise ValueError(f'unknown fundamental spec {spec!r}')


def write_json(analysis: dict, path):
    Path(path).write_text(json.dumps(analysis, indent=1, default=_np))


def _np(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o))


def summary(a: dict) -> str:
    notes = a['notes']
    lines = []
    fl = [notes[i] for i in a['fundamental']['notes']]
    lines.append(f"voice: {len(notes)} notes; hierarchy height {max(n['height'] for n in notes)}")
    lines.append(f"fundamental line ({a['fundamental']['rule']}): " +
                 ' '.join(f"{n['pitch']}(m{n['measure']})" for n in fl))
    for T, keep in a['levels_by_span_units'].items():
        lines.append(f"  span >= {T:>2} units: {len(keep):>3} notes")
    lines.append('dominant focal pitches: ' + ', '.join(
        f"{d['pitch']} m{d['measures'][0]}-{d['measures'][1]} ({d['length_units']} units, {d['returns']} returns)"
        for d in a['dominant_focal_pitches']))
    if a['modules']:
        lines.append('modules: ' + '; '.join(
            f"{m['label']} x{len(m['occurrences'])} ({m['length_notes']} notes) at m" +
            ','.join(str(o['measures'][0]) + (f"{o['transposition_steps']:+d}" if o['transposition_steps'] else '')
                     for o in m['occurrences']) for m in a['modules'][:8]))
    rel = {}
    for n in notes:
        rel[n['relation']] = rel.get(n['relation'], 0) + 1
    lines.append('elaboration types: ' + ', '.join(f'{k} {v}' for k, v in sorted(rel.items(), key=lambda kv: -kv[1])))
    return '\n'.join(lines)


# ------------------------------------------------------------------ grouped tree

def _voice_tree(s, part, reference, w, unit, ligs, master=None):
    """Salience, grouping and tree for one voice. ``master`` = (root, notes) of the voice whose
    groups this one follows above the ordo (the tenor follows the duplum)."""
    from . import grouping as G
    from .tree import reduce_tree, map_hierarchy
    notes = load_voice(s, part, reference)
    ref_notes = load_voice(s, reference, part) if reference is not None else None
    feats = F.base_features(notes, unit)
    for f in feats:
        f.pop('piece_edge', None)          # applied only at the top of the tree (tree.py)
    sal = F.salience(feats, w)
    ords = G.ordines(notes, G.unit_period(notes, ref_notes))
    lig_spans = G.ligatures(s.parts[part], notes) if ligs else None
    if master is None:
        root = G.build_hierarchy(notes, ords, lig_spans, w.get('grouping', {}), ref_notes=ref_notes)
        G.label_modules(notes, root, **w.get('labels', {}))
    else:
        root = map_hierarchy(master[0], master[1], notes, ords)
        if root is None or root.first != 0 or root.last != len(notes) - 1:
            # the master's groups do not cover this voice: group it on its own
            root = G.build_hierarchy(notes, ords, None, w.get('grouping', {}), ref_notes=ref_notes)
    res = reduce_tree(notes, root, sal, w, unit)
    return notes, feats, sal, root, res, ords


def analyze_tree(score, part: int = 0, reference='auto', weights='default', unit: float | None = None,
                 fundamental='auto', ligatures: bool = False, reduce_reference: bool = True,
                 min_focal_units: float = 2.0) -> dict:
    """Reduce one voice group by group: ordines (optionally ligatures inside them), pairs, pairs
    of pairs ... up to the whole voice; each group's members reduced to a head by the
    prolongation rules; heads carried up. With a reference voice, that voice is reduced too,
    following the same groups above the ordo.

    fundamental  'auto' (heads of the level just below the sections: pairs of pairs in a
                 clausula), 'level:L' (heads of the groups at level L), or 'notes:1,5,9'.
    ligatures    use ligature brackets in the MusicXML as a level below the ordo.
    """
    from . import grouping as G
    from .tree import heads_at, section_summary
    s = load_score(score)
    w = load_weights(weights)
    nparts = len(s.parts)
    if reference == 'auto':
        reference = (1 - part) if nparts == 2 else None
    unit = unit or bar_length(s)
    notes, feats, sal, root, res, ords = _voice_tree(s, part, reference, w, unit, ligatures)
    if len(notes) < 2:
        raise ValueError('voice has fewer than two notes')
    top = root.level

    out_notes = []
    for v in notes:
        d = v.to_dict()
        r = res['notes'][v.idx]
        d.update({'salience': round(float(sal[v.idx]), 4),
                  'features': {a: round(b, 4) for a, b in feats[v.idx].items()},
                  'level': r['level'], 'level_name': G.level_name(r['level'], top) if r['level'] else 'surface',
                  'reduced_at': r['reduced_at'], 'parent': r['parent'], 'relation': r['relation'],
                  'local_height': r.get('local_height', 0)})
        out_notes.append(d)

    levels = {'surface': [n['idx'] for n in out_notes]}
    for L in range(1, top + 1):
        keep = [n['idx'] for n in out_notes if n['level'] >= L]
        levels[G.LEVEL_NAMES.get(L, f'level {L}')] = keep
        if L == top:
            levels['piece'] = keep

    fund_level = max(1, min(3, top - 1)) if fundamental in (None, 'auto') else None
    if fund_level is not None:
        fl = sorted(set(heads_at(root, fund_level)) | {0})
        fund = {'rule': f'heads of each {G.level_name(fund_level, top)}, and the first note', 'notes': fl,
                'level': fund_level}
    elif str(fundamental).startswith('level:'):
        L = int(str(fundamental).split(':')[1])
        fund = {'rule': f'heads of each {G.level_name(L, top)}', 'notes': sorted(set(heads_at(root, L)) | {0}),
                'level': L}
    elif str(fundamental).startswith('notes:'):
        fund = {'rule': 'given', 'notes': [int(x) for x in str(fundamental)[6:].split(',') if x]}
    else:
        raise ValueError(f'unknown fundamental spec {fundamental!r}')

    edges = set()
    for (L, f, l, k, pi, pj, rel) in res['dependencies']:
        for a, b in ((pi, k), (k, pj), (pi, pj)):
            if a is not None and b is not None:
                edges.add((min(a, b), max(a, b)))
    focal = FO.focal_spans(notes, None, unit, min_focal_units, edges=edges,
                           heights=[r['level'] for r in (res['notes'][v.idx] for v in notes)])

    out = {
        'format': 'melodic-reduction/2', 'method': 'tree',
        'source': str(score) if not hasattr(score, 'parts') else None,
        'part': part, 'reference': reference, 'unit_ql': unit, 'ligatures': ligatures,
        'weights': w,
        'notes': out_notes,
        'groups': root.to_dict(notes),
        'level_names': {str(L): G.level_name(L, top) for L in range(0, top + 1)},
        'levels': levels,
        'fundamental': fund,
        'sections': section_summary(notes, root, fund_level or 3),
        'dependencies': [{'level': L, 'note': k, 'parent': [pi, pj], 'relation': rel}
                         for (L, f, l, k, pi, pj, rel) in res['dependencies']],
        'modules': [{'label': g.label, 'measures': [notes[g.first].measure, notes[g.last].measure],
                     'first': g.first, 'last': g.last,
                     'like': (None if getattr(g, 'similar_to', (None,))[0] is None else
                              {'pair': g.similar_to[0], 'similarity': g.similar_to[1]})}
                    for g in G.walk(root) if g.level == 2],
        'focal_pitches': focal,
        'dominant_focal_pitches': [{'pitch': x['pitch'], 'measures': x['measures'],
                                    'length_units': x['length_units'], 'returns': x['returns'],
                                    'returns_per_8_units': x['returns_per_8_units'],
                                    'time_within_step': x['time_within_step']}
                                   for x in FO.dominant_spans(focal)],
        'relations_legend': REL_NAMES,
    }
    if reference is not None and reduce_reference:
        rn, rf, rs, rroot, rres, _ = _voice_tree(s, reference, part, w, unit, False, master=(root, notes))
        rtop = rroot.level
        out['reference_voice'] = {
            'part': reference,
            'notes': [{**v.to_dict(), 'salience': round(float(rs[v.idx]), 4),
                       'level': rres['notes'][v.idx]['level'],
                       'reduced_at': rres['notes'][v.idx]['reduced_at'],
                       'parent': rres['notes'][v.idx]['parent'],
                       'relation': rres['notes'][v.idx]['relation']} for v in rn],
            'groups': rroot.to_dict(rn),
            'fundamental': {'notes': sorted(set(heads_at(rroot, max(1, min(fund_level or 3, rtop - 1)))) | {0}),
                            'level': max(1, min(fund_level or 3, rtop - 1))},
            'dependencies': [{'level': L, 'note': k, 'parent': [pi, pj], 'relation': rel}
                             for (L, f, l, k, pi, pj, rel) in rres['dependencies']],
        }
    return out


def summary_tree(a: dict) -> str:
    notes = a['notes']
    lines = [f"voice: {len(notes)} notes in {sum(1 for n in notes if n['after_rest'])} rest-groups"]
    def walkg(g, depth=0):
        yield g, depth
        for c in g['children']:
            yield from walkg(c, depth + 1)
    names = a['level_names']
    for g, depth in walkg(a['groups']):
        if g['level'] >= 2:
            h = notes[g['head']]
            lab = f" {g['label']}" if g.get('label') else ''
            lines.append(f"{'  ' * depth}{names[str(g['level'])]} m{g['measures'][0]}-{g['measures'][1]}{lab}: "
                         f"head {h['pitch']} (m{h['measure']})")
    fl = [notes[i] for i in a['fundamental']['notes']]
    lines.append(f"fundamental line ({a['fundamental']['rule']}): " +
                 ' '.join(f"{n['pitch']}(m{n['measure']})" for n in fl))
    for sec in a['sections']:
        ped = sec['pedal']
        ped_s = f"; {ped['position']} pedal {ped['pitch']} ({ped['ordo_heads']} of {ped['of']} ordo heads)" if ped else ''
        if sec.get('line'):
            ped_s += f"; {len(sec['line'])}-note stepwise line " + '-'.join(x.split('@')[0] for x in sec['line'])
        lines.append(f"m{sec['measures'][0]}-{sec['measures'][1]}: home {sec['home']}; ordo heads "
                     + ' '.join(sec['ordo_head_line']) + ped_s)
    if 'reference_voice' in a:
        rv = a['reference_voice']
        lines.append('reference voice line: ' + ' '.join(
            f"{rv['notes'][i]['pitch']}(m{rv['notes'][i]['measure']})" for i in rv['fundamental']['notes']))
    return '\n'.join(lines)
