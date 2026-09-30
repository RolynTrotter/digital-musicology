"""Fit weights by coordinate ascent against the GTTM time-span benchmark (cross-validated).

Only weights the benchmark can speak to are searched: the metric/duration/grouping/contour
salience features and how strongly the tree defers to salience. Relation weights (which
elaborations are licensed) and consonance weights (there is no second voice in GTTM) are left
at their rule values.
"""
from __future__ import annotations

import copy
import glob
import json
import os
import sys

import numpy as np

from .analyze import load_weights
from . import gttm

SEARCH = ['salience.metric', 'salience.duration', 'salience.group_start', 'salience.group_end',
          'salience.piece_edge', 'salience.extreme', 'triangle.sub_min', 'triangle.sub_max',
          'triangle.leap', 'triangle.same_pitch_edge', 'parallel_alpha']
FACTORS = [0.0, 0.5, 2.0]


def _set(w, path, val):
    if '.' in path:
        a, b = path.split('.')
        w[a][b] = val
    else:
        w[path] = val


def _get(w, path):
    if '.' in path:
        a, b = path.split('.')
        return w[a].get(b, 0.0)
    return w.get(path, 0.0)


def _score(root, w, pieces, metric):
    rows = gttm.evaluate_folders([os.path.join(root, p) for p in pieces], w)
    return float(np.nanmean([r[metric] for r in rows]))


def fit(root, start='default', rounds=2, metric='tree_span', out=None, log=print):
    folders = sorted(os.path.basename(d) for d in glob.glob(os.path.join(root, '*')) if os.path.isdir(d))
    train = folders[0::2]
    test = folders[1::2]
    w = load_weights(start)
    best = _score(root, w, train, metric)
    log(f'start train {best:.4f}')
    for r in range(rounds):
        for path in SEARCH:
            cur = _get(w, path)
            cands = sorted({round(cur * f, 4) for f in FACTORS} | {round(cur + d, 4) for d in (-0.5, 0.5)})
            for v in cands:
                if v == cur:
                    continue
                w2 = copy.deepcopy(w)
                _set(w2, path, v)
                s = _score(root, w2, train, metric)
                if s > best + 1e-4:
                    best, w = s, w2
                    log(f'round {r} {path}={v}: train {best:.4f}')
    test_start = _score(root, load_weights(start), test, metric)
    test_fit = _score(root, w, test, metric)
    log(f'held-out {metric}: start {test_start:.4f} -> fitted {test_fit:.4f}')
    w['_comment'] = (f'Salience and subordination weights fitted by coordinate ascent to the GTTM database '
                     f'time-span trees (train = every other folder); held-out {metric} '
                     f'{test_start:.3f} -> {test_fit:.3f}. Relation and consonance weights are the rule defaults.')
    if out:
        with open(out, 'w') as fh:
            json.dump(w, fh, indent=2)
    return w, {'train': best, 'test_start': test_start, 'test_fit': test_fit}


if __name__ == '__main__':
    fit(sys.argv[1], out=sys.argv[2] if len(sys.argv) > 2 else None)
