"""Chart building for the RIFF demo songs: tempo map, a small pattern DSL, difficulty reductions,
Star Power placement and a .chart writer/reader.

Pattern DSL (one string per bar, tokens separated by spaces):
    FRETS[:DUR][MODS]
    FRETS  digits 0-4 (several = chord, e.g. "02"), "o" = open note, "-" = rest
    DUR    length in 16th steps (default 2 = an 8th). A token may run past the bar line; the
           following bar string(s) must then be "~" (continuation).
    MODS   "~" sustain (length = DUR minus a small gap), "!" = N 5 (flip strum<->HOPO), "t" = tap (N 6)
"""
from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field

RES = 192
STEP = RES // 4                      # 16th note
HOPO_THRESHOLD = (65 * RES) // 192   # 65 ticks at 192
OPEN_BIT = 1 << 5                    # internal: open note


def popcount(m: int) -> int:
    return bin(m).count("1")


# --- tempo map -----------------------------------------------------------------------

class TempoMap:
    """tick -> seconds for a list of (tick, bpm) changes (own implementation)."""

    def __init__(self, tempos: list[tuple[int, float]], res: int = RES):
        self.res = res
        self.ticks: list[int] = []
        self.bpms: list[float] = []
        self.times: list[float] = []
        t = 0.0
        for i, (tick, bpm) in enumerate(sorted(tempos)):
            if i:
                t += (tick - self.ticks[-1]) / res * 60.0 / self.bpms[-1]
            self.ticks.append(tick)
            self.bpms.append(bpm)
            self.times.append(t)

    def sec(self, tick: float) -> float:
        i = max(bisect.bisect_right(self.ticks, tick) - 1, 0)
        return self.times[i] + (tick - self.ticks[i]) / self.res * 60.0 / self.bpms[i]

    def bpm_at_tick(self, tick: float) -> float:
        return self.bpms[max(bisect.bisect_right(self.ticks, tick) - 1, 0)]


# --- song structure ------------------------------------------------------------------

@dataclass
class Section:
    name: str
    bars: int
    chords: list[int]                 # scale degree per bar (cycled)
    lead: list[str]                   # bar patterns (cycled); "" = empty bar, "~" = continuation
    drums: str = "rock"
    bass: str = "root8"
    rhythm: str = "chug8"
    pad: bool = False
    ts: tuple[int, int] = (4, 4)
    bpm: float | None = None          # tempo change at section start
    scale: list[int] | None = None    # override song scale (lead + harmony)
    lead_pos: list[int] | None = None # fixed lead base degree per bar (cycled); default = chord degree
    lead_oct: list[int] | int = 0
    solo: bool = False
    fill: bool = True
    final: bool = False
    show: bool = True                 # emit a 'section' event


@dataclass
class Song:
    title: str
    artist: str
    genre: str
    bpm: float
    tonic: int                        # midi of the lead tonic (e.g. 64 = E4)
    scale: list[int]
    sections: list[Section]
    seed: int
    drive: float = 5.0
    rhythm_drive: float = 4.0
    organ: bool = False
    diff_guitar: int = 3
    preview: str = "Chorus"
    art: str = "sun"
    loading_phrase: str = ""


@dataclass
class ChartNote:
    tick: int
    mask: int                         # bits 0..4 frets, OPEN_BIT = open
    length: int = 0
    force: bool = False
    tap: bool = False
    sec: int = 0                      # section index
    bar: int = 0                      # bar index within section

    @property
    def is_chord(self) -> bool:
        return popcount(self.mask & 0x1F) >= 2

    def frets(self) -> list[int]:
        return [f for f in range(5) if self.mask >> f & 1]


@dataclass
class Layout:
    """Tick layout of a song: section starts, bar starts, tempo & TS events."""
    sec_start: list[int] = field(default_factory=list)
    bar_starts: list[int] = field(default_factory=list)       # absolute ticks, all bars
    bar_info: list[tuple[int, int]] = field(default_factory=list)  # (section idx, bar in section)
    tempos: list[tuple[int, float]] = field(default_factory=list)
    timesigs: list[tuple[int, int, int]] = field(default_factory=list)  # tick, num, den
    end_tick: int = 0

    def steps_per_bar(self, sec: Section) -> int:
        return sec.ts[0] * 16 // sec.ts[1]

    def bar_at(self, tick: int) -> int:
        return max(bisect.bisect_right(self.bar_starts, tick) - 1, 0)


