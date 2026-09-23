"""Ham gem'lerden Note/Track uretimi: akor gruplama, dogal HOPO, force/tap, SP ve solo eslemesi.

.chart ve .mid parser'lari ortak kullanir (ek-01 §1.8, §2.1, §2.2).

Ham gem: (tick, fret, length)  fret 0..4 = yesil..turuncu, OPEN_FRET (-1) = acik nota.
Aralik: (start_tick, end_tick) yari-acik [start, end); sifir uzunluklu aralik start tick'ini kapsar.
"""
from __future__ import annotations

import bisect
from typing import Iterable, Sequence

from ..models import Chart, Note, NoteType, SPPhrase, Solo, Track, popcount
from ..timing import TempoMap

OPEN_FRET = -1


# --- esikler -----------------------------------------------------------------

def chart_hopo_threshold(resolution: int, hopo_frequency: int | None = None) -> int:
    """.chart: floor(65/192 * res) tick (192 -> 65, 480 -> 162); song.ini hopo_frequency ezer."""
    if hopo_frequency:
        return int(hopo_frequency)
    return (65 * resolution) // 192


def midi_hopo_threshold(resolution: int, hopo_frequency: int | None = None,
                        eighthnote_hopo: bool = False) -> int:
    """.mid: floor(res/3)+1 tick (480 -> 161); eighthnote_hopo -> res/2+1; hopo_frequency ezer."""
    if hopo_frequency:
        return int(hopo_frequency)
    if eighthnote_hopo:
        return resolution // 2 + 1
    return resolution // 3 + 1


def midi_sustain_cutoff(resolution: int, threshold: int | None = None) -> int:
    """.mid: bu tick sayisindan KISA sustain'ler 0 olur. Varsayilan floor(res/3)+1."""
    if threshold is not None:
        return int(threshold)
    return resolution // 3 + 1


# --- gruplama ------------------------------------------------------------------

def group_gems(gems: Iterable[tuple[int, int, int]], sustain_cutoff: int = 0) -> list[tuple[int, int, int]]:
    """Ayni tick'teki gem'leri (tick, mask, length) olarak birlestir; tick'e gore sirali.

    - mask: bit0 yesil .. bit4 turuncu; acik nota = 0.
    - Acik gem + perdeli gem ayni tick'te: acik gem atilir (uzunlugu da).
    - length: gruptaki en uzun gem; sustain_cutoff'tan kisa gem uzunluklari 0 sayilir.
    """
    groups: dict[int, list[int]] = {}   # tick -> [mask, has_open, fret_len, open_len]
    for tick, fret, length in gems:
        length = max(0, int(length))
        if sustain_cutoff and length < sustain_cutoff:
            length = 0
        g = groups.setdefault(int(tick), [0, 0, 0, 0])
        if fret == OPEN_FRET:
            g[1] = 1
            g[3] = max(g[3], length)
        elif 0 <= fret <= 4:
            g[0] |= 1 << fret
            g[2] = max(g[2], length)
    out: list[tuple[int, int, int]] = []
    for tick in sorted(groups):
        mask, has_open, flen, olen = groups[tick]
        if mask:
            out.append((tick, mask, flen))
        elif has_open:
            out.append((tick, 0, olen))
    return out


# --- HOPO ------------------------------------------------------------------------

def natural_hopo(prev: Note | None, note: Note, threshold: int) -> bool:
    """Dogal HOPO kurali."""
    if prev is None:
        return False
    if popcount(note.mask) >= 2:              # akor asla dogal HOPO degil
        return False
    if note.tick - prev.tick > threshold:
        return False
    if note.mask == prev.mask:                # ayni perde tekrari
        return False
    if popcount(prev.mask) >= 2 and (prev.mask & note.mask):  # akordaki perdeye inis
        return False
    return True


def _in_ranges(tick: int, ranges: Sequence[tuple[int, int]]) -> bool:
    for s, e in ranges:
        if s <= tick < max(e, s + 1):
            return True
    return False


def resolve_note_types(notes: list[Note], threshold_ticks: int, *,
                       invert_ticks: Iterable[int] = (), tap_ticks: Iterable[int] = (),
                       force_hopo_ranges: Sequence[tuple[int, int]] = (),
                       force_strum_ranges: Sequence[tuple[int, int]] = (),
                       tap_ranges: Sequence[tuple[int, int]] = ()) -> None:
    """Note.type'lari yerinde belirle.

    Oncelik: tap (tick veya aralik) > .mid force strum > .mid force HOPO > .chart ters cevirme
    (dogal durumu tersine cevirir) > dogal kural.
    """
    inv = set(invert_ticks)
    taps = set(tap_ticks)
    prev: Note | None = None
    for n in notes:
        hopo = natural_hopo(prev, n, threshold_ticks)
        if n.tick in inv:
            hopo = not hopo
        if force_hopo_ranges and _in_ranges(n.tick, force_hopo_ranges):
            hopo = True
        if force_strum_ranges and _in_ranges(n.tick, force_strum_ranges):
            hopo = False
        if n.tick in taps or (tap_ranges and _in_ranges(n.tick, tap_ranges)):
            n.type = NoteType.TAP
        else:
            n.type = NoteType.HOPO if hopo else NoteType.STRUM
        prev = n


