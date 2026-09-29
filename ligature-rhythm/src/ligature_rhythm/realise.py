"""Reading both voices of a clausula together, and turning the reading into timed events."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .decoder import HOMES, Reading, decode
from .features import Model
from .items import TENOR, UPPER, voice_items

SOFT_DROP = 3.0        # a tenor fitted to the upper voice's first reading may ignore a synch at this cost
CONSONANCE_MARGIN = 0.02   # the upper-first reading must beat tenor-first by this much on-beat consonance
STYLE_COUPLE = 4.0     # reward for both voices ending their ordines the same way
ORGANUM_RATIO = 5.5    # upper notes per tenor note above which a passage looks like organum purum
STEPS = 'cdefgab'


@dataclass
class Event:
    onset: int                       # sixteenths
    duration: int
    pitch: Optional[tuple]           # (step, alter, octave) or None for a rest
    lig: Optional[tuple] = None      # (ligature number, index, size, kind)
    plica: bool = False
    mode: Optional[int] = None
    note_id: Optional[str] = None


@dataclass
class Result:
    upper: list                      # [Event]
    tenor: list
    info: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- timing helpers
def item_times(items, values) -> list:
    out, t = [], 0
    for k in range(len(items)):
        out.append(t)
        t += values[k]
    return out


def synch_targets(src_items, src_values, dst_items, dst_is_upper: bool) -> dict:
    """{stroke item of dst: time at which src's next ordo starts} for strokes CANDR synchronises.
    The synch links are stored on the upper voice's strokes and point at tenor strokes."""
    st = item_times(src_items, src_values)
    times = {}
    for k, it in enumerate(src_items):
        if not it.is_note:
            ids = it.ids if dst_is_upper else it.synch
            for i in ids:
                times[i] = st[k] + src_values[k]
    out = {}
    for k, it in enumerate(dst_items):
        if not it.is_note:
            for i in (it.synch if dst_is_upper else it.ids):
                if i in times:
                    out[k] = times[i]
    return out


def ordo_starts(items, values) -> set:
    out, t, new = set(), 0, True
    for k, it in enumerate(items):
        if it.is_note:
            if new:
                out.add(t)
            new = False
        else:
            new = True
        t += values[k]
    return out


def line_of(items, values) -> dict:
    """time -> diatonic step number of the sounding note"""
    line, t = {}, 0
    for k, it in enumerate(items):
        if it.is_note:
            for x in range(t, t + values[k]):
                line[x] = it.note.step
        t += values[k]
    return line


def homorhythm(up_items, te_items, targets, te_values) -> dict:
    """Where both voices go note against note between two synchronised strokes, the tenor's value
    for each upper note."""
    st = item_times(te_items, te_values)
    t_ordo, cur, start = {}, [], 0
    for k, it in enumerate(te_items):
        if it.is_note:
            if not cur:
                start = st[k]
            cur.append(te_values[k])
        else:
            if cur:
                t_ordo[start] = (cur, st[k] + te_values[k])
            cur = []
    if cur:
        t_ordo[start] = (cur, None)
    out, prev_target, cur = {}, 0, []
    for k, it in enumerate(up_items):
        if it.is_note:
            cur.append(k)
        else:
            tg = targets.get(k)
            if cur and prev_target in t_ordo:
                vals, end = t_ordo[prev_target]
                if tg is not None and end == tg and len(vals) == len(cur):
                    out.update(zip(cur, vals))
            cur, prev_target = [], tg
    return out


# --------------------------------------------------------------------------- joint reading
def onbeat_consonance(ui, ti, ur: Reading, tr: Reading) -> float:
    """share of duplum notes on the first beat of a perfection that make a unison, fifth, fourth or
    octave with the tenor note sounding under them (editors put consonances on the beat)"""
    line = line_of(ti, tr.values)
    st = item_times(ui, ur.values)
    hits = [(abs(it.note.step - line[st[k]]) % 7) in (0, 3, 4)
            for k, it in enumerate(ui) if it.is_note and st[k] % 6 == 0 and st[k] in line]
    return sum(hits) / len(hits) if hits else 0.0


def read_pair(ui, ti, model: Model, rounds: int = 2, log: Optional[list] = None) -> tuple:
    """(tenor Reading, upper Reading, which voice led). Either voice may lead: the tenor read alone
    and the upper voice fitted to it, or the upper voice alone and the tenor fitted to it (softly),
    then the upper voice again. A tenor is in the fifth mode or in the upper voice's mode. The
    reading that puts more consonances on the beat wins (tenor-first unless upper-first is clearly
    better); the two usually agree wherever CANDR marks enough synchronisations."""
    best = None
    cp = lambda r: {r.style: STYLE_COUPLE}
    te_homes = lambda ur: tuple(sorted({5, ur.home}))
    up_homes = lambda tr: HOMES[UPPER] if tr.home == 5 else (tr.home,)

    def upper_for(tres):
        tg = synch_targets(ti, tres.values, ui, True)
        return decode(ui, UPPER, model, targets=tg, homo=homorhythm(ui, ti, tg, tres.values),
                      style_bonus=cp(tres), home=up_homes(tres), line=line_of(ti, tres.values),
                      starts=ordo_starts(ti, tres.values), end=tres.end_time)

    def tenor_for(ures):
        return decode(ti, TENOR, model, targets=synch_targets(ui, ures.values, ti, False),
                      style_bonus=cp(ures), home=te_homes(ures), drop=SOFT_DROP, end=ures.end_time)

    for how in ('tenor-first', 'upper-first'):
        tres = decode(ti, TENOR, model) if how == 'tenor-first' else tenor_for(decode(ui, UPPER, model))
        for _ in range(rounds):
            t2 = tenor_for(upper_for(tres))
            if t2.values == tres.values:
                break
            tres = t2
        ures = upper_for(tres)
        cons = onbeat_consonance(ui, ti, ures, tres)
        if log is not None:
            log.append((how, cons, tres, ures))
        if best is None or cons > best[0] + CONSONANCE_MARGIN:
            best = (cons, tres, ures, how)
    return best[1], best[2], best[3]


def realise(upper_tokens, tenor_tokens, model: Optional[Model] = None) -> Result:
    """Realise both voices of a clausula (tokens from candr.parse_mei / segment.split)."""
    model = model or Model()
    ui, ti = voice_items(upper_tokens, UPPER), voice_items(tenor_tokens, TENOR)
    tres, ures, how = read_pair(ui, ti, model)
    tg = synch_targets(ti, tres.values, ui, True)
    n_up = sum(it.is_note for it in ui)
    n_te = sum(it.is_note for it in ti)
    info = dict(home_mode=ures.home, tenor_home=tres.home, upper_style=ures.style, tenor_style=tres.style,
                lead=how, synch_used=len(tg), synch_dropped=ures.dropped,
                homorhythm_notes=len(homorhythm(ui, ti, tg, tres.values)),
                organum_like=n_te > 0 and n_up / n_te > ORGANUM_RATIO)
    return Result(events(ui, ures), events(ti, tres), info)


# --------------------------------------------------------------------------- events
def pitch(n, oct_shift: int = 1) -> tuple:
    # flats fall on B (and occasionally E); a flat CANDR attaches to another note is almost always
    # a sign drawn on the B line and attributed to the wrong note
    alt = -1 if (n.accid == 'f' and n.pname in 'be') else (1 if n.accid == 's' else 0)
    return n.pname.upper(), alt, n.oct + oct_shift


def plica_pitch(n, oct_shift: int = 1) -> tuple:
    """a step in the plica's direction"""
    i = STEPS.index(n.pname) + 7 * n.oct + (1 if n.plica == 'up' else -1)
    p, o = STEPS[i % 7], i // 7
    return p.upper(), -1 if (p == 'b' and n.accid == 'f') else 0, o + oct_shift


def events(items, r: Reading, oct_shift: int = 1) -> list:
    ev, t, lig_id = [], 0, 0
    for k, it in enumerate(items):
        val, m = r.values[k], r.modes[k]
        if not it.is_note:
            if val:
                ev.append(Event(t, val, None, mode=m))
            t += val
            continue
        n = it.note
        if it.lig and it.i == 0:
            lig_id += 1
        lig = (lig_id, it.i, it.lig, it.ltype) if it.lig else None
        if n.plica:
            d1 = val - 2 if val >= 4 else val // 2        # the plica note takes a breve
            ev.append(Event(t, d1, pitch(n, oct_shift), lig, False, m, n.id))
            ev.append(Event(t + d1, val - d1, plica_pitch(n, oct_shift), None, True, m, n.id))
        else:
            ev.append(Event(t, val, pitch(n, oct_shift), lig, False, m, n.id))
        t += val
    return ev
