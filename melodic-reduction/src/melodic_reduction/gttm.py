"""Benchmark against the GTTM database (Hamanaka, Hirata & Tojo): 300 eight-bar melodies with
hand-made time-span trees (https://gttm.jp/gttm/database/). Used only as an external check of the
rules: the repertoire is tonal, so agreement here says the rules reduce melodies sensibly, not that
they are right for clausulae.

A note's gold level is the length of the largest time-span it heads. The reducer's ranking puts
notes with longer parent intervals first. Agreement at a level = share of the gold top-k notes that
are also in the reducer's top-k, averaged over the gold levels (the whole-melody level excluded).
"""
from __future__ import annotations

import glob
import os
import re
import xml.etree.ElementTree as ET

import numpy as np
from music21 import converter

from .analyze import analyze, load_weights


def gold_levels(ts_path) -> dict[str, float]:
    root = ET.parse(ts_path).getroot()
    lev: dict[str, float] = {}

    def walk(ts):
        span = float(ts.get('timespan'))
        head = ts.find('head')
        if head is not None:
            for nt in head.iter('note'):
                i = nt.get('id')
                lev[i] = max(lev.get(i, 0.0), span)
        for sub in ts:
            if sub.tag in ('primary', 'secondary'):
                for t in sub.findall('ts'):
                    walk(t)

    for ts in root.findall('ts'):
        walk(ts)
    return lev


def note_ids(score):
    """GTTM ids ('P1-m-k') for the first part's notes in order, ties merged like load_voice.
    GTTM numbers every note element of a measure, rests and tie continuations included."""
    ids, count = [], {}
    for n in score.parts[0].flatten().notesAndRests:
        if n.duration.isGrace:
            continue
        m = n.measureNumber
        count[m] = count.get(m, 0) + 1
        if n.isRest or (n.tie is not None and n.tie.type in ('stop', 'continue')):
            continue
        ids.append(f'P1-{m}-{count[m]}')
    return ids


def load_piece(folder):
    msc = [f for f in glob.glob(os.path.join(folder, '*.xml'))
           if not re.match(r'(GPR|MPR|TS|PR|HM)-', os.path.basename(f), re.I)]
    ts = glob.glob(os.path.join(folder, 'TS-*.xml'))
    if not msc or not ts:
        return None
    return msc[0], ts[0]


def agreement(pred_rank_value: np.ndarray, gold: np.ndarray) -> float:
    n = len(gold)
    levels = sorted(set(gold), reverse=True)
    accs = []
    order = np.argsort(-pred_rank_value, kind='stable')
    for L in levels:
        G = set(np.where(gold >= L)[0])
        k = len(G)
        if k >= n or k == 0:
            continue
        P = set(order[:k])
        accs.append(len(G & P) / k)
    return float(np.mean(accs)) if accs else float('nan')


_CACHE: dict = {}


def _load(folder):
    if folder not in _CACHE:
        lp = load_piece(folder)
        item = None
        if lp:
            msc, ts = lp
            try:
                sc = converter.parse(msc)
                item = (sc, note_ids(sc), gold_levels(ts))
            except Exception:
                item = None
        _CACHE[folder] = item
    return _CACHE[folder]


def evaluate_folders(folders, weights='default', frame='virtual', verbose=False):
    rows = []
    w = load_weights(weights)
    for folder in folders:
        item = _load(folder)
        if item is None:
            continue
        s, ids, lev = item
        try:
            a = analyze(s, part=0, reference=None, weights=w, frame=frame, modules=True)
        except Exception as e:
            if verbose:
                print('skip', folder, e)
            continue
        notes = a['notes']
        if len(ids) != len(notes) or any(i not in lev for i in ids):
            if verbose:
                print('skip (id mismatch)', folder, len(ids), len(notes))
            continue
        gold = np.array([lev[i] for i in ids])
        span = np.array([n['span_units'] for n in notes])
        height = np.array([n['height'] for n in notes], float)
        sal = np.array([n['salience'] for n in notes])
        metric = np.array([n['beat_strength'] for n in notes])
        dur = np.array([n['dur'] for n in notes])
        tiny = 1e-6
        rows.append({
            'piece': os.path.basename(folder), 'n': len(notes),
            'tree_span': agreement(span + tiny * height + tiny * tiny * sal, gold),
            'tree_height': agreement(height + tiny * span, gold),
            'salience_only': agreement(sal, gold),
            'metric_only': agreement(metric + tiny * dur, gold),
            'duration_only': agreement(dur + tiny * metric, gold),
        })
    return rows


def evaluate(root, weights='default', frame='virtual', limit=None, verbose=False):
    folders = sorted(d for d in glob.glob(os.path.join(root, '*')) if os.path.isdir(d))
    return evaluate_folders(folders[:limit], weights, frame, verbose)


def report(rows):
    keys = [k for k in rows[0] if k not in ('piece', 'n')]
    out = {k: float(np.nanmean([r[k] for r in rows])) for k in keys}
    out['pieces'] = len(rows)
    return out
