"""melodic-reduction command line.

    melodic-reduction analyze SCORE [--part 0] [--reference auto] [--weights default] [--json out.json]
    melodic-reduction reduce SCORE --json analysis.json --out reduction.musicxml [--levels fundamental span:4]
    melodic-reduction corpus DIR --out results/        # every .xml/.musicxml/.mxl in DIR
    melodic-reduction gttm DIR                          # benchmark against the GTTM database
    melodic-reduction fit DIR --out weights.json        # fit salience weights on the GTTM database
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

from .analyze import analyze, summary, write_json


def _ref(x):
    if x in (None, 'auto'):
        return 'auto'
    if x in ('none', 'None', ''):
        return None
    return int(x)


def main(argv=None):
    ap = argparse.ArgumentParser(prog='melodic-reduction')
    sub = ap.add_subparsers(dest='cmd', required=True)

    a = sub.add_parser('analyze', help='reduce one voice of a score')
    a.add_argument('score')
    a.add_argument('--part', type=int, default=0)
    a.add_argument('--reference', default='auto', help="part index, 'auto' or 'none'")
    a.add_argument('--weights', default='default')
    a.add_argument('--fundamental', default='auto', help="auto | span:T | height:H | count:K | notes:1,5,9")
    a.add_argument('--frame', default='notes', choices=['notes', 'virtual'])
    a.add_argument('--unit', type=float, default=None, help='quarterLength of one unit (default: a bar)')
    a.add_argument('--json', default=None, help='write the full analysis here')
    a.add_argument('--no-modules', action='store_true')

    r = sub.add_parser('reduce', help='write reduction staves above the score (music21 ScoreReduction)')
    r.add_argument('score')
    r.add_argument('--json', required=True, help='analysis from `analyze --json`')
    r.add_argument('--out', required=True)
    r.add_argument('--levels', nargs='+', default=['fundamental', 'span:4'])

    c = sub.add_parser('corpus', help='analyse every score in a folder')
    c.add_argument('folder')
    c.add_argument('--out', required=True)
    c.add_argument('--part', type=int, default=0)
    c.add_argument('--weights', default='default')

    g = sub.add_parser('gttm', help='benchmark on the GTTM database (folders of MusicXML + TS-*.xml)')
    g.add_argument('folder')
    g.add_argument('--weights', default='default')
    g.add_argument('--frame', default='virtual', choices=['notes', 'virtual'])

    f = sub.add_parser('fit', help='fit salience weights on the GTTM database')
    f.add_argument('folder')
    f.add_argument('--out', required=True)
    f.add_argument('--start', default='default')
    f.add_argument('--rounds', type=int, default=2)

    args = ap.parse_args(argv)
    if args.cmd == 'analyze':
        res = analyze(args.score, part=args.part, reference=_ref(args.reference), weights=args.weights,
                      unit=args.unit, fundamental=args.fundamental, modules=not args.no_modules,
                      frame=args.frame)
        print(summary(res))
        if args.json:
            write_json(res, args.json)
            print(f'wrote {args.json}')
    elif args.cmd == 'reduce':
        from .export import write_reduction
        res = json.load(open(args.json))
        write_reduction(args.score, res, args.out, levels=args.levels)
        print(f'wrote {args.out}')
    elif args.cmd == 'corpus':
        os.makedirs(args.out, exist_ok=True)
        files = sorted(sum((glob.glob(os.path.join(args.folder, p)) for p in ('*.xml', '*.musicxml', '*.mxl')), []))
        rows = []
        for fn in files:
            name = os.path.splitext(os.path.basename(fn))[0]
            try:
                res = analyze(fn, part=args.part, weights=args.weights)
            except Exception as e:
                print(f'{name}: failed ({e})')
                continue
            write_json(res, os.path.join(args.out, name + '.json'))
            fl = [res['notes'][i]['pitch'] for i in res['fundamental']['notes']]
            rows.append({'piece': name, 'notes': len(res['notes']), 'fundamental': ' '.join(fl),
                         'focal': '; '.join(f"{d['pitch']} m{d['measures'][0]}-{d['measures'][1]} x{d['returns']}"
                                            for d in res['dominant_focal_pitches'])})
            print(f"{name}: {' '.join(fl)} | {rows[-1]['focal']}")
        import csv
        with open(os.path.join(args.out, 'summary.csv'), 'w', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=['piece', 'notes', 'fundamental', 'focal'])
            w.writeheader()
            w.writerows(rows)
    elif args.cmd == 'gttm':
        from . import gttm
        rows = gttm.evaluate(args.folder, weights=args.weights, frame=args.frame)
        print(json.dumps(gttm.report(rows), indent=1))
    elif args.cmd == 'fit':
        from .fit import fit
        fit(args.folder, start=args.start, rounds=args.rounds, out=args.out)


if __name__ == '__main__':
    main()
