"""Reading CANDR (Clausula Archive of the Notre Dame Repertory) data.

CANDR publishes each *setting* (one system of a manuscript page, both voices) as diplomatic MEI:
pitches, ligatures (square or currentes), plicae, strokes (divisiones) with their drawn length, and
``@synch`` links between simultaneous events in the two voices. There are no note values.

This module parses that MEI into plain Python objects and downloads settings politely.
"""
from __future__ import annotations

import csv
import html
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Union

MEI = '{http://www.music-encoding.org/ns/mei}'
XML_ID = '{http://www.w3.org/XML/1998/namespace}id'
BASE_URL = 'https://www.candr.org.uk'
USER_AGENT = 'ligature-rhythm (musicology research; polite single-thread downloader)'


# --------------------------------------------------------------------------- data model
@dataclass
class Note:
    pname: str                       # 'c' .. 'b'
    oct: int                         # CANDR octave (scientific octave - 1)
    id: str
    accid: Optional[str] = None      # gestural accidental: 'f' or 's'
    plica: Optional[str] = None      # 'up' / 'down'
    synch: Optional[str] = None      # id of a simultaneous event in the other voice

    @property
    def step(self) -> int:
        """diatonic step number (7 per octave)"""
        return 7 * self.oct + 'cdefgab'.index(self.pname)


@dataclass
class Ligature:
    kind: str                        # 'square' or 'currentes'
    notes: list


@dataclass
class Stroke:
    length: float                    # drawn length (staff spaces)
    id: str
    synch: Optional[str] = None


@dataclass
class Other:
    kind: str                        # clef, accid, ... (kept for completeness)
    attrs: dict = field(default_factory=dict)


Token = Union[Note, Ligature, Stroke, Other]


def notes_of(tok: Token) -> list:
    if isinstance(tok, Note):
        return [tok]
    if isinstance(tok, Ligature):
        return tok.notes
    return []


# --------------------------------------------------------------------------- parsing
def _attr(e, k):
    v = e.get(MEI + k)
    return v if v is not None else e.get(k)


def _synch(e):
    return (_attr(e, 'synch') or '').lstrip('#') or None


def _note(e) -> Note:
    pl = e.find(MEI + 'plica')
    return Note(pname=_attr(e, 'pname'), oct=int(_attr(e, 'oct')), id=e.get(XML_ID),
                accid=_attr(e, 'accid.ges'), plica=_attr(pl, 'dir') if pl is not None else None,
                synch=_synch(e))


def parse_mei(path: Union[str, Path]) -> dict:
    """Parse one CANDR setting. Returns {staff number: [tokens]} (staff '1' = upper voice)."""
    root = ET.parse(path).getroot()
    voices: dict = {}
    for staff in root.iter(MEI + 'staff'):
        toks = voices.setdefault(_attr(staff, 'n'), [])
        for layer in staff.findall(MEI + 'layer'):
            for e in layer:
                tag = e.tag.replace(MEI, '')
                if tag == 'ligature':
                    toks.append(Ligature(_attr(e, 'type'), [_note(x) for x in e.findall(MEI + 'note')]))
                elif tag == 'note':
                    toks.append(_note(e))
                elif tag == 'divisione':
                    toks.append(Stroke(float(_attr(e, 'len') or 0), e.get(XML_ID), _synch(e)))
                elif tag in ('pb', 'sb'):
                    continue
                else:
                    toks.append(Other(tag, {k.replace(MEI, ''): v for k, v in e.attrib.items()}))
    return voices


def upper_and_tenor(path) -> tuple:
    """(upper-voice tokens, tenor tokens) of a two-voice setting"""
    v = parse_mei(path)
    keys = sorted(v)
    return v[keys[0]], v[keys[-1]]


