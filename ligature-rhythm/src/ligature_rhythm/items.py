"""A voice as the reader sees it: a sequence of note items and stroke items with their context."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .candr import Ligature, Note, Stroke

UPPER, TENOR = 'up', 'te'


@dataclass
class Item:
    kind: str                         # 'n' (note) or 's' (stroke)
    # notes
    note: Optional[Note] = None
    lig: int = 0                      # size of the ligature the note belongs to (0 = single note)
    i: int = 0                        # position in the ligature
    ltype: Optional[str] = None       # 'square' / 'currentes'
    ctx: str = ''                     # notational context, e.g. 'S', 'L3.0', 'Cn.z', 'S+pl'
    next: str = ''                    # what follows: 'end' (stroke/end), 'S', 'lig' (new ligature), 'in'
    first: bool = False
    last: bool = False
    final: bool = False               # last note of the voice
    osig: Optional[tuple] = None      # on an ordo's first note: its ligature pattern
    # strokes
    ids: list = field(default_factory=list)
    synch: list = field(default_factory=list)
    length: float = 0.0
    after: str = '-'                  # context of the note before the stroke
    # both
    short: bool = False               # ordo of one or two single notes (a stroke there just separates)

    @property
    def is_note(self) -> bool:
        return self.kind == 'n'


def ctx_name(it: Item) -> str:
    k, i = it.lig, it.i
    if k == 0:
        c = 'S'
    else:
        head = 'C' if it.ltype == 'currentes' else 'L'
        if k <= 3:
            c = f'{head}{k}.{i}'
        else:
            c = f'{head}n.' + ('0' if i == 0 else 'z' if i == k - 1 else 'p' if i == k - 2 else 'm')
    if it.note.plica:
        c += '+pl'
    return c


def voice_items(tokens, voice: str = UPPER) -> list:
    """tokens of one voice -> [Item]. Consecutive strokes merge; leading strokes are dropped."""
    items: list = []
    for t in tokens:
        if isinstance(t, Stroke):
            if items and items[-1].kind == 's':
                s = items[-1]
                s.ids.append(t.id)
                s.length = max(s.length, t.length)
                if t.synch:
                    s.synch.append(t.synch)
            elif items:
                items.append(Item('s', ids=[t.id], synch=[t.synch] if t.synch else [], length=t.length))
        elif isinstance(t, Note):
            items.append(Item('n', note=t))
        elif isinstance(t, Ligature):
            for i, x in enumerate(t.notes):
                items.append(Item('n', note=x, lig=len(t.notes), i=i, ltype=t.kind))
    # a stroke after one or two single notes in the upper voice (one in the tenor) usually just
    # separates the notes
    short_max = 2 if voice == UPPER else 1
    ordo: list = []

    def close():
        if not ordo:
            return
        singles = all(o.lig == 0 for o in ordo)
        groups = [min(o.lig, 4) if o.lig else 1 for o in ordo if o.lig == 0 or o.i == 0]
        ordo[0].osig = (groups[0], groups[-1], tuple(groups[:2]), tuple(groups[-2:]))
        for j, o in enumerate(ordo):
            o.first, o.last = j == 0, j == len(ordo) - 1
            o.short = singles and len(ordo) <= short_max
        ordo.clear()

    for it in items:
        if it.kind == 's':
            close()
        else:
            ordo.append(it)
    close()
    note_idx = [k for k, x in enumerate(items) if x.is_note]
    if note_idx:
        items[note_idx[-1]].final = True
    for k, it in enumerate(items):
        if it.is_note:
            it.ctx = ctx_name(it)
            nxt = items[k + 1] if k + 1 < len(items) else None
            it.next = ('end' if nxt is None or not nxt.is_note else
                       'S' if nxt.lig == 0 else 'lig' if nxt.i == 0 else 'in')
        else:
            j = k - 1
            prev_notes = []
            while j >= 0 and items[j].is_note:
                prev_notes.append(items[j])
                j -= 1
            it.short = bool(prev_notes) and prev_notes[0].short
            it.after = prev_notes[0].ctx if prev_notes else '-'
    return items
