""".chart (Feedback / Moonscraper) okuyucu (ek-01 §2.1).

parse_chart(path_or_text, info=None) -> Chart
Yalniz 5-fret lead gitar ([EasySingle] .. [ExpertSingle]) okunur; diger enstrumanlar yok sayilir.
"""
from __future__ import annotations

import os

from ..models import Chart, Section, SongInfo
from ..timing import TempoChange, TempoMap, TimeSignature
from .hopo import (OPEN_FRET, build_track, chart_hopo_threshold, compute_end_time, is_end_event,
                   section_name)
from .song_ini import read_text_file

TRACK_SECTIONS = {
    "easysingle": "easy",
    "mediumsingle": "medium",
    "hardsingle": "hard",
    "expertsingle": "expert",
}


def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    if s.startswith('"'):
        return s[1:]
    return s


def _looks_like_text(s: str) -> bool:
    return "\n" in s or "\r" in s or s.lstrip("﻿ \t").startswith("[")


def _split_sections(text: str) -> list[tuple[str, list[str]]]:
    """[(bolum_adi, [satirlar])]. Parantez yapisina toleransli."""
    sections: list[tuple[str, list[str]]] = []
    current: list[str] | None = None
    for raw in text.splitlines():
        line = raw.strip().lstrip("﻿").strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            current = []
            sections.append((line[1:-1].strip(), current))
            continue
        if line in ("{", "}"):
            continue
        if current is not None:
            current.append(line)
    return sections


def _parse_tick_line(line: str) -> tuple[int, str, str] | None:
    """'768 = N 0 0' -> (768, 'N', '0 0'). Gecersizse None."""
    if "=" not in line:
        return None
    left, right = line.split("=", 1)
    try:
        tick = int(left.strip())
    except ValueError:
        return None
    right = right.strip()
    if not right:
        return None
    parts = right.split(None, 1)
    return tick, parts[0].upper(), (parts[1] if len(parts) > 1 else "")


def _ints(s: str) -> list[int]:
    out = []
    for p in s.split():
        try:
            out.append(int(p))
        except ValueError:
            try:
                out.append(int(float(p)))
            except ValueError:
                break
    return out


def _apply_chart_meta(meta: dict[str, str], info: SongInfo) -> None:
    """[Song] etiketleri yalniz song.ini'nin doldurmadigi alanlari doldurur."""
    if meta.get("name") and info.name in ("", "Unknown"):
        info.name = meta["name"]
    if meta.get("artist") and info.artist in ("", "Unknown"):
        info.artist = meta["artist"]
    for key, attr in (("album", "album"), ("genre", "genre"), ("charter", "charter")):
        if meta.get(key) and not getattr(info, attr):
            setattr(info, attr, meta[key])
    year = meta.get("year", "").lstrip(", ").strip()
    if year and not info.year:
        info.year = year
    if not info.preview_start_ms and meta.get("previewstart"):
        try:
            info.preview_start_ms = int(float(meta["previewstart"]) * 1000)
        except ValueError:
            pass


