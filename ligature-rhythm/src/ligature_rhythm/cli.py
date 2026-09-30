"""Command-line interface: ``ligature-rhythm {fetch,split,realise,evaluate,train,cv}``."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import candr, musicxml
from .features import Model, load_weights, save_weights
from .realise import realise
from .segment import guess_incipit, split


def _model(args) -> Model:
    return Model(load_weights(getattr(args, 'weights', None)))


def _settings(args) -> list:
    return [Path(args.candr_dir) / f'setting_{i:04d}.mei' for i in args.settings]


def cmd_fetch(args):
    candr.fetch(args.out, title=args.title, source=args.source, delay=args.delay, limit=args.limit,
                list_only=args.list_only)


def cmd_split(args):
    paths = _settings(args)
    inc = args.incipit or guess_incipit(paths)
    clausulae, head = split(paths, incipit=inc)
    print(f'incipit {inc}: {len(clausulae)} clausulae')
    for k, c in enumerate(clausulae):
        print(f'{k:3d}  {", ".join(Path(s).stem for s in c.settings)}')
        print('     upper:', candr.show(c.upper)[:120])
        print('     tenor:', candr.show(c.tenor)[:120])


def cmd_realise(args):
    paths = _settings(args)
    model = _model(args)
    clausulae, _ = split(paths, incipit=args.incipit or guess_incipit(paths))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for k, c in enumerate(clausulae):
        res = realise(c.upper, c.tenor, model)
        name = f'{args.prefix}_{k:02d}.musicxml'
        musicxml.write(out / name, res.upper, res.tenor, title=f'{args.prefix} {k}',
                       subtitle='from CANDR ' + ', '.join(Path(s).stem for s in c.settings))
        flags = []
        if res.info['synch_dropped']:
            flags.append(f"{len(res.info['synch_dropped'])} synchronisations dropped")
        if res.info['organum_like']:
            flags.append('looks like organum purum: not modal discant')
        print(f"{name}: modes {res.info['home_mode']}/{res.info['tenor_home']}"
              + (f"  [{'; '.join(flags)}]" if flags else ''))


def _bench(args):
    from .evaluate import Benchmark
    return Benchmark.load(args.spec, args.candr_dir, args.editions)


def cmd_evaluate(args):
    df = _bench(args).evaluate(_model(args))
    print(df.round(3).to_string())
    print('\nmean:\n' + df.select_dtypes('number').mean().round(3).to_string())
    if args.csv:
        df.to_csv(args.csv)


def cmd_train(args):
    from .train import fit_benchmark
    model = fit_benchmark(_bench(args), epochs=args.epochs, c_pa=args.c_pa)
    save_weights(model.w, args.out)
    print(f'wrote {args.out} ({len(model.w)} weights)')


def cmd_cv(args):
    from .train import cross_validate
    df = cross_validate(_bench(args), epochs=args.epochs, workers=args.workers, c_pa=args.c_pa)
    print(df.round(3).to_string())
    print('\nmean:\n' + df.select_dtypes('number').mean().round(3).to_string())
    if args.csv:
        df.to_csv(args.csv)


def main(argv=None):
    p = argparse.ArgumentParser(prog='ligature-rhythm', description=__doc__)
    p.add_argument('-v', '--verbose', action='store_true')
    sub = p.add_subparsers(dest='cmd', required=True)

    f = sub.add_parser('fetch', help='download CANDR settings as MEI')
    f.add_argument('--out', default='candr_mei')
    f.add_argument('--title')
    f.add_argument('--source')
    f.add_argument('--delay', type=float, default=4.0)
    f.add_argument('--limit', type=int)
    f.add_argument('--list-only', action='store_true')
    f.set_defaults(func=cmd_fetch)

    for name, fn, hlp in (('split', cmd_split, 'show how a run of settings is cut into clausulae'),
                          ('realise', cmd_realise, 'realise a run of settings and write MusicXML')):
        s = sub.add_parser(name, help=hlp)
        s.add_argument('settings', type=int, nargs='+', help='CANDR setting ids, in manuscript order')
        s.add_argument('--candr-dir', default='.')
        s.add_argument('--incipit', help="the chant's first pitch letters (default: guessed)")
        s.set_defaults(func=fn)
        if name == 'realise':
            s.add_argument('--out', default='.')
            s.add_argument('--prefix', default='clausula')
            s.add_argument('--weights', help="weights file, or 'default' / 'dominus' (packaged)")

    for name, fn, hlp in (('evaluate', cmd_evaluate, 'compare with edition encodings'),
                          ('train', cmd_train, 'tune weights on edition encodings'),
                          ('cv', cmd_cv, 'leave-one-group-out cross-validation (parallel)')):
        s = sub.add_parser(name, help=hlp)
        s.add_argument('spec', help='benchmark spec (JSON)')
        s.add_argument('--candr-dir', required=True)
        s.add_argument('--editions', required=True)
        s.set_defaults(func=fn)
        if name == 'evaluate':
            s.add_argument('--weights', help="weights file, or 'default' / 'dominus' (packaged)")
            s.add_argument('--csv')
        if name in ('train', 'cv'):
            s.add_argument('--epochs', type=int, default=8)
            s.add_argument('--c-pa', type=float, default=0.01,
                           help='largest step of each update (smaller = stays closer to the theory prior)')
        if name == 'train':
            s.add_argument('--out', default='weights.json')
        if name == 'cv':
            s.add_argument('--workers', type=int)
            s.add_argument('--csv')

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format='%(message)s')
    args.func(args)


if __name__ == '__main__':
    sys.exit(main())
