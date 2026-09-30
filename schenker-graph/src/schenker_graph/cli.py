"""schenker-graph command line.

    schenker-graph SCORE [--analysis a.json] [--graph spec.json] [--out out/name]
                   [--part 0] [--stacked fundamental span:4] [--middleground auto|span:T|none]
                   [--modules 4] [--no-focal] [--no-slurs] [--formats svg png pdf]
"""
from __future__ import annotations

import argparse
import json

from .graph import schenker_graph


def main(argv=None):
    ap = argparse.ArgumentParser(prog='schenker-graph')
    ap.add_argument('score')
    ap.add_argument('--analysis', help='melodic-reduction JSON (default: analyse now)')
    ap.add_argument('--graph', help='JSON spec that adds to (or, with "replace": true, replaces) the automatic overlays')
    ap.add_argument('--out', default='graph')
    ap.add_argument('--part', type=int, default=0)
    ap.add_argument('--stacked', nargs='*', default=None,
                    help="add reduction staves above the score, e.g. --stacked fundamental span:4")
    ap.add_argument('--middleground', default='auto')
    ap.add_argument('--modules', type=int, default=4)
    ap.add_argument('--module-brackets', action='store_true', help='bracket whole module occurrences')
    ap.add_argument('--no-focal', action='store_true')
    ap.add_argument('--no-slurs', action='store_true')
    ap.add_argument('--formats', nargs='+', default=['svg', 'png', 'pdf'])
    ap.add_argument('--title', default=None)
    args = ap.parse_args(argv)

    graph = json.load(open(args.graph)) if args.graph else None
    if args.title:
        graph = dict(graph or {})
        graph['title'] = args.title
    mg = None if args.middleground in ('none', 'None') else args.middleground
    stacked = tuple(args.stacked) if args.stacked else None
    if args.stacked is not None and not args.stacked:
        stacked = ('fundamental', 'span:4')
    files, g, a = schenker_graph(args.score, analysis=args.analysis, graph=graph, out_prefix=args.out,
                                 part=args.part, stacked=stacked, middleground=mg, modules=args.modules,
                                 module_brackets=args.module_brackets, focal=not args.no_focal,
                                 slurs=not args.no_slurs, formats=tuple(args.formats))
    fl = ' '.join(a['notes'][i]['pitch'] for i in g.fundamental)
    print(f'fundamental line: {fl}')
    for f in files:
        print(f'wrote {f}')


if __name__ == '__main__':
    main()