def parse_chart(path_or_text: str | os.PathLike, info: SongInfo | None = None) -> Chart:
    """.chart dosya yolu veya metni -> Chart. `info` verilirse (song.ini'den) kullanilir/tamamlanir."""
    if isinstance(path_or_text, (bytes, bytearray)):
        from .song_ini import decode_text
        text = decode_text(bytes(path_or_text))
    elif isinstance(path_or_text, str) and _looks_like_text(path_or_text):
        text = path_or_text
    else:
        text = read_text_file(path_or_text)
    info = info if info is not None else SongInfo()

    sections = _split_sections(text)
    meta: dict[str, str] = {}
    for name, lines in sections:
        if name.lower() == "song":
            for line in lines:
                if "=" in line:
                    k, v = line.split("=", 1)
                    meta[k.strip().lower()] = _unquote(v)
    try:
        resolution = int(float(meta.get("resolution", "192")))
    except ValueError:
        resolution = 192
    if resolution <= 0:
        resolution = 192
    try:
        offset = float(meta.get("offset", "0") or 0)
    except ValueError:
        offset = 0.0
    _apply_chart_meta(meta, info)

    # --- SyncTrack
    tempos: list[TempoChange] = []
    timesigs: list[TimeSignature] = []
    for name, lines in sections:
        if name.lower() != "synctrack":
            continue
        for line in lines:
            p = _parse_tick_line(line)
            if p is None:
                continue
            tick, kind, rest = p
            vals = _ints(rest)
            if kind == "B" and vals and vals[0] > 0:
                tempos.append(TempoChange(tick, vals[0] / 1000.0))
            elif kind == "TS" and vals and vals[0] > 0:
                exp = vals[1] if len(vals) > 1 else 2
                timesigs.append(TimeSignature(tick, vals[0], 2 ** max(0, min(exp, 6))))
    tempo_map = TempoMap(resolution, tempos, timesigs)

    # --- Events
    chart_sections: list[Section] = []
    end_tick: int | None = None
    for name, lines in sections:
        if name.lower() != "events":
            continue
        for line in lines:
            p = _parse_tick_line(line)
            if p is None or p[1] != "E":
                continue
            tick, _, rest = p
            txt = _unquote(rest)
            sec = section_name(txt)
            if sec is not None:
                chart_sections.append(Section(tick, tempo_map.tick_to_time(tick), sec))
            elif is_end_event(txt) and end_tick is None:
                end_tick = tick
    chart_sections.sort(key=lambda s: s.tick)

    chart = Chart(resolution=resolution, tempo_map=tempo_map, info=info,
                  offset=offset + info.delay_ms / 1000.0, sections=chart_sections)

    # --- 5-fret gitar
    threshold = chart_hopo_threshold(resolution, info.hopo_frequency)
    raw: dict[str, dict] = {}
    for name, lines in sections:
        diff = TRACK_SECTIONS.get(name.lower())
        if diff is None:
            continue
        d = raw.setdefault(diff, {"gems": [], "inv": set(), "tap": set(), "sp": [],
                                  "solo_on": [], "solo_off": []})
        for line in lines:
            p = _parse_tick_line(line)
            if p is None:
                continue
            tick, kind, rest = p
            if kind == "N":
                vals = _ints(rest)
                if not vals:
                    continue
                code = vals[0]
                length = vals[1] if len(vals) > 1 else 0
                if 0 <= code <= 4:
                    d["gems"].append((tick, code, length))
                elif code == 7:
                    d["gems"].append((tick, OPEN_FRET, length))
                elif code == 5:
                    d["inv"].add(tick)
                elif code == 6:
                    d["tap"].add(tick)
            elif kind == "S":
                vals = _ints(rest)
                if len(vals) >= 1 and vals[0] == 2:
                    d["sp"].append((tick, vals[1] if len(vals) > 1 else 0))
            elif kind == "E":
                txt = _unquote(rest).strip().lower()
                if txt == "solo":
                    d["solo_on"].append(tick)
                elif txt == "soloend":
                    d["solo_off"].append(tick)

    for diff, d in raw.items():
        last_tick = max((g[0] for g in d["gems"]), default=0)
        solos = [(s, e if e is not None else max(s, last_tick))
                 for s, e in _pair_solos(d["solo_on"], d["solo_off"])]
        track = build_track(diff, d["gems"], tempo_map, threshold,
                            invert_ticks=d["inv"], tap_ticks=d["tap"], sp_ranges=d["sp"],
                            solo_ranges=solos, solo_end_inclusive=True)
        if track.notes:
            chart.tracks[diff] = track

    chart.end_time = compute_end_time(chart, end_tick)
    return chart


def _pair_solos(ons: list[int], offs: list[int]) -> list[tuple[int, int | None]]:
    """'solo' / 'soloend' olaylarini sirayla eslestir; kapanmayan solo -> bitis None (son notaya kadar)."""
    ons = sorted(set(ons))
    offs = sorted(offs)
    out: list[tuple[int, int | None]] = []
    j = 0
    for s in ons:
        if out and (out[-1][1] is None or out[-1][1] > s):
            continue  # onceki solo henuz kapanmadi (ic ice 'solo' olaylari)
        while j < len(offs) and offs[j] < s:
            j += 1
        if j < len(offs):
            out.append((s, offs[j]))
            j += 1
        else:
            out.append((s, None))
    return out
