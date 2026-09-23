"""Yalniz Expert'i olan (elle yapilmis) .chart'lara eksik Hard / Medium / Easy uretimi.

Notalar Expert'ten SECILIR (zamanlari degismez: senkron elle yapilmis chart kadar iyi kalir); secim, perde
daraltma (Medium 4, Easy 3 perde) ve sustain kirpma otomatik chart'in indirgeme kurallariyla (charter.reduce_*)
yapilir. Star Power cumleleri ve solo isaretleri Expert bolumunden kopyalanir. Tick'ler charter'in RES
cozunurlugune olceklenip islenir, yazarken chart'in kendi tick'lerine geri donulur.
"""
from __future__ import annotations

import re

from .charter import RES, SECTION_NAMES, GNote, reduce_easy, reduce_hard, reduce_medium

_BLOCK = re.compile(r"^\[([^\]\r\n]+)\][ \t]*\r?\n\{(.*?)^\}", re.M | re.S)
_TS = re.compile(r"^\s*(\d+)\s*=\s*TS\s+(\d+)(?:\s+(\d+))?", re.M)
_COPY = re.compile(r"^\s*(\d+)\s*=\s*(S\s+2\s+\d+|E\s+solo|E\s+soloend)\s*$", re.M)
REDUCERS = {"hard": reduce_hard, "medium": reduce_medium, "easy": reduce_easy}


def _bar_ticks(sync_body: str, res: int, last_tick: int) -> set[int]:
    ts = sorted((int(t), int(n), int(d) if d else 2) for t, n, d in _TS.findall(sync_body)) or [(0, 4, 2)]
    bars: set[int] = set()
    for i, (t, num, dexp) in enumerate(ts):
        end = ts[i + 1][0] if i + 1 < len(ts) else last_tick + 1
        step = max(1, int(round(res * num * 4 / (2 ** dexp))))
        b = t
        while b < end:
            bars.add(b)
            b += step
    return bars


def fill_missing_difficulties(text: str) -> tuple[str, list[str]]:
    """(yeni metin, uretilen zorluklar). Expert yoksa ya da hicbir zorluk eksik degilse metin aynen doner."""
    from ..chart import parse_chart
    chart = parse_chart(text)
    ex = chart.tracks.get("expert")
    missing = [d for d in ("hard", "medium", "easy") if d not in chart.tracks]
    if ex is None or not ex.notes or not missing:
        return text, []
    res = chart.resolution
    scale = RES / res
    blocks = {m.group(1).strip(): m for m in _BLOCK.finditer(text)}
    ex_block = blocks.get(SECTION_NAMES["expert"])
    sync = blocks.get("SyncTrack")
    if ex_block is None:
        return text, []
    orig: dict[int, int] = {}
    gnotes: list[GNote] = []
    for n in ex.notes:
        t = int(round(n.tick * scale))
        if t in orig:
            continue
        orig[t] = n.tick
        length = int(round(n.length_ticks * scale))
        gnotes.append(GNote(tick=t, time=n.time, strength=0.5 + 0.1 * n.is_chord + 0.1 * (length > 0),
                            fret=(n.mask & -n.mask).bit_length() - 1 if n.mask else 0, mask=n.mask, length=length))
    last = max(orig.values())
    bars = {int(round(b * scale)) for b in _bar_ticks(sync.group(2) if sync else "", res, last)}
    shared = [(int(t), s) for t, s in _COPY.findall(ex_block.group(2))]
    new_blocks = []
    for d in missing:
        rows = []
        for n in REDUCERS[d](gnotes, bars):
            tick = orig[n.tick]
            ln = int(round(n.length / scale))
            if n.mask == 0:
                rows.append((tick, 0, f"N 7 {ln}"))
            else:
                rows += [(tick, 0, f"N {f} {ln}") for f in range(5) if n.mask >> f & 1]
        rows += [(t, 1, " ".join(s.split())) for t, s in shared]
        body = "".join(f"  {t} = {s}\n" for t, _k, s in sorted(rows))
        new_blocks.append(f"[{SECTION_NAMES[d]}]\n{{\n{body}}}\n")
    nl = "\r\n" if "\r\n" in text else "\n"
    joined = "".join(new_blocks).replace("\n", nl).rstrip(nl)
    at = ex_block.end()                        # Expert bolumunun '}' karakterinden hemen sonra
    return text[:at] + nl + joined + text[at:], missing


def fill_chart_file(path: str) -> list[str]:
    """notes.chart'i yerinde tamamla (once .bak). Uretilen zorluklari dondur."""
    from ..chart.song_ini import read_text_file
    text = read_text_file(path)
    new, made = fill_missing_difficulties(text)
    if made:
        import shutil
        shutil.copyfile(path, path + ".bak")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(new)
    return made


__all__ = ["fill_missing_difficulties", "fill_chart_file"]
