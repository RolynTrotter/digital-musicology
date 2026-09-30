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


def analyze(score, part: int = 0, reference='auto', weights='default', unit: float | None = None,
            fundamental='auto', min_focal_units: float = 2.0, modules: bool = True,
            frame: str = 'notes') -> dict:
    """Reduce one voice.

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
        'format': 'melodic-reduction/1',
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