def show(tokens: Iterable[Token]) -> str:
    """compact notation: (square ligature) {currentes} ^/v plica, | stroke, || long stroke"""
    out = []
    for t in tokens:
        mark = lambda n: n.pname.upper() + ('^' if n.plica == 'up' else 'v' if n.plica == 'down' else '')
        if isinstance(t, Ligature):
            o, c = ('(', ')') if t.kind == 'square' else ('{', '}')
            out.append(o + ''.join(mark(n) for n in t.notes) + c)
        elif isinstance(t, Note):
            out.append(mark(t))
        elif isinstance(t, Stroke):
            out.append('|' if t.length < 3.6 else '||')
    return ' '.join(out)


# --------------------------------------------------------------------------- downloading
def _get(url: str, tries: int = 8, first_wait: float = 30) -> Optional[bytes]:
    wait = first_wait
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            ra = e.headers.get('Retry-After') if e.headers else None
            pause = int(ra) if (ra or '').isdigit() else wait
            print(f'  HTTP {e.code} on {url}; waiting {pause}s ({attempt}/{tries})', file=sys.stderr)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            pause = wait
            print(f'  {e} on {url}; waiting {pause}s ({attempt}/{tries})', file=sys.stderr)
        time.sleep(pause + random.uniform(0, 5))
        wait = min(wait * 2, 600)
    raise RuntimeError(f'gave up on {url}')


def list_settings(page: Optional[str] = None) -> list:
    """All settings listed at /browse/setting/, in page order: [{id, title, folio, source}]."""
    page = page if page is not None else _get(BASE_URL + '/browse/setting/').decode('utf-8')
    heads = [(m.start(), html.unescape(re.sub('<[^>]+>', '', m.group(1))).strip())
             for m in re.finditer(r'<h[23][^>]*>(.*?)</h[23]>', page, re.S)]
    pat = (r'href="/browse/setting/(\d+)/"[^>]*>\s*(.*?)\s*</a>'
           r'\s*(?:<a class="inline" href="/browse/folio/\d+/">\s*<i>\(([^)]*)\)</i>)?')
    rows, seen = [], set()
    for m in re.finditer(pat, page, re.S):
        sid = int(m.group(1))
        if sid in seen:
            continue
        seen.add(sid)
        src = ''
        for pos, name in heads:
            if pos < m.start():
                src = name
        rows.append(dict(id=sid, title=html.unescape(re.sub(r'\s+', ' ', m.group(2))).strip(),
                         folio=(m.group(3) or '').strip(), source=src))
    return rows


def fetch(out: Union[str, Path], title: Optional[str] = None, source: Optional[str] = None,
          delay: float = 4.0, limit: Optional[int] = None, list_only: bool = False) -> list:
    """Download settings as ``setting_<id>.mei`` into ``out`` (resumable) and write manifest.csv.
    ``title``/``source`` are case-insensitive regexes on the setting title / manuscript heading."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    settings = list_settings()
    if title:
        settings = [s for s in settings if re.search(title, s['title'], re.I)]
    if source:
        settings = [s for s in settings if re.search(source, s['source'], re.I)]
    for s in settings:
        s['file'] = f"setting_{s['id']:04d}.mei"
    with open(out / 'manifest.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['id', 'title', 'source', 'folio', 'file'])
        w.writeheader()
        w.writerows(settings)
    if list_only:
        return settings
    done = 0
    for i, s in enumerate(settings, 1):
        path = out / s['file']
        if path.exists() and path.stat().st_size > 0:
            continue
        time.sleep(delay + random.uniform(0, delay / 2))
        data = _get(f"{BASE_URL}/browse/setting/{s['id']}/mei/")
        if data is None:
            print(f"[{i}/{len(settings)}] {s['id']} not found (404)")
            continue
        tmp = path.with_suffix('.part')
        tmp.write_bytes(data)
        os.replace(tmp, path)                 # never leaves a half-written file behind
        done += 1
        print(f"[{i}/{len(settings)}] {s['id']} {s['title'][:40]} ({s['source'][:20]} {s['folio']})")
        if limit and done >= limit:
            break
    return settings
