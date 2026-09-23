"""Analizden oynanabilir .chart uretimi: tempo haritasi, Expert notalari (niceleme, perde konturundan perde
secimi, akorlar, sustain'ler, bolum tekrarlarinda desen yeniden kullanimi), Hard/Medium/Easy indirgemeleri,
Star Power cumleleri, [Events] ve kalite denetimi (parser + bot full combo).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..timing import TempoChange, TempoMap
from .analysis import Analysis, analyze

RES = 192
HOPO_TICKS = (65 * RES) // 192
DIFFS = ("expert", "hard", "medium", "easy")
SECTION_NAMES = {"expert": "ExpertSingle", "hard": "HardSingle", "medium": "MediumSingle", "easy": "EasySingle"}
FIRST_NOTE_MIN = 1.5        # s: ilk notadan once sayim suresi
MAX_NPS = 9.0               # Expert yogunluk tavani (1 s pencerede)
EXPERT_MIN_STRENGTH = 0.12  # zayif onset'ler Expert'e girmez


@dataclass
class GNote:
    tick: int
    time: float
    strength: float
    pitch: float = 60.0
    clarity: float = 0.0
    width: float = 0.0
    low: float = 0.0
    sustain_s: float = 0.0
    triplet: bool = False
    fret: int = 0                 # kok perde (DP)
    mask: int = 1
    length: int = 0
    section: int = -1

    @property
    def frets(self) -> list[int]:
        return [f for f in range(5) if self.mask >> f & 1]


@dataclass
class ChartResult:
    text: str
    analysis: Analysis
    tracks: dict = field(default_factory=dict)        # zorluk -> list[GNote]
    sp: dict = field(default_factory=dict)            # zorluk -> [(tick, length)]
    tempo_events: list = field(default_factory=list)
    timesigs: list = field(default_factory=list)
    sections: list = field(default_factory=list)      # (tick, ad)
    end_tick: int = 0
    difficulty: int = 0
    preview_ms: int = 0
    validation: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- tempo haritasi

def build_tempo_map(an: Analysis) -> tuple[list[tuple[int, int]], list[tuple[int, int]], np.ndarray, int]:
    """Vurus izgarasi -> (B olaylari [(tick, bpm*1000)], TS olaylari [(tick, pay)], grid zamanlari, ilk-vurus
    grid kaydirmasi). Grid indeksi k <-> tick k*RES; grid[0] = 0 s (ses baslangici)."""
    beats = np.asarray(an.beats, dtype=np.float64)
    if beats.size < 4:
        ibi = 60.0 / max(an.tempo, 60.0)
        beats = np.arange(0.5, an.duration + ibi, ibi)
    ibi0 = float(np.median(np.diff(beats[:9])))
    ibin = float(np.median(np.diff(beats[-9:])))
    pre: list[float] = []
    t = beats[0] - ibi0
    while t > 0.3 * ibi0:
        pre.append(t)
        t -= ibi0
    pre.reverse()
    post: list[float] = []
    t = beats[-1] + ibin
    while t < an.duration + 6 * ibin:
        post.append(t)
        t += ibin
    grid = np.concatenate([[0.0], pre, beats, post])
    shift = 1 + len(pre)                       # an.beats[i] -> grid indeksi i + shift
    events: list[tuple[int, int]] = []
    T = 0.0
    prev = None
    for k in range(grid.size - 1):
        dt = grid[k + 1] - T
        milli = int(round(60.0 / max(dt, 1e-3) * 1000.0))       # bpm * 1000 (hata yayilimli)
        milli = max(20000, min(900000, milli))
        T += 60.0 / (milli / 1000.0)
        if milli != prev:
            events.append((k * RES, milli))
            prev = milli
    p = (an.downbeat + shift) % 4
    ts = [(0, 4)]
    if p:
        ts.append((p * RES, 4))
    return events, ts, grid, shift


def tempo_map_from(events, ts) -> TempoMap:
    from ..timing import TimeSignature
    return TempoMap(RES, [TempoChange(t, m / 1000.0) for t, m in events], [TimeSignature(t, n, 4) for t, n in ts])


# --------------------------------------------------------------------------- niceleme

STRAIGHT = np.array([0.0, 0.25, 0.5, 0.75, 1.0])
TRIPLET = np.array([0.0, 1 / 3, 2 / 3, 1.0])


def quantize(an: Analysis, tm: TempoMap, first_tick_min: int, last_tick: int) -> list[GNote]:
    by_beat: dict[int, list[tuple[float, int]]] = {}
    ons = an.onsets
    for i, o in enumerate(ons):
        tf = tm.time_to_tick(o.time) / RES
        b = int(math.floor(tf))
        by_beat.setdefault(b, []).append((tf - b, i))
    notes: dict[int, GNote] = {}
    for b in sorted(by_beat):
        items = by_beat[b]
        fr = np.array([f for f, _ in items])
        e_str = np.abs(fr[:, None] - STRAIGHT[None, :]).min(axis=1)
        e_tri = np.abs(fr[:, None] - TRIPLET[None, :]).min(axis=1)
        trip_like = int(((np.abs(fr - 1 / 3) < 0.05) | (np.abs(fr - 2 / 3) < 0.05)).sum())
        use_tri = trip_like >= 1 and e_tri.sum() < 0.7 * e_str.sum() and len(items) >= 2
        for f, i in items:
            if use_tri:
                q = int(round(f * 3))
                tick = b * RES + q * (RES // 3)
            else:
                q = int(round(f * 4))
                tick = b * RES + q * (RES // 4)
            if tick < first_tick_min or tick > last_tick:
                continue
            o = ons[i]
            n = notes.get(tick)
            if n is None or o.strength > n.strength:
                notes[tick] = GNote(tick=tick, time=tm.tick_to_time(tick), strength=o.strength, pitch=o.pitch,
                                    clarity=o.clarity, width=o.width, low=o.low, sustain_s=o.sustain,
                                    triplet=use_tri and q not in (0, 3))
    return [notes[t] for t in sorted(notes)]


def cap_density(notes: list[GNote], max_nps: float, window: float = 1.0) -> list[GNote]:
    """Herhangi bir `window` saniyelik pencerede en fazla max_nps*window nota: en zayiflari at."""
    notes = list(notes)
    limit = int(max_nps * window)
    changed = True
    while changed:
        changed = False
        j = 0
        for i in range(len(notes)):
            while notes[i].time - notes[j].time >= window:
                j += 1
            if i - j + 1 > limit:
                seg = range(j, i + 1)
                k = min(seg, key=lambda x: (notes[x].strength, -x))
                del notes[k]
                changed = True
                break
    return notes


# --------------------------------------------------------------------------- perde secimi (Viterbi)

def _fold(d: float) -> float:
    """Oktav hatalarina dayanikli perde farki: [-6.5, 6.5] araligina katla."""
    d = (d + 6.5) % 12.0 - 6.5 if abs(d) > 6.5 else d
    return d


def target_step(d: float) -> int:
    a = abs(d)
    if a < 0.5:
        return 0
    s = 1 if d > 0 else -1
    if a <= 2.5:
        return s
    if a <= 5.5:
        return 2 * s
    return 3 * s


def assign_frets(values: list[float], nfrets: int, clarity: list[float] | None = None,
                 fold: bool = False, window: int = 12, edge_cost: float = 0.15) -> list[int]:
    """Bir deger dizisini (perde / ust zorluk perdesi) insan charter'i gibi perdelere esle.

    Kurallar (maliyetler): ayni deger -> ayni perde; yukari -> yukari perde; buyuklukle orantili adim;
    yerel araliktaki konum (yuksek notalar yuksek perdelerde); gereksiz buyuk sicrama ve kenar cezasi.
    """
    N = len(values)
    if N == 0:
        return []
    F = nfrets
    v = np.asarray(values, dtype=np.float64)
    c = np.ones(N) if clarity is None else np.clip(np.asarray(clarity, dtype=np.float64), 0.15, 1.0)
    # yerel konum hedefi (sirali siralama yuzdeligi)
    pos = np.zeros(N)
    for i in range(N):
        lo, hi = max(0, i - window), min(N, i + window + 1)
        seg = v[lo:hi]
        rank = (seg < v[i]).sum() + 0.5 * (seg == v[i]).sum()
        pos[i] = (rank / seg.size) * (F - 1)
    frets = np.arange(F)
    INF = 1e18
    cost = np.full((N, F), INF)
    back = np.zeros((N, F), dtype=np.int64)
    edge = np.array([edge_cost if (f == F - 1 and F == 5) else 0.0 for f in frets])
    cost[0] = 0.35 * np.abs(frets - pos[0]) + edge
    for i in range(1, N):
        d = v[i] - v[i - 1]
        if fold:
            d = _fold(d)
        tgt = target_step(d)
        w = 0.5 + 0.5 * min(c[i], c[i - 1])
        # (onceki a, simdiki b) gecis maliyeti
        a = frets[:, None]
        b = frets[None, :]
        dd = b - a
        tc = np.zeros((F, F))
        if tgt == 0:
            tc += 3.0 * w * (dd != 0) + 0.8 * w * np.abs(dd)
        else:
            wrong = np.sign(dd) == -np.sign(tgt)
            flat = dd == 0
            tc += w * (4.0 * wrong + 1.4 * flat + 0.6 * np.abs(dd - tgt) * (~wrong))
        tc += 0.35 * np.maximum(0, np.abs(dd) - 2) ** 2
        tot = cost[i - 1][:, None] + tc
        back[i] = np.argmin(tot, axis=0)
        cost[i] = tot[back[i], frets] + 0.35 * np.abs(frets - pos[i]) + edge
    out = [int(np.argmin(cost[-1]))]
    for i in range(N - 1, 0, -1):
        out.append(int(back[i][out[-1]]))
    return out[::-1]


# --------------------------------------------------------------------------- Expert

def metric_weight(tick: int, bar_ticks: set[int], p_ts: int) -> float:
    if tick in bar_ticks:
        return 1.0
    r = tick % RES
    if r == 0:
        return 0.8
    if r == RES // 2:
        return 0.5
    return 0.2


def chord_shape(root: int, size: int, variant: int = 0) -> int:
    if size <= 1:
        return 1 << root
    if size == 2:
        if variant and root <= 2:
            return (1 << root) | (1 << (root + 2))
        if root >= 4:
            return (1 << 3) | (1 << 4)
        return (1 << root) | (1 << (root + 1))
    r = min(root, 2)
    return (1 << r) | (1 << (r + 1)) | (1 << (r + 2))


def make_expert(an: Analysis, tm: TempoMap, grid_shift: int, bar_ticks: set[int],
                section_ticks: list[tuple[int, int, int]], last_tick: int) -> list[GNote]:
    first = int(math.ceil(tm.time_to_tick(FIRST_NOTE_MIN)))
    notes = quantize(an, tm, first, last_tick)
    notes = [n for n in notes if n.strength >= EXPERT_MIN_STRENGTH]
    notes = cap_density(notes, MAX_NPS)
    if not notes:
        return notes
    # bolum atamasi
    for n in notes:
        for si, (st, en, _cl) in enumerate(section_ticks):
            if st <= n.tick < en:
                n.section = si
                break
    # perdeler
    frets = assign_frets([n.pitch for n in notes], 5, [n.clarity for n in notes])
    for n, f in zip(notes, frets):
        n.fret = f
        n.mask = 1 << f
    # akorlar: genis bantli guclu vurgular (olcu basi / vurus), hizli pasajlarda degil
    acc = np.array([n.strength * (0.4 + n.width) + 0.25 * min(n.low, 1.5) for n in notes])
    if acc.size >= 8:
        thr2 = np.percentile(acc, 76)
        thr3 = np.percentile(acc, 97)
        variant = 0
        for i, n in enumerate(notes):
            mw = metric_weight(n.tick, bar_ticks, 0)
            if mw < 0.8 or acc[i] < thr2:
                continue
            gap_prev = n.tick - notes[i - 1].tick if i > 0 else 10 ** 6
            gap_next = notes[i + 1].tick - n.tick if i + 1 < len(notes) else 10 ** 6
            if min(gap_prev, gap_next) < RES // 2:
                continue
            size = 3 if (acc[i] >= thr3 and mw >= 1.0) else 2
            n.mask = chord_shape(n.fret, size, variant)
            variant ^= 1 if n.fret <= 2 else 0
    # bolum tekrarlari: ayni kumedeki bolumlerde ayni goreli konumdaki notalar ayni perdeleri alir
    reuse_patterns(notes, section_ticks)
    # sustain'ler
    set_sustains(notes, tm, an)
    return notes


def reuse_patterns(notes: list[GNote], section_ticks: list[tuple[int, int, int]]) -> None:
    by_sec: dict[int, list[GNote]] = {}
    for n in notes:
        by_sec.setdefault(n.section, []).append(n)
    ref_of_cluster: dict[int, int] = {}
    for si, (st, en, cl) in enumerate(section_ticks):
        sec_notes = by_sec.get(si, [])
        if cl < 0 or len(sec_notes) < 4:
            continue
        if cl not in ref_of_cluster:
            ref_of_cluster[cl] = si
            continue
        ref = ref_of_cluster[cl]
        rst = section_ticks[ref][0]
        ref_map = {n.tick - rst: n for n in by_sec.get(ref, [])}
        matched = [(n, ref_map[n.tick - st]) for n in sec_notes if (n.tick - st) in ref_map]
        if len(matched) < 0.6 * len(sec_notes) or len(matched) < 4:
            continue
        # ayni ritim yetmez: eslesen notalarin perde konturu da ayni olmali (ayni riff / melodi)
        same = 0
        for (a, ra), (b, rb) in zip(matched, matched[1:]):
            da = _fold(b.pitch - a.pitch)
            dr = _fold(rb.pitch - ra.pitch)
            same += abs(da - dr) <= 1.0
        if same < 0.75 * (len(matched) - 1):
            continue
        for n, r in matched:
            n.mask = r.mask
            n.fret = r.fret


def set_sustains(notes: list[GNote], tm: TempoMap, an: Analysis) -> None:
    for i, n in enumerate(notes):
        n.length = 0
        if n.sustain_s <= 0:
            continue
        end_tick = tm.time_to_tick(n.time + n.sustain_s)
        sus = end_tick - n.tick
        # olcum sonumlenen enerjiyi %30 esikle izler (muhafazakar): ~3/4 vurus = "~1 vurus surer"
        if sus < RES * 0.75:
            continue
        nxt = notes[i + 1].tick if i + 1 < len(notes) else 10 ** 9
        length = min(max(sus, RES), nxt - n.tick - RES // 8)
        length = int(length // (RES // 8)) * (RES // 8)
        if length >= RES // 2:
            n.length = int(length)


# --------------------------------------------------------------------------- indirgemeler

def _priority(n: GNote, bar_ticks: set[int]) -> float:
    return (0.55 * n.strength + 0.45 * metric_weight(n.tick, bar_ticks, 0) + 0.2 * (n.length > 0)
            + 0.08 * (bin(n.mask).count("1") > 1))


def _select(notes: list[GNote], bar_ticks: set[int], min_gap: int, target: float, lo: float,
            strong_gap: int | None = None, strong_prio: float = 9.0) -> list[GNote]:
    """Oncelige gore acgozlu secim; min_gap kuralina uy, hedef orana indir."""
    if not notes:
        return []
    pr = [_priority(n, bar_ticks) for n in notes]
    order = sorted(range(len(notes)), key=lambda i: (-pr[i], notes[i].tick))
    chosen_ticks: list[int] = []
    import bisect
    chosen: list[int] = []
    limit = max(1, int(round(target * len(notes))))
    for i in order:
        t = notes[i].tick
        gap = min_gap
        if strong_gap is not None and pr[i] >= strong_prio:
            gap = strong_gap
        k = bisect.bisect_left(chosen_ticks, t)
        ok = True
        if k > 0 and t - chosen_ticks[k - 1] < gap:
            ok = False
        if k < len(chosen_ticks) and chosen_ticks[k] - t < gap:
            ok = False
        if not ok:
            continue
        chosen_ticks.insert(k, t)
        chosen.append(i)
        if len(chosen) >= limit:
            break
    chosen.sort()
    return [notes[i] for i in chosen]


def _copy(n: GNote) -> GNote:
    return GNote(**{k: getattr(n, k) for k in n.__dataclass_fields__})


def _trim_sustains(notes: list[GNote], extend_to: float | None = None) -> None:
    for i, n in enumerate(notes):
        nxt = notes[i + 1].tick if i + 1 < len(notes) else 10 ** 9
        if n.length > 0:
            n.length = min(n.length, nxt - n.tick - RES // 8)
            n.length = int(n.length // (RES // 8)) * (RES // 8)
            if n.length < RES // 2:
                n.length = 0


def reduce_hard(expert: list[GNote], bar_ticks: set[int]) -> list[GNote]:
    sel = [_copy(n) for n in _select(expert, bar_ticks, RES // 2, 0.72, 0.65,
                                     strong_gap=RES // 4, strong_prio=1.2)]
    for n in sel:
        fr = n.frets
        if len(fr) >= 3:
            n.mask = (1 << fr[0]) | (1 << fr[-1]) if fr[-1] - fr[0] <= 2 else (1 << fr[0]) | (1 << fr[1])
    _trim_sustains(sel)
    return sel


def _remap(notes: list[GNote], nfrets: int, chords: bool) -> None:
    vals = [2.0 * (n.frets[0] if n.frets else 0) + (0.5 if len(n.frets) > 1 else 0.0) for n in notes]
    fr = assign_frets(vals, nfrets, fold=False, window=10, edge_cost=0.0)
    for n, f, orig in zip(notes, fr, [len(x.frets) for x in notes]):
        n.fret = f
        if chords and orig >= 2:
            n.mask = (1 << f) | (1 << (f + 1)) if f + 1 < nfrets else (1 << (f - 1)) | (1 << f)
        else:
            n.mask = 1 << f


def reduce_medium(expert: list[GNote], bar_ticks: set[int]) -> list[GNote]:
    sel = [_copy(n) for n in _select(expert, bar_ticks, RES // 2, 0.52, 0.45)]
    _remap(sel, 4, chords=True)
    _trim_sustains(sel)
    return sel


def reduce_easy(expert: list[GNote], bar_ticks: set[int]) -> list[GNote]:
    sel = [_copy(n) for n in _select(expert, bar_ticks, RES, 0.32, 0.25, strong_gap=RES // 2, strong_prio=1.25)]
    _remap(sel, 3, chords=False)
    # uzun sustain'ler korunur; bir sonraki notaya kadar uzatilabilir (enerji suruyorsa)
    _trim_sustains(sel)
    return sel


# --------------------------------------------------------------------------- Star Power

def place_star_power(notes: list[GNote], bar_ticks_sorted: list[int]) -> list[tuple[int, int]]:
    if len(notes) < 12:
        return []
    first, last = notes[0].tick, notes[-1].tick
    n_meas = max(1, sum(1 for b in bar_ticks_sorted if first <= b <= last))
    count = int(np.clip(round(n_meas / 10.0), 6, 8))
    count = min(count, len(notes) // 6)
    if count <= 0:
        return []
    seg = (last - first) / count
    phrases: list[tuple[int, int]] = []
    last_end = -10 ** 9
    for j in range(count):
        anchor = first + seg * (j + 0.45)
        best = None
        for i, n in enumerate(notes):
            if n.tick < first + seg * j or n.tick > first + seg * (j + 1):
                continue
            if n.tick < last_end + 4 * RES:
                continue
            for L in range(4, 9):
                if i + L > len(notes):
                    break
                grp = notes[i:i + L]
                span = grp[-1].tick - grp[0].tick
                if span > 8 * RES:
                    break
                sc = -abs(n.tick - anchor) / (4 * RES) + 1.2 * (grp[-1].length > 0) - 0.1 * abs(L - 6)
                if i + L < len(notes) and notes[i + L].tick - grp[-1].tick < RES // 2:
                    sc -= 0.6            # cumle bir kosunun ortasinda bitmesin
                if best is None or sc > best[0]:
                    best = (sc, i, L)
        if best is None:
            continue
        _, i, L = best
        start = notes[i].tick
        end = notes[i + L - 1].tick
        phrases.append((start, end - start + 1))
        last_end = end
    return phrases


# --------------------------------------------------------------------------- yazici

def _q(s: str) -> str:
    return str(s).replace('"', "'").replace("\n", " ").replace("\r", " ").strip()


def write_chart(res: ChartResult, *, title: str, artist: str, album: str = "", year: str = "",
                genre: str = "", music_stream: str = "song.ogg") -> str:
    L = ["[Song]", "{", f'  Name = "{_q(title)}"', f'  Artist = "{_q(artist)}"', '  Charter = "RIFF Auto"']
    if album:
        L.append(f'  Album = "{_q(album)}"')
    if year:
        L.append(f'  Year = ", {_q(year)}"')
    L += ["  Offset = 0", f"  Resolution = {RES}", "  Player2 = bass", f"  Difficulty = {res.difficulty}",
          f"  PreviewStart = {res.preview_ms / 1000.0:.3f}", "  PreviewEnd = 0"]
    if genre:
        L.append(f'  Genre = "{_q(genre)}"')
    L += ['  MediaType = "cd"', f'  MusicStream = "{_q(music_stream)}"', "}", "[SyncTrack]", "{"]
    sync = [(t, 0, f"TS {n}") for t, n in res.timesigs] + [(t, 1, f"B {m}") for t, m in res.tempo_events]
    for t, _, s in sorted(sync):
        L.append(f"  {t} = {s}")
    L += ["}", "[Events]", "{"]
    for t, name in res.sections:
        L.append(f'  {t} = E "section {_q(name)}"')
    L.append(f'  {res.end_tick} = E "end"')
    L.append("}")
    for d in DIFFS:
        notes = res.tracks.get(d) or []
        if not notes:
            continue
        L += [f"[{SECTION_NAMES[d]}]", "{"]
        rows = []
        for n in notes:
            for f in n.frets:
                rows.append((n.tick, 0, f"N {f} {n.length}"))
        for t, ln in res.sp.get(d, []):
            rows.append((t, 1, f"S 2 {ln}"))
        for t, _, s in sorted(rows):
            L.append(f"  {t} = {s}")
        L.append("}")
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------- dogrulama

def validate(text: str) -> dict:
    """Her zorluk icin: parse + bot ile full combo ve 0 overstrum. {zorluk: (ok, mesaj)}"""
    from ..chart import parse_chart
    from ..config import EngineConfig
    from ..engine import GuitarEngine, autoplay_inputs
    chart = parse_chart(text)
    out = {}
    for d in DIFFS:
        tr = chart.tracks.get(d)
        if tr is None or not tr.notes:
            out[d] = (False, "missing track")
            continue
        ticks = [n.tick for n in tr.notes]
        if len(set(ticks)) != len(ticks) or ticks != sorted(ticks):
            out[d] = (False, "duplicate / unsorted ticks")
            continue
        if tr.notes[0].time < FIRST_NOTE_MIN - 1e-6:
            out[d] = (False, f"first note at {tr.notes[0].time:.2f}s")
            continue
        cfg = EngineConfig()
        eng = GuitarEngine(chart, tr, cfg)
        for ev in autoplay_inputs(tr, cfg):
            eng.push(ev)
        eng.update(chart.end_time + 5.0)
        ok = eng.notes_hit == eng.total_notes and eng.overstrums == 0 and eng.notes_missed == 0
        out[d] = (ok, f"hit {eng.notes_hit}/{eng.total_notes} over {eng.overstrums}")
    return out


# --------------------------------------------------------------------------- zorluk / onizleme

def estimate_difficulty(src) -> int:
    """0..6 (song.ini diff_guitar). src: ChartResult, .chart metni veya Expert GNote listesi."""
    notes = None
    if isinstance(src, ChartResult):
        notes = src.tracks.get("expert") or []
        times = [n.time for n in notes]
        chords = sum(1 for n in notes if len(n.frets) > 1)
        fast = sum(1 for a, b in zip(notes, notes[1:]) if b.tick - a.tick <= HOPO_TICKS)
    else:
        from ..chart import parse_chart
        chart = parse_chart(src) if isinstance(src, str) else src
        tr = chart.tracks.get("expert") or next(iter(chart.tracks.values()), None)
        if tr is None or not tr.notes:
            return 0
        times = [n.time for n in tr.notes]
        chords = sum(1 for n in tr.notes if n.is_chord)
        fast = sum(1 for a, b in zip(tr.notes, tr.notes[1:]) if b.tick - a.tick <= HOPO_TICKS)
    if len(times) < 2:
        return 0
    dur = max(times[-1] - times[0], 1.0)
    nps = len(times) / dur
    score = nps + 3.0 * fast / len(times) + 1.0 * chords / len(times)
    for lvl, thr in enumerate((1.6, 2.6, 3.6, 4.6, 5.6, 6.6)):
        if score < thr:
            return lvl
    return 6


def pick_preview_start(an: Analysis) -> int:
    """Ilk koro (yoksa en yogun bolum) baslangici, ms."""
    beats = an.beats
    if not an.sections or beats.size == 0:
        return int(max(0.0, min(an.duration * 0.35, an.duration - 30.0)) * 1000)
    cands = [s for s in an.sections if s.name.startswith("Chorus")]
    if not cands:
        pool = [s for s in an.sections if beats[min(s.beat, beats.size - 1)] > 0.12 * an.duration] or an.sections
        cands = [max(pool, key=lambda s: s.energy)]
    t = float(beats[min(cands[0].beat, beats.size - 1)])
    t = max(0.0, min(t - 0.2, max(0.0, an.duration - 30.0)))
    return int(round(t * 1000))


# --------------------------------------------------------------------------- ana giris

def _progress(cb, frac, text):
    if cb is not None:
        try:
            cb(float(frac), text)
        except Exception:
            pass


def generate(samples: np.ndarray, sr: int, *, title: str = "Unknown", artist: str = "Unknown",
             album: str = "", year: str = "", genre: str = "", music_stream: str = "song.ogg",
             progress=None, analysis: Analysis | None = None, check: bool = True) -> ChartResult:
    def sub(lo, hi):
        return lambda f, t: _progress(progress, lo + (hi - lo) * f, t)

    an = analysis if analysis is not None else analyze(samples, sr, progress=sub(0.0, 0.75))
    _progress(progress, 0.76, "Building tempo map")
    events, ts, grid, shift = build_tempo_map(an)
    tm = tempo_map_from(events, ts)
    p = ts[1][0] // RES if len(ts) > 1 else 0
    end_time = an.duration
    last_tick = int(tm.time_to_tick(max(FIRST_NOTE_MIN + 1.0, end_time - 0.25)))
    bar_ticks_sorted = list(range(p * RES, last_tick + 8 * RES, 4 * RES))
    bar_ticks = set(bar_ticks_sorted)
    # bolumler (grid tick'leri)
    secs = []
    for s in an.sections:
        tick = (s.beat + shift) * RES
        if tick <= last_tick:
            secs.append((tick, s.name, s.cluster))
    secs.sort()
    section_ticks = []
    for i, (t, _nm, cl) in enumerate(secs):
        nxt = secs[i + 1][0] if i + 1 < len(secs) else 10 ** 9
        section_ticks.append((t, nxt, cl))

    _progress(progress, 0.8, "Charting Expert")
    expert = make_expert(an, tm, shift, bar_ticks, section_ticks, last_tick)
    if len(expert) < 8:
        raise ValueError("could not find enough notes in this audio")
    _progress(progress, 0.86, "Charting Hard / Medium / Easy")
    tracks = {"expert": expert, "hard": reduce_hard(expert, bar_ticks),
              "medium": reduce_medium(expert, bar_ticks), "easy": reduce_easy(expert, bar_ticks)}
    sp = {d: place_star_power(tracks[d], bar_ticks_sorted) for d in DIFFS}
    last_note_end = max(n.tick + n.length for n in expert)
    end_tick = max(int(tm.time_to_tick(end_time)), last_note_end + RES)
    res = ChartResult(text="", analysis=an, tracks=tracks, sp=sp, tempo_events=events, timesigs=ts,
                      sections=[(t, nm) for t, nm, _ in secs], end_tick=end_tick)
    res.difficulty = estimate_difficulty(res)
    res.preview_ms = pick_preview_start(an)
    res.text = write_chart(res, title=title, artist=artist, album=album, year=year, genre=genre,
                           music_stream=music_stream)
    if check:
        _progress(progress, 0.9, "Checking playability")
        res.validation = validate(res.text)
        bad = [d for d, (ok, _m) in res.validation.items() if not ok]
        if bad:
            # guvenli geri donus: sorunlu zorluklarda sustain ve akorlari sadelestir
            for d in bad:
                for n in tracks[d]:
                    n.length = 0
                    n.mask = 1 << (n.frets[0] if n.frets else 0)
            res.text = write_chart(res, title=title, artist=artist, album=album, year=year, genre=genre,
                                   music_stream=music_stream)
            res.validation = validate(res.text)
            bad = [d for d, (ok, _m) in res.validation.items() if not ok]
            if bad:
                raise RuntimeError("generated chart failed the playability check: " +
                                   ", ".join(f"{d}: {res.validation[d][1]}" for d in bad))
    _progress(progress, 1.0, "Done")
    return res


def generate_chart(samples: np.ndarray, sr: int, *, title: str = "Unknown", artist: str = "Unknown",
                   progress=None, **kw) -> str:
    return generate(samples, sr, title=title, artist=artist, progress=progress, **kw).text
