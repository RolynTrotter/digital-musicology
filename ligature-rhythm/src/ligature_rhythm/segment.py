"""Cutting a run of CANDR settings into clausulae.

CANDR settings follow the page layout (one system each), not the pieces: a clausula's first tenor
notes often close the previous system, and its upper voice often runs over into the next one.
A new clausula is found where

* the tenor starts the chant again (its incipit, allowing a couple of mismatches), **and**
* that restart sits at a system break (the restart note opens or closes a setting), or CANDR marks
  the tenor's first notes as sounding with an upper-voice note.

A restart in the middle of a setting with nothing marked is a second cursus of the same clausula.

The upper voice of the new clausula starts at the note CANDR synchronises with the tenor's first
note; failing that, after the upper stroke CANDR synchronises with the tenor stroke that closes the
previous cursus; failing that, after a very long stroke in the first half of the setting holding
the new tenor, or at that setting's start.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from .candr import Note, Stroke, notes_of, upper_and_tenor

log = logging.getLogger(__name__)


@dataclass
class Clausula:
    upper: list                      # tokens
    tenor: list
    settings: list = field(default_factory=list)   # setting files it draws on


def _letters(tokens) -> list:
    return [n.pname + str(n.oct) for t in tokens for n in notes_of(t)]


def chain(paths: Sequence) -> tuple:
    """Concatenate consecutive settings voice by voice -> ([(setting index, token)], [...]).
    A setting whose upper voice repeats the previous one (a CANDR double entry) is skipped."""
    up, te, prev = [], [], None
    for si, p in enumerate(paths):
        u, t = upper_and_tenor(p)
        if prev is not None and _letters(u) == prev:
            log.info('%s repeats the previous upper voice; skipped as a duplicate entry', p)
            continue
        prev = _letters(u)
        up += [(si, x) for x in u]
        te += [(si, x) for x in t]
    return up, te


def _note_index(tokens) -> list:
    return [(i, n) for i, (_, t) in enumerate(tokens) for n in notes_of(t)]


def restarts(tenor_notes, incipit: str, max_mismatch: int = 2, min_gap: int = 40) -> list:
    """indices (into the tenor's notes) where the chant incipit starts"""
    letters = [n.pname.upper() for _, n in tenor_notes]
    k, hits = len(incipit), []
    for i in range(len(letters) - k + 1):
        mis = sum(a != b for a, b in zip(letters[i:i + k], incipit))
        if mis <= max_mismatch and (not hits or i - hits[-1] >= min_gap):
            hits.append(i)
    return hits


def guess_incipit(paths: Sequence, k: int = 13) -> Optional[str]:
    """The chant's first k pitch letters, from the first tenor note CANDR marks as sounding with an
    upper-voice note (CANDR marks the first notes of a piece this way). Check it against the chant."""
    up, te = chain(paths)
    uid = {n.id for _, n in _note_index(up)}
    tn = _note_index(te)
    for i, (_, n) in enumerate(tn):
        if n.synch and n.synch in uid and i + k <= len(tn):
            return ''.join(x.pname.upper() for _, x in tn[i:i + k])
    return None


def split(paths: Sequence, incipit: Optional[str] = None, very_long: float = 6.2, min_gap: int = 40) -> tuple:
    """Cut a run of consecutive settings (manuscript order) into clausulae.
    Returns ([Clausula], head) where head holds the material before the first clausula.
    `min_gap`: fewest tenor notes between two chant restarts (shorter than the chant)."""
    paths = [str(p) for p in paths]
    incipit = incipit or guess_incipit(paths)
    if not incipit:
        raise ValueError('no incipit given and none could be guessed')
    up, te = chain(paths)
    un, tn = _note_index(up), _note_index(te)
    uid = {n.id: i for i, (_, n) in enumerate(un)}
    up_stroke_synch = {t.synch: i for i, (_, t) in enumerate(up) if isinstance(t, Stroke) and t.synch}
    cuts = []
    for r in restarts(tn, incipit, min_gap=min_gap):
        t_tok = tn[r][0]
        u_tok = None
        for rr in range(r, min(r + 3, len(tn))):
            s = tn[rr][1].synch
            if s and s in uid:
                u_tok = un[uid[s]][0]
                break
        setting = te[t_tok][0]
        pos = [i for i, (tk, _) in enumerate(tn) if te[tk][0] == setting]
        k_in = pos.index(r)
        if not (u_tok is not None or r == 0 or k_in <= 1 or k_in >= len(pos) - 3):
            continue                                   # a second cursus of the same clausula
        if u_tok is None:
            k = t_tok - 1
            while k >= 0 and not isinstance(te[k][1], (Stroke, Note)) and not notes_of(te[k][1]):
                k -= 1
            if k >= 0 and isinstance(te[k][1], Stroke) and te[k][1].id in up_stroke_synch:
                u_tok = up_stroke_synch[te[k][1].id] + 1
                if cuts and u_tok <= cuts[-1][0]:
                    u_tok = None
        if u_tok is None:
            body = te[tn[min(r + 2, len(tn) - 1)][0]][0]
            in_body = [i for i, (s2, _) in enumerate(up) if s2 == body]
            if not in_body:
                continue
            u_tok = in_body[0]
            total = sum(len(notes_of(up[i][1])) for i in in_body)
            seen = 0
            for i in in_body:
                t = up[i][1]
                if isinstance(t, Stroke) and t.length >= very_long and seen <= 0.5 * total:
                    u_tok = i + 1
                    break
                seen += len(notes_of(t))
            if cuts and u_tok <= cuts[-1][0]:
                continue
        cuts.append((u_tok, t_tok))
    out = []
    for k, (u0, t0) in enumerate(cuts):
        u1, t1 = cuts[k + 1] if k + 1 < len(cuts) else (len(up), len(te))
        used = sorted({paths[s] for s, _ in up[u0:u1]} | {paths[s] for s, _ in te[t0:t1]})
        out.append(Clausula([t for _, t in up[u0:u1]], [t for _, t in te[t0:t1]], used))
    head = Clausula([t for _, t in up[:cuts[0][0]]], [t for _, t in te[:cuts[0][1]]]) if cuts else None
    return out, head