# --- Track uretimi -----------------------------------------------------------------

def _notes_in(ticks: list[int], start: int, end: int, inclusive_end: bool = False) -> tuple[int, int]:
    """[start, end) (veya [start, end]) araligindaki notalarin indeks araligi [lo, hi)."""
    if end <= start and not inclusive_end:
        end = start + 1
    lo = bisect.bisect_left(ticks, start)
    hi = bisect.bisect_right(ticks, end) if inclusive_end else bisect.bisect_left(ticks, end)
    return lo, hi


def build_track(difficulty: str, gems: Iterable[tuple[int, int, int]], tempo_map: TempoMap,
                hopo_threshold: int, *, sustain_cutoff: int = 0,
                invert_ticks: Iterable[int] = (), tap_ticks: Iterable[int] = (),
                force_hopo_ranges: Sequence[tuple[int, int]] = (),
                force_strum_ranges: Sequence[tuple[int, int]] = (),
                tap_ranges: Sequence[tuple[int, int]] = (),
                sp_ranges: Sequence[tuple[int, int]] = (),
                solo_ranges: Sequence[tuple[int, int]] = (),
                solo_end_inclusive: bool = False) -> Track:
    """Ham gem'lerden tam Track uret.

    sp_ranges: (tick, length) - notalar [tick, tick+length) icinde ise cumleye aittir (Moonscraper).
    solo_ranges: (start_tick, end_tick); solo_end_inclusive=True ise end tick'teki nota da dahildir
    (.chart 'soloend'), aksi halde yari-acik (.mid nota 103).
    """
    notes: list[Note] = []
    for tick, mask, length in group_gems(gems, sustain_cutoff):
        t = tempo_map.tick_to_time(tick)
        end = tempo_map.tick_to_time(tick + length) if length > 0 else t
        notes.append(Note(tick=tick, time=t, mask=mask, length_ticks=length, end_time=end))
    resolve_note_types(notes, hopo_threshold, invert_ticks=invert_ticks, tap_ticks=tap_ticks,
                       force_hopo_ranges=force_hopo_ranges, force_strum_ranges=force_strum_ranges,
                       tap_ranges=tap_ranges)
    for i, n in enumerate(notes):
        n.index = i
    ticks = [n.tick for n in notes]

    track = Track(difficulty=difficulty, notes=notes)
    for tick, length in sorted(sp_ranges):
        length = max(0, int(length))
        lo, hi = _notes_in(ticks, tick, tick + length)
        members = [i for i in range(lo, hi) if notes[i].sp_phrase == -1]
        if not members:
            continue
        idx = len(track.sp_phrases)
        for i in members:
            notes[i].sp_phrase = idx
        notes[members[-1]].sp_phrase_end = True
        track.sp_phrases.append(SPPhrase(tick=tick, length_ticks=length,
                                         start_time=tempo_map.tick_to_time(tick),
                                         end_time=tempo_map.tick_to_time(tick + length),
                                         first_note=members[0], last_note=members[-1]))

    for start, end in sorted(solo_ranges):
        lo, hi = _notes_in(ticks, start, end, solo_end_inclusive)
        if hi <= lo:
            continue
        track.solos.append(Solo(start_time=tempo_map.tick_to_time(start),
                                end_time=tempo_map.tick_to_time(max(end, start)),
                                first_note=lo, last_note=hi - 1))
    return track


def section_name(text: str) -> str | None:
    """'section Intro' / '[section Intro]' / 'prc_verse_1' -> bolum adi, degilse None."""
    t = text.strip()
    if t.startswith("[") and t.endswith("]"):
        t = t[1:-1].strip()
    low = t.lower()
    if low.startswith("section "):
        return t[8:].strip() or None
    if low.startswith("section_"):
        return t[8:].replace("_", " ").strip() or None
    if low.startswith("prc_"):
        return t[4:].replace("_", " ").strip() or None
    return None


def is_end_event(text: str) -> bool:
    t = text.strip()
    if t.startswith("[") and t.endswith("]"):
        t = t[1:-1].strip()
    return t.lower() == "end"


def compute_end_time(chart: Chart, end_event_tick: int | None) -> float:
    """max(son nota/sustain bitisi, [end] olayi zamani)."""
    end = 0.0
    for tr in chart.tracks.values():
        for n in tr.notes:  # sustain'ler sirali bitmeyebilir: hepsini tara
            if n.end_time > end:
                end = n.end_time
    if end_event_tick is not None:
        end = max(end, chart.tempo_map.tick_to_time(end_event_tick))
    return end
