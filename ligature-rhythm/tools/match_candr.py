"""Match edition sections (e.g. from tools/payne_pdf.py) to CANDR clausulae; write a benchmark spec.

Usage:
    python tools/match_candr.py --candr candr --editions editions_payne --out benchmarks/f5_payne.json

For every section:

* candidate runs: the F settings on the piece's leaf, the one before and the one after (manuscript
  order from candr/manifest.csv), and every window of six consecutive W1 settings from the
  clausula fascicle whose tenor contains the section's tenor incipit (one mismatch allowed);
* each run is cut with the section's own tenor incipit (first ten pitch letters) and a restart
  gap just under the chant's period, and the clausula whose upper voice best fits the duplum is
  taken;
* fit = semi-global alignment score of the duplum (+1 match, -1 mismatch or gap, pitch with
  octave) per edition note. Unrelated clausulae score about 0.0-0.4 against these sections, true
  concordances 0.6-1.0. F is preferred when it fits about as well (it is the edition's source).

Kept: duplum fit >= 0.6 (>= 0.75 under 20 notes), tenor >= 0.8 of its notes aligned in a contiguous
span, at least 12 duplum notes. Sections of one piece, and sections whose dupla are the same music
(similar length, fit >= 0.7), share a cross-validation group.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from seqalign import semiglobal                                           # noqa: E402
from ligature_rhythm.candr import notes_of                               # noqa: E402
from ligature_rhythm.evaluate import align                               # noqa: E402
from ligature_rhythm.segment import chain, split                          # noqa: E402

STEPS = 'CDEFGAB'


def fol_key(f):
    m = re.match(r'f\.(\d+)[a-z]?([rv])', f or '')
    return int(m.group(1)) * 2 + (m.group(2) == 'v') if m else None


def edition_pitches(path, part) -> list:
    """diatonic pitch numbers (7 * octave + step), tied continuations dropped"""
    P = list(ET.parse(path).getroot().iter('part'))[part]
    out, prev_tie = [], False
    for n in P.iter('note'):
        p = n.find('pitch')
        ties = [x.get('type') for x in n.findall('tie')]
        if p is None:
            prev_tie = False
            continue
        if not ('stop' in ties and prev_tie):
            out.append(7 * int(p.findtext('octave')) + STEPS.index(p.findtext('step')))
        prev_tie = 'start' in ties
    return out


def candr_pitches(tokens) -> list:
    return [7 * (n.oct + 1) + 'cdefgab'.index(n.pname) for t in tokens for n in notes_of(t)]


def contiguous_share(a, b) -> float:
    """share of a aligned with b, over the span of b it occupies"""
    pr = align([(0, 0, chr(0x100 + x)) for x in a], [(0, 0, chr(0x100 + x)) for x in b])
    if not pr:
        return 0.0
    return len(pr) / max(len(a), pr[-1][1] - pr[0][1] + 1)


def period(seq) -> int:
    for p in range(3, len(seq)):
        if len(seq) - p >= 3 and all(seq[i] == seq[i + p] for i in range(len(seq) - p)):
            return p
    return len(seq)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--candr', default='candr')
    ap.add_argument('--editions', default='editions_payne')
    ap.add_argument('--out', default='f5_payne.json')
    a = ap.parse_args(argv)
    candr, ed_dir = Path(a.candr), Path(a.editions)

    man = [r for r in csv.DictReader(open(candr / 'manifest.csv')) if (candr / r['file']).exists()]
    F = [(int(r['id']), fol_key(r['folio'])) for r in man if 'Pluteus 29.1' in r['source'] and fol_key(r['folio'])]
    W1 = [int(r['id']) for r in man if 'Guelf. 628' in r['source']
          and fol_key(r['folio']) and 80 <= fol_key(r['folio']) <= 128]        # ff. 40r-64v
    W1_windows = [W1[i:i + 6] for i in range(0, max(1, len(W1) - 3), 3)]
    path = lambda i: candr / f'setting_{i:04d}.mei'

    tl_cache, split_cache = {}, {}

    def tenor_letters(ids):
        if ids not in tl_cache:
            _, te = chain([path(i) for i in ids])
            tl_cache[ids] = ''.join(n.pname.upper() for _, x in te for n in notes_of(x))
        return tl_cache[ids]

    def has_incipit(ids, inc):
        L, k = tenor_letters(ids), len(inc)
        return any(sum(x != y for x, y in zip(L[i:i + k], inc)) <= 1 for i in range(len(L) - k + 1))

    def clausulae(ids, inc, gap):
        key = (ids, inc, gap)
        if key not in split_cache:
            try:
                split_cache[key] = split([path(i) for i in ids], incipit=inc, min_gap=gap)[0]
            except ValueError:
                split_cache[key] = []
        return split_cache[key]

    index = json.loads((ed_dir / 'index.json').read_text())
    spec = dict(description='Payne, F fasc. 5 clausulae a2 (DIAMM 2026), matched to CANDR settings (F, or '
                'the W1 concordance); edition sections read from the vector PDF by tools/payne_pdf.py',
                runs={}, pieces={}, groups=[], exclude_from_training=[], notes={})
    for name, m in sorted(index.items()):
        f = ed_dir / f'{name}.xml'
        dup, ten = edition_pitches(f, 0), edition_pitches(f, 1)
        if len(dup) < 12:
            continue
        letters = [STEPS[x % 7] for x in ten]
        inc, gap = ''.join(letters[:10]), max(4, period(letters) - 2)
        fk = fol_key('f.' + m['folio'])
        cands = []
        ids = tuple(i for i, k in F if fk is not None and fk - 1 <= k <= fk + 1)
        if ids:
            cands.append(('F', ids))
        cands += [('W1', tuple(w)) for w in W1_windows if has_incipit(tuple(w), inc[:6])]
        best = None
        for ms, ids in cands:
            for cl in clausulae(ids, inc, gap):
                up = candr_pitches(cl.upper)
                d = semiglobal(dup, up) if up else -1.0
                t = contiguous_share(ten, candr_pitches(cl.tenor))
                val = d + t + (0.1 if ms == 'F' else 0)
                if best is None or val > best[-1]:
                    best = (d, t, ms, ids, val)
        if not best:
            continue
        d, t, ms, ids, _ = best
        if d < (0.75 if len(dup) < 20 else 0.6) or t < 0.8:
            continue
        run = f'{ms}:{ids[0]}-{ids[-1]}:{inc}:{gap}'
        spec['runs'][run] = dict(settings=list(ids), incipit=inc, min_gap=gap)
        spec['pieces'][name] = dict(edition=f'{name}.xml', run=run)
        spec['notes'][name] = f'{ms}; duplum fit {d:.2f}, tenor {t:.2f}'
        print(name, m['folio'], ms, f'{d:.2f} {t:.2f}', flush=True)

    # cross-validation groups
    ps = list(spec['pieces'])
    seq = {p: edition_pitches(ed_dir / spec['pieces'][p]['edition'], 0) for p in ps}
    parent = {p: p for p in ps}

    def find(x):
        while parent[x] != x:
            x = parent[x]
        return x
    for i, p in enumerate(ps):
        for q in ps[i + 1:]:
            x, y = sorted((seq[p], seq[q]), key=len)
            if p[:7] == q[:7] or (len(x) >= 0.5 * len(y) and semiglobal(x, y) >= 0.7):
                parent[find(p)] = find(q)
    g = defaultdict(list)
    for p in ps:
        g[find(p)].append(p)
    spec['groups'] = sorted(g.values())
    Path(a.out).write_text(json.dumps(spec, indent=1))
    print(f"{len(ps)} sections matched ({sum(v['run'].startswith('F') for v in spec['pieces'].values())} in F), "
          f"{len(spec['groups'])} groups -> {a.out}")


if __name__ == '__main__':
    main()