def build_layout(song: Song) -> Layout:
    lay = Layout()
    tick = 0
    bpm = song.bpm
    lay.tempos.append((0, bpm))
    cur_ts = None
    for si, sec in enumerate(song.sections):
        lay.sec_start.append(tick)
        if sec.bpm is not None and sec.bpm != bpm:
            bpm = sec.bpm
            lay.tempos.append((tick, bpm))
        if sec.ts != cur_ts:
            cur_ts = sec.ts
            lay.timesigs.append((tick, sec.ts[0], sec.ts[1]))
        bar_ticks = lay.steps_per_bar(sec) * STEP
        for b in range(sec.bars):
            lay.bar_starts.append(tick)
            lay.bar_info.append((si, b))
            tick += bar_ticks
    lay.end_tick = tick
    return lay


_TOKEN = re.compile(r"^([0-4]+|o|-)(?::(\d+))?([~!t]*)$")


def parse_lead(song: Song, lay: Layout) -> list[ChartNote]:
    """Expand the per-section bar patterns into Expert notes."""
    notes: list[ChartNote] = []
    for si, sec in enumerate(song.sections):
        spb = lay.steps_per_bar(sec)
        if not sec.lead:
            continue
        pos = 0  # steps from section start
        for b in range(sec.bars):
            pat = sec.lead[b % len(sec.lead)].strip()
            if pat == "~":
                continue
            if pos != b * spb:
                raise ValueError(f"{song.title}/{sec.name} bar {b}: pattern position {pos} != {b * spb}")
            if not pat:
                pos += spb
                continue
            for tok in pat.split():
                m = _TOKEN.match(tok)
                if not m:
                    raise ValueError(f"{song.title}/{sec.name} bar {b}: bad token {tok!r}")
                frets, dur, mods = m.group(1), int(m.group(2) or 2), m.group(3)
                if frets != "-":
                    mask = OPEN_BIT if frets == "o" else sum(1 << int(c) for c in set(frets))
                    length = 0
                    if "~" in mods:
                        length = dur * STEP - (STEP if dur >= 4 else STEP // 2)
                    notes.append(ChartNote(tick=lay.sec_start[si] + pos * STEP, mask=mask, length=length,
                                           force="!" in mods, tap="t" in mods, sec=si, bar=b))
                pos += dur
        if pos != sec.bars * spb:
            raise ValueError(f"{song.title}/{sec.name}: total {pos} steps != {sec.bars * spb}")
    trim_sustains(notes)
    return notes


# --- rules -------------------------------------------------------------------------------

def natural_hopo(prev: ChartNote | None, n: ChartNote) -> bool:
    if prev is None or n.is_chord:
        return False
    if n.tick - prev.tick > HOPO_THRESHOLD:
        return False
    if n.mask == prev.mask:
        return False
    if prev.is_chord and (prev.mask & n.mask):
        return False
    return True


def note_kinds(notes: list[ChartNote]) -> list[str]:
    """Effective type per note: 'strum' | 'hopo' | 'tap'."""
    out = []
    prev = None
    for n in notes:
        if n.tap:
            out.append("tap")
        else:
            h = natural_hopo(prev, n) ^ n.force
            out.append("hopo" if h else "strum")
        prev = n
    return out


def trim_sustains(notes: list[ChartNote], gap: int = RES // 8, min_len: int = 36) -> None:
    for i, n in enumerate(notes):
        if n.length <= 0 or i + 1 >= len(notes):
            continue
        max_len = notes[i + 1].tick - gap - n.tick
        if n.length > max_len:
            n.length = max_len if max_len >= min_len else 0


def design_warnings(notes: list[ChartNote]) -> list[str]:
    """Ambiguous-by-engine constructs we want to avoid in hand-written patterns."""
    w = []
    for a, b in zip(notes, notes[1:]):
        if b.tick <= a.tick:
            w.append(f"tick order {a.tick} {b.tick}")
        if a.length and a.tick + a.length > b.tick - RES // 8:
            w.append(f"sustain overlap at {a.tick}")
        if (not b.is_chord and a.is_chord and (a.mask & b.mask) and b.tick - a.tick <= HOPO_THRESHOLD):
            w.append(f"note-in-previous-chord within HOPO threshold at tick {b.tick}")
        if b.force and b.is_chord:
            w.append(f"forced chord at {b.tick}")
    return w


# --- difficulty reductions ------------------------------------------------------------

def _strength(n: ChartNote, lay: Layout) -> int:
    pos = n.tick - lay.bar_starts[lay.bar_at(n.tick)]
    if pos == 0:
        s = 6
    elif pos % RES == 0:
        s = 5
    elif pos % (RES // 2) == 0:
        s = 3
    elif pos % STEP == 0:
        s = 2
    else:
        s = 1
    if n.length >= RES // 2:
        s += 2
    if n.is_chord:
        s += 1
    return s


def _select(notes: list[ChartNote], lay: Layout, ratio: float, min_gap: int, beats_only: bool = False) -> list[ChartNote]:
    cands = []
    for i, n in enumerate(notes):
        pos = n.tick - lay.bar_starts[lay.bar_at(n.tick)]
        if beats_only and pos % RES != 0:
            continue
        prev_gap = n.tick - notes[i - 1].tick if i else 10 ** 6
        bonus = 1 if prev_gap >= RES else 0
        # deterministic tie-break that spreads picks: prefer notes whose index hash is small
        cands.append((-(_strength(n, lay) + bonus), (i * 7919) % 97, i))
    cands.sort()
    target = max(1, round(ratio * len(notes)))
    chosen_ticks: list[int] = []
    chosen: list[int] = []
    for _, _, i in cands:
        if len(chosen) >= target:
            break
        t = notes[i].tick
        k = bisect.bisect_left(chosen_ticks, t)
        if k > 0 and t - chosen_ticks[k - 1] < min_gap:
            continue
        if k < len(chosen_ticks) and chosen_ticks[k] - t < min_gap:
            continue
        chosen_ticks.insert(k, t)
        chosen.append(i)
    chosen.sort()
    return [ChartNote(**{**notes[i].__dict__}) for i in chosen]


def _two_fret(frets: list[int]) -> list[int]:
    lo = frets[0]
    rest = frets[1:]
    second = min(rest, key=lambda f: (abs(f - (lo + 2)), f))
    return [lo, second]


def _mask(frets) -> int:
    return sum(1 << f for f in set(frets))


def reduce_track(notes: list[ChartNote], lay: Layout, diff: str) -> list[ChartNote]:
    if diff == "hard":
        kinds = dict(zip((n.tick for n in notes), note_kinds(notes)))
        out = _select(notes, lay, 0.70, STEP)
        for n in out:
            f = n.frets()
            if len(f) > 2:
                n.mask = _mask(_two_fret(f))
            n.force = False
        # runs that were hammer-ons on Expert stay legato on Hard as (forced) 8th-note HOPOs
        prev = None
        for n in out:
            if (prev is not None and not n.tap and kinds.get(n.tick) == "hopo" and not n.is_chord
                    and n.mask != prev.mask and not (prev.is_chord and prev.mask & n.mask)
                    and n.tick - prev.tick <= RES // 2):
                n.force = not natural_hopo(prev, n)
            prev = n
    elif diff == "medium":
        out = _select(notes, lay, 0.50, RES // 2)
        by_bar: dict[int, list[ChartNote]] = {}
        for n in out:
            n.force = False
            n.tap = False
            f = n.frets()
            if len(f) > 2:
                n.mask = _mask(_two_fret(f))
            by_bar.setdefault(lay.bar_at(n.tick), []).append(n)
        for bar_notes in by_bar.values():
            used = set()
            for n in bar_notes:
                used.update(n.frets())
            shift = 1 if (4 in used and 0 not in used) else 0
            for n in bar_notes:
                if n.mask & OPEN_BIT:
                    continue
                f = sorted({min(3, x - shift) for x in n.frets()})
                n.mask = _mask(f)
    elif diff == "easy":
        out = _select(notes, lay, 0.30, RES, beats_only=True)
        by_bar = {}
        for n in out:
            n.force = False
            n.tap = False
            f = n.frets()
            n.mask = _mask([f[0]]) if f else 1  # open -> green, chord -> lowest fret
            by_bar.setdefault(lay.bar_at(n.tick), []).append(n)
        table = (0, 1, 1, 2, 2)
        for bar_notes in by_bar.values():
            fs = [n.frets()[0] for n in bar_notes]
            lo, hi = min(fs), max(fs)
            # keep the contour: shift the bar down only as far as needed to fit G/R/Y
            shift = max(0, hi - 2) if hi - lo <= 2 else None
            for n, f in zip(bar_notes, fs):
                g = f - shift if shift is not None else table[f]
                n.mask = 1 << g
    else:
        raise ValueError(diff)
    # sustains: keep only meaningful ones; re-trim for the new neighbours
    for n in out:
        if n.length and n.length < RES // 2 and diff in ("medium", "easy"):
            n.length = 0
    trim_sustains(out)
    return out


# --- Star Power ---------------------------------------------------------------------------

def place_star_power(notes: list[ChartNote], lay: Layout, count: int, avoid: list[tuple[int, int]] = ()) -> list[tuple[int, int]]:
    """Return (tick, length) phrases: `count` phrases spread over the song, each 4..8 notes,
    preferring to end on the longest sustain in its region."""
    if len(notes) < 8:
        return []
    first, last = notes[0].tick, notes[-1].tick
    span = last - first
    phrases: list[tuple[int, int]] = []
    last_used = -2
    for k in range(count):
        a = first + span * k // count
        b = first + span * (k + 1) // count
        idx = [i for i, n in enumerate(notes) if a <= n.tick < b and i >= 3 and i - 3 > last_used + 1]
        if not idx:
            continue
        sus = [i for i in idx if notes[i].length >= RES // 2]
        if sus:
            end = max(sus, key=lambda i: (notes[i].length, -i))
        else:
            end = idx[len(idx) // 2]
        # window size: notes within the previous 2 bars (by ticks), clamped to 4..8
        w = sum(1 for j in range(max(0, end - 8), end + 1) if notes[end].tick - notes[j].tick <= 2 * 4 * RES)
        w = max(4, min(8, w))
        start = end - w + 1
        if start <= last_used + 1:
            start = last_used + 2
            if end - start + 1 < 4:
                end = start + 3
        if end >= len(notes):
            continue
        s, e = notes[start], notes[end]
        length = e.tick + max(e.length, 1) - s.tick
        if end + 1 < len(notes):
            length = min(length, notes[end + 1].tick - s.tick)
        phrases.append((s.tick, length))
        last_used = end
    return phrases


# --- writer / reader ----------------------------------------------------------------------

DIFF_TRACKS = (("expert", "ExpertSingle"), ("hard", "HardSingle"), ("medium", "MediumSingle"), ("easy", "EasySingle"))


def write_chart(path: str, song: Song, lay: Layout, tracks: dict[str, list[ChartNote]],
                sp: dict[str, list[tuple[int, int]]], solos: dict[str, list[tuple[int, int]]],
                preview_ms: int) -> None:
    L = []
    L.append("[Song]\n{")
    L += [f'  Name = "{song.title}"', f'  Artist = "{song.artist}"', '  Charter = "RIFF"',
          '  Album = "RIFF Demo"', '  Year = "2026"', "  Offset = 0", f"  Resolution = {RES}",
          '  Player2 = bass', "  Difficulty = 0", "  PreviewStart = 0", "  PreviewEnd = 0",
          f'  Genre = "{song.genre}"', '  MediaType = "cd"', '  MusicStream = "song.ogg"', '  GuitarStream = "guitar.ogg"']
    L.append("}")
    L.append("[SyncTrack]\n{")
    ev = []
    for tick, num, den in lay.timesigs:
        exp = {1: 0, 2: 1, 4: 2, 8: 3, 16: 4, 32: 5}[den]
        ev.append((tick, 0, f"TS {num}" if exp == 2 else f"TS {num} {exp}"))
    for tick, bpm in lay.tempos:
        ev.append((tick, 1, f"B {int(round(bpm * 1000))}"))
    for tick, _, txt in sorted(ev):
        L.append(f"  {tick} = {txt}")
    L.append("}")
    L.append("[Events]\n{")
    for si, sec in enumerate(song.sections):
        if sec.show:
            L.append(f'  {lay.sec_start[si]} = E "section {sec.name}"')
    L.append(f'  {lay.end_tick} = E "end"')
    L.append("}")
    for diff, name in DIFF_TRACKS:
        L.append(f"[{name}]\n{{")
        ev = []
        for n in tracks[diff]:
            if n.mask & OPEN_BIT:
                ev.append((n.tick, 0, 7, f"N 7 {n.length}"))
            for f in n.frets():
                ev.append((n.tick, 0, f, f"N {f} {n.length}"))
            if n.force:
                ev.append((n.tick, 0, 5, "N 5 0"))
            if n.tap:
                ev.append((n.tick, 0, 6, "N 6 0"))
        for tick, length in sp[diff]:
            ev.append((tick, 1, 2, f"S 2 {length}"))
        for s, e in solos.get(diff, []):
            ev.append((s, 2, 0, "E solo"))
            ev.append((e, 2, 1, "E soloend"))
        for tick, _, _, txt in sorted(ev):
            L.append(f"  {tick} = {txt}")
        L.append("}")
    with open(path, "w", encoding="utf-8", newline="\r\n") as fh:
        fh.write("\n".join(L) + "\n")


def read_chart(path: str) -> dict:
    """Minimal regex reader used for validation."""
    text = open(path, encoding="utf-8").read()
    out: dict = {"sections": {}}
    for m in re.finditer(r"\[(\w+)\]\s*\{(.*?)\}", text, re.S):
        out["sections"][m.group(1)] = [ln.strip() for ln in m.group(2).strip().splitlines() if ln.strip()]
    res = int(re.search(r"Resolution\s*=\s*(\d+)", text).group(1))
    tempos = []
    for ln in out["sections"]["SyncTrack"]:
        m = re.match(r"(\d+)\s*=\s*B\s+(\d+)", ln)
        if m:
            tempos.append((int(m.group(1)), int(m.group(2)) / 1000.0))
    out["res"] = res
    out["tempo"] = TempoMap(tempos, res)
    tracks = {}
    for diff, name in DIFF_TRACKS:
        gems: dict[int, dict] = {}
        sp = []
        for ln in out["sections"].get(name, []):
            m = re.match(r"(\d+)\s*=\s*N\s+(\d+)\s+(\d+)", ln)
            if m:
                t, f, l = map(int, m.groups())
                g = gems.setdefault(t, {"mask": 0, "len": 0, "force": False, "tap": False})
                if f <= 4:
                    g["mask"] |= 1 << f
                elif f == 7:
                    g["mask"] |= OPEN_BIT
                elif f == 5:
                    g["force"] = True
                elif f == 6:
                    g["tap"] = True
                if f in (0, 1, 2, 3, 4, 7):
                    g["len"] = max(g["len"], l)
                continue
            m = re.match(r"(\d+)\s*=\s*S\s+2\s+(\d+)", ln)
            if m:
                sp.append((int(m.group(1)), int(m.group(2))))
        notes = [ChartNote(tick=t, mask=g["mask"], length=g["len"], force=g["force"], tap=g["tap"])
                 for t, g in sorted(gems.items())]
        tracks[diff] = {"notes": notes, "sp": sp}
    out["tracks"] = tracks
    return out
