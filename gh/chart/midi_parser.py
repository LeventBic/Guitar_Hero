""".mid (Rock Band / Clone Hero) okuyucu, bagimliliksiz SMF parser ile (ek-01 §2.2, D06).

parse_midi(path_or_bytes, info=None) -> Chart
Okunan: tempo/TS (tum track'ler), EVENTS track'i (bolumler, [end]), PART GUITAR (yoksa T1 GEMS).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from ..models import Chart, Section, SongInfo
from ..timing import TempoChange, TempoMap, TimeSignature
from .hopo import (OPEN_FRET, build_track, compute_end_time, is_end_event, midi_hopo_threshold,
                   midi_sustain_cutoff, section_name)
from .song_ini import decode_text


class MidiError(ValueError):
    pass


# --- Standard MIDI File okuyucu ---------------------------------------------------

@dataclass
class MidiTrack:
    name: str = ""
    # (tick, kanal, nota, hiz) ; hiz 0 = note-off
    notes: list[tuple[int, int, int, int]] = field(default_factory=list)
    # (tick, meta tipi, veri)
    metas: list[tuple[int, int, bytes]] = field(default_factory=list)
    # (tick, veri)  (F0 sonrasi, uzunluk haric)
    sysex: list[tuple[int, bytes]] = field(default_factory=list)


@dataclass
class MidiFile:
    format: int
    division: int
    tracks: list[MidiTrack]


def _read_vlq(data: bytes, pos: int, end: int) -> tuple[int, int]:
    value = 0
    for _ in range(4):
        if pos >= end:
            raise MidiError("VLQ kesik")
        b = data[pos]
        pos += 1
        value = (value << 7) | (b & 0x7F)
        if not b & 0x80:
            return value, pos
    raise MidiError("VLQ cok uzun")


_DATA_LEN = {0x80: 2, 0x90: 2, 0xA0: 2, 0xB0: 2, 0xC0: 1, 0xD0: 1, 0xE0: 2}


def _parse_track(data: bytes, pos: int, end: int) -> MidiTrack:
    tr = MidiTrack()
    tick = 0
    running = 0
    try:
        while pos < end:
            delta, pos = _read_vlq(data, pos, end)
            tick += delta
            if pos >= end:
                break
            status = data[pos]
            if status == 0xFF:  # meta
                if pos + 1 >= end:
                    break
                mtype = data[pos + 1]
                length, pos = _read_vlq(data, pos + 2, end)
                payload = data[pos:pos + length]
                pos += length
                if mtype == 0x2F:  # end of track
                    break
                tr.metas.append((tick, mtype, payload))
                if mtype == 0x03 and not tr.name:
                    tr.name = decode_text(payload).strip("\x00").strip()
                continue
            if status in (0xF0, 0xF7):  # sysex
                length, pos = _read_vlq(data, pos + 1, end)
                if status == 0xF0:
                    tr.sysex.append((tick, data[pos:pos + length]))
                pos += length
                running = 0
                continue
            if status & 0x80:
                pos += 1
                if status >= 0xF0:  # sistem mesaji (SMF'de beklenmez)
                    pos += {0xF2: 2, 0xF3: 1}.get(status, 0)
                    continue
                running = status
            elif not running:
                raise MidiError("running status yok")
            kind = running & 0xF0
            n = _DATA_LEN[kind]
            if pos + n > end:
                break
            d1 = data[pos]
            d2 = data[pos + 1] if n == 2 else 0
            pos += n
            if kind == 0x90:
                tr.notes.append((tick, running & 0x0F, d1, d2))
            elif kind == 0x80:
                tr.notes.append((tick, running & 0x0F, d1, 0))
    except MidiError:
        pass  # bozuk track sonu: okunabilen kismi kullan
    return tr


def read_midi(data: bytes) -> MidiFile:
    if len(data) < 14 or data[:4] != b"MThd":
        raise MidiError("MThd baslik yok")
    hlen = int.from_bytes(data[4:8], "big")
    fmt = int.from_bytes(data[8:10], "big")
    ntrks = int.from_bytes(data[10:12], "big")
    division = int.from_bytes(data[12:14], "big")
    if division & 0x8000:
        raise MidiError("SMPTE zaman bolumu desteklenmiyor")
    if division == 0:
        raise MidiError("division 0")
    pos = 8 + hlen
    tracks: list[MidiTrack] = []
    while pos + 8 <= len(data) and len(tracks) < max(ntrks, 1) * 4:
        cid = data[pos:pos + 4]
        clen = int.from_bytes(data[pos + 4:pos + 8], "big")
        body = pos + 8
        end = min(body + clen, len(data))
        if cid == b"MTrk":
            tracks.append(_parse_track(data, body, end))
        pos = body + clen
    return MidiFile(fmt, division, tracks)


# --- Gitar yorumlama ----------------------------------------------------------------

DIFF_BASE = {"easy": 60, "medium": 72, "hard": 84, "expert": 96}
SOLO_NOTE = 103
TAP_NOTE = 104
SP_NOTE = 116
GUITAR_TRACK_NAMES = ("PART GUITAR", "T1 GEMS")
_TEXT_METAS = (0x01, 0x05, 0x06, 0x07)
_PS_SYSEX_DIFF = {0: "easy", 1: "medium", 2: "hard", 3: "expert"}


def _note_ranges(track: MidiTrack) -> dict[int, list[tuple[int, int]]]:
    """nota numarasi -> [(on_tick, off_tick)] (kanal yok sayilir; kapanmayan nota 0 uzunluk)."""
    active: dict[int, int] = {}
    out: dict[int, list[tuple[int, int]]] = {}
    # Ayni tick'teki olaylar nota bazinda toplanir: once off (onceki notayi kapatir), sonra on.
    # Onceden acik olmayan bir nota ayni tick'te hem on hem off aldiysa 0 uzunluklu notadir.
    evs = sorted(track.notes, key=lambda e: e[0])
    i = 0
    while i < len(evs):
        tick = evs[i][0]
        per_note: dict[int, list[int]] = {}   # nota -> [on sayisi, off sayisi]
        while i < len(evs) and evs[i][0] == tick:
            _, _ch, note, vel = evs[i]
            c = per_note.setdefault(note, [0, 0])
            c[0 if vel > 0 else 1] += 1
            i += 1
        for note, (ons, offs) in per_note.items():
            if offs and note in active:
                out.setdefault(note, []).append((active.pop(note), tick))
                offs -= 1
            if ons:
                if note in active:  # off'suz yeniden tetikleme
                    out.setdefault(note, []).append((active.pop(note), tick))
                if offs:
                    out.setdefault(note, []).append((tick, tick))
                else:
                    active[note] = tick
    for note, start in active.items():
        out.setdefault(note, []).append((start, start))
    for v in out.values():
        v.sort()
    return out


def _texts(track: MidiTrack) -> list[tuple[int, str]]:
    return [(t, decode_text(d).strip("\x00").strip()) for t, m, d in track.metas if m in _TEXT_METAS]


def _sysex_ranges(track: MidiTrack) -> dict[tuple[str, int], list[tuple[int, int]]]:
    """Phase Shift SysEx: 50 53 00 00 <zorluk|FF> 01 <tip: 01 acik, 04 tap> <01 ac|00 kapat> F7.

    (zorluk, tip) -> [(start, end)].
    """
    active: dict[tuple[str, int], int] = {}
    out: dict[tuple[str, int], list[tuple[int, int]]] = {}
    for tick, d in track.sysex:
        if len(d) < 8 or d[0] != 0x50 or d[1] != 0x53 or d[2] != 0 or d[3] != 0 or d[5] != 0x01:
            continue
        diffs = list(_PS_SYSEX_DIFF.values()) if d[4] == 0xFF else (
            [_PS_SYSEX_DIFF[d[4]]] if d[4] in _PS_SYSEX_DIFF else [])
        for diff in diffs:
            key = (diff, d[6])
            if d[7]:
                active.setdefault(key, tick)
            elif key in active:
                out.setdefault(key, []).append((active.pop(key), tick))
    for key, start in active.items():
        out.setdefault(key, []).append((start, start))
    return out


def parse_midi(path_or_bytes: str | os.PathLike | bytes, info: SongInfo | None = None) -> Chart:
    """notes.mid -> Chart (yalniz 5-fret lead gitar)."""
    if isinstance(path_or_bytes, (bytes, bytearray)):
        data = bytes(path_or_bytes)
    else:
        with open(path_or_bytes, "rb") as f:
            data = f.read()
    info = info if info is not None else SongInfo()
    mid = read_midi(data)
    res = mid.division

    tempos: list[TempoChange] = []
    timesigs: list[TimeSignature] = []
    for tr in mid.tracks:
        for tick, mtype, d in tr.metas:
            if mtype == 0x51 and len(d) >= 3:
                mpq = int.from_bytes(d[:3], "big")
                if mpq > 0:
                    tempos.append(TempoChange(tick, 60_000_000.0 / mpq))
            elif mtype == 0x58 and len(d) >= 2 and d[0] > 0:
                timesigs.append(TimeSignature(tick, d[0], 2 ** min(d[1], 6)))
    tempo_map = TempoMap(res, tempos, timesigs)

    # --- EVENTS
    sections: list[Section] = []
    end_tick: int | None = None
    for tr in mid.tracks:
        if tr.name.strip().upper() != "EVENTS":
            continue
        for tick, txt in _texts(tr):
            sec = section_name(txt)
            if sec is not None:
                sections.append(Section(tick, tempo_map.tick_to_time(tick), sec))
            elif is_end_event(txt) and end_tick is None:
                end_tick = tick
    sections.sort(key=lambda s: s.tick)

    chart = Chart(resolution=res, tempo_map=tempo_map, info=info,
                  offset=info.delay_ms / 1000.0, sections=sections)

    # --- gitar track'i
    guitar: MidiTrack | None = None
    for wanted in GUITAR_TRACK_NAMES:
        guitar = next((t for t in mid.tracks if t.name.strip().upper() == wanted), None)
        if guitar is not None:
            break
    if guitar is None and mid.format == 0 and len(mid.tracks) == 1:
        guitar = mid.tracks[0]

    if guitar is not None:
        ranges = _note_ranges(guitar)
        enhanced_opens = any(txt.strip("[] ").upper() == "ENHANCED_OPENS" for _, txt in _texts(guitar))
        sysex = _sysex_ranges(guitar)
        sp_note = info.multiplier_note if info.multiplier_note in (103, 116) else SP_NOTE
        sp_ranges = [(s, e - s) for s, e in ranges.get(sp_note, [])]
        solo_ranges = [] if sp_note == SOLO_NOTE else list(ranges.get(SOLO_NOTE, []))
        tap_ranges_all = list(ranges.get(TAP_NOTE, []))
        threshold = midi_hopo_threshold(res, info.hopo_frequency, info.eighthnote_hopo)
        cutoff = midi_sustain_cutoff(res, info.sustain_cutoff_threshold)

        for diff, base in DIFF_BASE.items():
            gems: list[tuple[int, int, int]] = []
            for fret in range(5):
                for s, e in ranges.get(base + fret, []):
                    gems.append((s, fret, e - s))
            if enhanced_opens:
                for s, e in ranges.get(base - 1, []):
                    gems.append((s, OPEN_FRET, e - s))
            # PS SysEx acik nota: aralik icindeki yesil gem'ler acik olur
            open_sx = sysex.get((diff, 0x01), [])
            if open_sx:
                gems = [(t, OPEN_FRET if f == 0 and any(s <= t < max(e, s + 1) for s, e in open_sx) else f, ln)
                        for t, f, ln in gems]
            if not gems:
                continue
            track = build_track(diff, gems, tempo_map, threshold, sustain_cutoff=cutoff,
                                force_hopo_ranges=ranges.get(base + 5, []),
                                force_strum_ranges=ranges.get(base + 6, []),
                                tap_ranges=tap_ranges_all + sysex.get((diff, 0x04), []),
                                sp_ranges=sp_ranges, solo_ranges=solo_ranges)
            if track.notes:
                chart.tracks[diff] = track

    chart.end_time = compute_end_time(chart, end_tick)
    return chart
