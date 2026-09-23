"""Generate the built-in RIFF demo songs into Songs/ (Clone Hero folder layout).

    python tools/make_demo_songs.py            # generate all 3 songs + validate
    python tools/make_demo_songs.py --no-validate
    python tools/make_demo_songs.py --out SomeDir --serial

Per song: notes.chart, song.ini, song.ogg (band without lead guitar), guitar.ogg (isolated lead that
plays exactly the Expert chart), album.png. Fully deterministic (seeded).
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import numpy as np
import soundfile as sf

import synth as S
from charting import (OPEN_BIT, RES, STEP, ChartNote, Layout, Section, Song, TempoMap, build_layout,
                      design_warnings, note_kinds, parse_lead, place_star_power, read_chart, reduce_track,
                      write_chart)
from demo_song_defs import SONGS

SR = 44100
TAIL = 3.0            # seconds of ring-out after the chart's end
SONG_PEAK_DB = -3.0
GUITAR_TO_SONG_RMS = 0.85
SP_COUNTS = {"expert": 7, "hard": 7, "medium": 6, "easy": 6}


# --- harmony helpers -------------------------------------------------------------------

def deg_to_midi(tonic: int, scale: list[int], deg: int) -> int:
    octv, idx = divmod(deg, len(scale))
    return tonic + 12 * octv + scale[idx]


def fold(d: int) -> int:
    return d - 7 if d >= 4 else d


def harm_scale(song: Song, sec: Section) -> list[int]:
    return sec.scale if (sec.scale and len(sec.scale) == 7) else song.scale


def chord_of(sec: Section, bar: int) -> int:
    return sec.chords[bar % len(sec.chords)]


def lead_pitches(song: Song, n: ChartNote) -> list[float]:
    sec = song.sections[n.sec]
    lscale = sec.scale or song.scale
    hscale = harm_scale(song, sec)
    d = chord_of(sec, n.bar)
    octs = sec.lead_oct if isinstance(sec.lead_oct, list) else [sec.lead_oct]
    tonic = song.tonic + 12 * octs[n.bar % len(octs)]
    if n.mask & OPEN_BIT:
        return [deg_to_midi(song.tonic - 24, hscale, fold(d))]
    base = sec.lead_pos[n.bar % len(sec.lead_pos)] if sec.lead_pos else fold(d)
    frets = n.frets()
    p = [deg_to_midi(tonic, lscale, base + f) for f in frets]
    if len(frets) == 1:
        return p
    if len(frets) == 2 and frets[1] - frets[0] >= 2:
        return p                                   # harmonized dyad
    r = p[0] - 12
    return [r, r + 7, r + 12]                      # power chord


# --- arrangement patterns ------------------------------------------------------------------

def drum_pattern(style: str, steps: int, b: int, nbars: int) -> list[tuple[int, str, float]]:
    ev: list[tuple[int, str, float]] = []
    eighths = range(0, steps, 2)
    if style == "count":
        return [(s, "stick", 0.9 if s == 0 else 0.7) for s in range(0, steps, 4)]
    if style == "end":
        return [(0, "kick", 1.0), (0, "crash", 1.0), (0, "snare", 0.6)]
    if style == "intro":
        ev += [(0, "kick", 1.0), (8, "kick", 0.8)]
        ev += [(s, "hat", 0.45 if s % 4 == 0 else 0.3) for s in eighths]
        if b >= nbars // 2:
            ev += [(4, "snare", 0.55), (12, "snare", 0.6)]
    elif style in ("rock", "rock_open"):
        ev += [(0, "kick", 1.0), (8, "kick", 0.9), (10, "kick", 0.75), (4, "snare", 0.9), (12, "snare", 0.95)]
        if style == "rock":
            ev += [(s, "hat", 0.55 if s % 4 == 0 else 0.38) for s in eighths]
        else:
            ev += [(s, "ohat" if s % 4 == 2 else "hat", 0.42 if s % 4 == 2 else 0.5) for s in eighths]
    elif style == "half":
        ev += [(0, "kick", 1.0), (10, "kick", 0.7), (8, "snare", 0.95)]
        ev += [(s, "ride", 0.35 if s % 4 == 0 else 0.25) for s in eighths]
    elif style == "drive":
        ev += [(0, "kick", 1.0), (6, "kick", 0.8), (8, "kick", 0.9), (14, "kick", 0.75),
               (4, "snare", 0.95), (12, "snare", 0.95)]
        ev += [(s, "hat", 0.6 if s % 4 == 0 else 0.45) for s in eighths]
    elif style == "build":
        v = 0.35 + 0.6 * (b + 1) / nbars
        ev += [(s, "kick", 0.9) for s in range(0, steps, 4)]
        sn = range(0, steps, 2) if b < nbars - 1 else range(0, steps, 1)
        ev += [(s, "snare", v * (0.8 + 0.2 * (s % 4 == 0))) for s in sn]
        ev += [(s, "hat", 0.35) for s in range(0, steps, 4)]
    elif style in ("metal", "metal_half", "metal_open"):
        kick = range(steps) if style != "metal_open" else range(0, steps, 2)
        ev += [(s, "kick", 0.85 if s % 4 == 0 else 0.65) for s in kick]
        snares = [8] if style == "metal_half" else [4, 12]
        ev += [(s, "snare", 1.0) for s in snares]
        if style == "metal_open":
            ev += [(s, "crash" if s == 8 else "ride", 0.5 if s % 4 == 0 else 0.32) for s in eighths]
        else:
            ev += [(s, "hat", 0.55) for s in range(0, steps, 4)]
    elif style == "odd":  # 7/8 = 2+2+3 eighths
        ev += [(0, "kick", 1.0), (1, "kick", 0.6), (8, "kick", 0.9), (9, "kick", 0.6), (10, "kick", 0.7),
               (4, "snare", 0.95), (12, "snare", 0.95)]
        ev += [(s, "hat", 0.55 if s in (0, 4, 8) else 0.38) for s in eighths]
    else:
        raise ValueError(style)
    return ev


def drum_fill(steps: int) -> list[tuple[int, str, float]]:
    return [(steps - 4, "tom_h", 0.8), (steps - 3, "tom_h", 0.7), (steps - 2, "tom_m", 0.85),
            (steps - 1, "tom_l", 0.95), (steps - 4, "kick", 0.8)]


def bass_pattern(style: str, steps: int, kicks: list[int]) -> list[tuple[int, int, int]]:
    """(step, dur_steps, semitone offset from root)."""
    if style == "none":
        return []
    if style == "hold":
        return [(0, steps, 0)]
    if style == "root4":
        return [(s, 4, 0) for s in range(0, steps, 4)]
    if style == "root8":
        return [(s, 2, 0) for s in range(0, steps, 2)]
    if style == "walk":
        return [(0, 4, 0), (4, 2, 0), (6, 2, 7), (8, 4, 12), (12, 4, 7)]
    if style == "follow":
        ks = sorted(set(kicks)) or [0]
        return [(s, (ks[i + 1] if i + 1 < len(ks) else steps) - s, 0) for i, s in enumerate(ks)]
    raise ValueError(style)


def rhythm_pattern(style: str, steps: int) -> list[tuple[int, int, bool]]:
    """(step, dur_steps, muted)."""
    if style == "none":
        return []
    if style == "ring":
        return [(0, steps, False)]
    if style == "strum":
        pat = [(0, 6, False), (6, 2, False), (8, 4, False), (12, 4, False)]
        return [p for p in pat if p[0] < steps]
    if style in ("strum8", "power8"):
        return [(s, 2, False) for s in range(0, steps, 2)]
    if style == "chug8":
        return [(s, 2, True) for s in range(0, steps, 2)]
    if style == "chug16":
        return [(s, 1, s % 4 != 0) for s in range(steps)]
    raise ValueError(style)


# --- rendering ------------------------------------------------------------------------------

def render_song(song: Song, lay: Layout, tm: TempoMap, expert: list[ChartNote], kinds: list[str]) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(song.seed)
    end_sec = tm.sec(lay.end_tick)
    n_total = int(math.ceil((end_sec + TAIL) * SR))

    def smp(tick: float) -> int:
        return int(round(tm.sec(tick) * SR))

    kit = S.make_drum_kit(SR, rng)
    drums = np.zeros((n_total, 2))
    bass = np.zeros(n_total)
    rhythm = np.zeros((n_total, 2))
    pad = np.zeros((n_total, 2))
    drum_pan = {"kick": 0.0, "snare": 0.05, "hat": 0.45, "ohat": 0.45, "crash": -0.4, "ride": 0.5,
                "tom_h": -0.3, "tom_m": 0.1, "tom_l": 0.4, "stick": 0.0}
    drum_gain = {"kick": 1.0, "snare": 0.75, "hat": 0.28, "ohat": 0.22, "crash": 0.32, "ride": 0.22,
                 "tom_h": 0.7, "tom_m": 0.7, "tom_l": 0.75, "stick": 0.5}

    for gb, bar_tick in enumerate(lay.bar_starts):
        si, b = lay.bar_info[gb]
        sec = song.sections[si]
        steps = lay.steps_per_bar(sec)
        bar_end_tick = bar_tick + steps * STEP
        d = chord_of(sec, b)
        hs = harm_scale(song, sec)
        root = deg_to_midi(song.tonic - 24, hs, fold(d))
        extra = TAIL if sec.final else 0.0

        # drums
        ev = drum_pattern(sec.drums, steps, b, sec.bars)
        if sec.fill and b == sec.bars - 1 and sec.drums not in ("count", "end"):
            ev = [e for e in ev if e[0] < steps - 4 or e[1] == "kick"] + drum_fill(steps)
        if b == 0 and sec.drums not in ("count", "end", "half"):
            ev.append((0, "crash", 0.9))
        kicks = [s for s, name, _ in ev if name == "kick"]
        for s, name, vel in ev:
            v = vel * rng.uniform(0.88, 1.0)
            S.add_mono(drums, kit[name], smp(bar_tick + s * STEP), drum_gain[name] * v, drum_pan[name])

        # bass
        for s, dur, off in bass_pattern(sec.bass, steps, kicks):
            t0 = tm.sec(bar_tick + s * STEP)
            t1 = tm.sec(min(bar_tick + (s + dur) * STEP, bar_end_tick)) + extra
            note = S.bass_note(root + off, t1 - t0 - 0.004, SR, grit=1.2 + 0.25 * song.rhythm_drive)
            i0 = int(round(t0 * SR))
            seg = note[: max(0, min(note.size, n_total - i0))]
            bass[i0:i0 + seg.size] += seg

        # rhythm guitars (double tracked, hard panned)
        chord = [root + 12, root + 19, root + 24]
        for s, dur, muted in rhythm_pattern(sec.rhythm, steps):
            t0 = tm.sec(bar_tick + s * STEP)
            t1 = tm.sec(min(bar_tick + (s + dur) * STEP, bar_end_tick)) + extra
            ln = t1 - t0 - 0.003
            for take, (pan, det, dly) in enumerate(((-0.8, -4.0, 0.0), (0.8, 5.0, 0.007))):
                hit = S.rhythm_guitar_hit(chord, ln, SR, drive=song.rhythm_drive, muted=muted, detune_cents=det)
                S.add_mono(rhythm, hit, int(round((t0 + dly) * SR)), 0.9 if s % 4 == 0 else 0.75, pan)

        # pad / organ
        if sec.pad:
            tri = [deg_to_midi(song.tonic - 12, hs, fold(d) + k) for k in (0, 2, 4)]
            t0 = tm.sec(bar_tick)
            t1 = tm.sec(bar_end_tick) + 0.06 + extra
            p = S.pad_chord(tri, t1 - t0, SR, organ=song.organ)
            S.add_mono(pad, p, int(round(t0 * SR)), 0.5, -0.35)
            S.add_mono(pad, p, int(round((t0 + 0.011) * SR)), 0.5, 0.35)

    # lead guitar: exactly the Expert chart
    lead = np.zeros(n_total)
    for i, n in enumerate(expert):
        t0 = tm.sec(n.tick)
        t_next = tm.sec(expert[i + 1].tick) if i + 1 < len(expert) else end_sec + TAIL - 0.05
        if n.length > 0:
            dur = tm.sec(n.tick + n.length) - t0 + 0.06
            if i + 1 == len(expert):
                dur += TAIL * 0.6
        else:
            dur = 0.9
        dur = min(dur, t_next - t0)
        note = S.lead_guitar_note(lead_pitches(song, n), dur, SR, kind=kinds[i], sustain=n.length > 0,
                                  drive=song.drive, rng=rng)
        if n.mask & OPEN_BIT:
            note *= 1.6  # the cab high-pass eats the low open-string fundamental: keep chugs audible
        i0 = int(round(t0 * SR))
        seg = note[: max(0, min(note.size, n_total - i0))]
        lead[i0:i0 + seg.size] += seg

    # --- bus processing -----------------------------------------------------------------
    bass = S.fft_filter(bass, lambda f: S.lp_curve(f, 1400, 2) * S.hp_curve(f, 35, 2), SR)
    bright = 5200.0 if song.organ else 3600.0
    rhythm = S.fft_filter(rhythm, lambda f: S.lp_curve(f, bright, 2) * S.hp_curve(f, 90, 2)
                          * S.peak_curve(f, 700, -2.5, 0.8), SR)
    pad = S.fft_filter(pad, lambda f: S.lp_curve(f, 2600, 2) * S.hp_curve(f, 140, 1), SR)
    lead = S.fft_filter(lead, lambda f: S.lp_curve(f, 5600, 2) * S.hp_curve(f, 110, 2)
                        * S.peak_curve(f, 1900, 3.0, 0.9), SR)

    ref = S.rms(drums)
    def lvl(x, rel):
        r = S.rms(x)
        return x * (ref * rel / r) if r > 0 else x

    rhythm_rel = 0.45 if song.organ else 0.6
    bass_st = np.repeat(lvl(bass, 0.8)[:, None], 2, axis=1)
    rhythm = lvl(rhythm, rhythm_rel)
    pad = lvl(pad, 0.35 if song.organ else 0.25)
    dry = drums + bass_st + rhythm + pad
    ir = S.make_reverb_ir(SR, rng, seconds=1.8 if song.organ else 1.4)
    wet = S.apply_reverb(drums * 0.12 + rhythm * 0.15 + pad * 0.5, ir)
    mix = dry + 0.35 * wet
    mix = S.peak_normalize(mix, SONG_PEAK_DB)

    lead_st = np.repeat(lead[:, None], 2, axis=1)
    small_ir = S.make_reverb_ir(SR, rng, seconds=0.9, predelay=0.02)
    lead_st = lead_st + 0.13 * S.apply_reverb(lead_st, small_ir)
    lead_st = lead_st * (GUITAR_TO_SONG_RMS * S.rms(mix) / max(S.rms(lead_st), 1e-9))
    ceiling = 10 ** (SONG_PEAK_DB / 20.0)
    if np.abs(lead_st).max() > ceiling:
        lead_st = S.soft_limit(lead_st, ceiling)
    return mix.astype(np.float32), lead_st.astype(np.float32)


# --- per song ------------------------------------------------------------------------------

def solo_ranges(song: Song, lay: Layout, notes: list[ChartNote]) -> list[tuple[int, int]]:
    out = []
    for si, sec in enumerate(song.sections):
        if not sec.solo:
            continue
        a = lay.sec_start[si]
        b = lay.sec_start[si + 1] if si + 1 < len(song.sections) else lay.end_tick
        inside = [n.tick for n in notes if a <= n.tick < b]
        if inside:
            out.append((a, inside[-1]))
    return out


def build_charts(song: Song):
    lay = build_layout(song)
    tm = TempoMap(lay.tempos)
    expert = parse_lead(song, lay)
    warns = design_warnings(expert)
    tracks = {"expert": expert}
    for diff in ("hard", "medium", "easy"):
        tracks[diff] = reduce_track(expert, lay, diff)
    sp = {d: place_star_power(tracks[d], lay, SP_COUNTS[d]) for d in tracks}
    solos = {d: solo_ranges(song, lay, tracks[d]) for d in tracks}
    return lay, tm, tracks, sp, solos, warns


def write_ogg(path: str, data: np.ndarray, block: int = 8192) -> None:
    """OGG Vorbis in blocks: one huge sf.write() overflows libvorbis' stack on Windows."""
    with sf.SoundFile(path, "w", samplerate=SR, channels=data.shape[1], format="OGG", subtype="VORBIS") as f:
        for i in range(0, data.shape[0], block):
            f.write(data[i:i + block])


def folder_name(song: Song) -> str:
    return f"{song.artist} - {song.title}"


def write_ini(path: str, song: Song, length_ms: int, preview_ms: int) -> None:
    lines = ["[song]", f"name = {song.title}", f"artist = {song.artist}", "album = RIFF Demo",
             f"genre = {song.genre}", "year = 2026", "charter = RIFF", f"song_length = {length_ms}",
             f"preview_start_time = {preview_ms}", f"diff_guitar = {song.diff_guitar}", "icon = ",
             "delay = 0", f"loading_phrase = {song.loading_phrase}", f"album_track = {SONGS.index(song) + 1}"]
    with open(path, "w", encoding="utf-8", newline="\r\n") as fh:
        fh.write("\n".join(lines) + "\n")


def generate_song(idx: int, out_root: str) -> dict:
    from album_art import draw_album

    song = SONGS[idx]
    t_start = time.perf_counter()
    lay, tm, tracks, sp, solos, warns = build_charts(song)
    kinds = note_kinds(tracks["expert"])
    folder = os.path.join(out_root, folder_name(song))
    os.makedirs(folder, exist_ok=True)

    mix, lead = render_song(song, lay, tm, tracks["expert"], kinds)
    assert mix.shape == lead.shape
    write_ogg(os.path.join(folder, "song.ogg"), mix)
    write_ogg(os.path.join(folder, "guitar.ogg"), lead)

    length_ms = int(round(mix.shape[0] / SR * 1000))
    preview_tick = next((lay.sec_start[i] for i, s in enumerate(song.sections) if s.name == song.preview), 0)
    preview_ms = int(round(tm.sec(preview_tick) * 1000))
    write_chart(os.path.join(folder, "notes.chart"), song, lay, tracks, sp, solos, preview_ms)
    write_ini(os.path.join(folder, "song.ini"), song, length_ms, preview_ms)
    draw_album(os.path.join(folder, "album.png"), song.title, song.artist, song.art, song.seed)
    return {
        "folder": folder, "title": song.title, "bpm": [b for _, b in lay.tempos], "length_ms": length_ms,
        "notes": {d: len(v) for d, v in tracks.items()}, "sp": {d: len(v) for d, v in sp.items()},
        "hopo": kinds.count("hopo"), "tap": kinds.count("tap"),
        "open": sum(1 for n in tracks["expert"] if n.mask & OPEN_BIT),
        "forced": sum(1 for n in tracks["expert"] if n.force), "warnings": warns,
        "song_peak_db": float(20 * np.log10(np.abs(mix).max())), "guitar_peak_db": float(20 * np.log10(np.abs(lead).max())),
        "song_rms_db": float(20 * np.log10(S.rms(mix))), "guitar_rms_db": float(20 * np.log10(S.rms(lead))),
        "seconds": time.perf_counter() - t_start,
    }


# --- validation --------------------------------------------------------------------------------

def _onset_errors(audio: np.ndarray, times: list[float]) -> list[float]:
    """Detected onset - chart time (ms) per note: smoothed energy envelope (3 ms window), find the
    release dip around the expected time, then the first point after it reaching 10% (-10 dB) of the
    new note's peak energy (low open notes have a spiky square-wave envelope, so a higher threshold
    lands on a later wave edge). Half the window length is subtracted as detector latency."""
    x = (audio.mean(axis=1) if audio.ndim == 2 else audio).astype(np.float64)
    win = int(0.003 * SR)
    c = np.concatenate([[0.0], np.cumsum(x * x)])
    errs = []
    for t in times:
        i0 = int(round(t * SR))
        lo, hi = max(i0 - int(0.03 * SR), win), min(i0 + int(0.04 * SR), x.size - 1)
        idx = np.arange(lo, hi)
        env = (c[idx] - c[idx - win]) / win          # energy of the 3 ms ending at idx
        post = env[idx >= i0]
        peak = post.max()
        seg = (idx >= i0 - int(0.015 * SR)) & (idx <= i0 + int(0.005 * SR))
        dip = int(np.argmin(np.where(seg, env, np.inf)))
        above = np.nonzero(env[dip:] >= 0.1 * peak)[0]
        k = idx[dip + above[0]] if above.size else idx[dip]
        errs.append((k - win / 2 - i0) / SR * 1000.0)
    return errs


def validate_song(folder: str) -> list[str]:
    problems: list[str] = []
    ch = read_chart(os.path.join(folder, "notes.chart"))
    tm = ch["tempo"]
    for diff, tr in ch["tracks"].items():
        notes, sp = tr["notes"], tr["sp"]
        if not notes:
            problems.append(f"{diff}: no notes")
            continue
        if not 5 <= len(sp) <= 8:
            problems.append(f"{diff}: {len(sp)} SP phrases")
        ticks = [n.tick for n in notes]
        for tick, length in sp:
            cnt = sum(1 for t in ticks if tick <= t < tick + length)
            if not 4 <= cnt <= 8:
                problems.append(f"{diff}: SP at {tick} covers {cnt} notes")
        for a, b in zip(notes, notes[1:]):
            if a.length and a.tick + a.length > b.tick - RES // 8:
                problems.append(f"{diff}: sustain at {a.tick} overlaps next note")
        for n in notes:
            f = n.frets()
            if diff == "easy" and (len(f) != 1 or f[0] > 2):
                problems.append(f"easy: bad note at {n.tick}")
            if diff == "medium" and (4 in f or len(f) > 2):
                problems.append(f"medium: bad note at {n.tick}")
            if diff == "hard" and len(f) > 2:
                problems.append(f"hard: 3-note chord at {n.tick}")

    # audio checks
    song, sr1 = sf.read(os.path.join(folder, "song.ogg"), dtype="float32")
    gtr, sr2 = sf.read(os.path.join(folder, "guitar.ogg"), dtype="float32")
    if sr1 != SR or sr2 != SR or song.shape != gtr.shape or song.shape[1] != 2:
        problems.append(f"audio format mismatch {song.shape} {gtr.shape} {sr1} {sr2}")
    if np.abs(song).max() >= 1.0 or np.abs(gtr).max() >= 1.0:
        problems.append("audio clipping")
    ex = ch["tracks"]["expert"]["notes"]
    cand = [tm.sec(ex[i].tick) for i in range(1, len(ex))
            if tm.sec(ex[i].tick) - tm.sec(ex[i - 1].tick) >= 0.12 and not ex[i].tap]
    errs = _onset_errors(gtr, cand)
    bad = [e for e in errs if abs(e) > 10]
    if bad:
        problems.append(f"{len(bad)}/{len(errs)} guitar onsets off by >10 ms: {bad[:5]}")
    print(f"    onset check: {len(errs)} notes, max |err| = {max(abs(e) for e in errs):.0f} ms, "
          f"mean = {np.mean(errs):+.1f} ms")

    # cross-check with the game's own loader when it is available
    try:
        sys.path.insert(0, ROOT)
        from gh.chart.loader import load_song  # type: ignore
        chart = load_song(folder)
        got = {d: len(t.notes) for d, t in chart.tracks.items()}
        want = {d: len(tr["notes"]) for d, tr in ch["tracks"].items()}
        if got != want:
            problems.append(f"gh loader note counts {got} != {want}")
        print(f"    gh loader: OK {got}, SP {[len(t.sp_phrases) for t in chart.tracks.values()]}")
    except Exception as exc:  # the loader is developed concurrently; informative only
        print(f"    gh loader check skipped: {type(exc).__name__}: {exc}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "Songs"))
    ap.add_argument("--serial", action="store_true")
    ap.add_argument("--no-validate", action="store_true")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    for song in SONGS:  # create folders here, not in the workers (child-made dirs can be invisible in sandboxes)
        os.makedirs(os.path.join(args.out, folder_name(song)), exist_ok=True)
    t0 = time.perf_counter()
    if args.serial:
        results = [generate_song(i, args.out) for i in range(len(SONGS))]
    else:
        with ProcessPoolExecutor(max_workers=len(SONGS)) as ex:
            results = list(ex.map(generate_song, range(len(SONGS)), [args.out] * len(SONGS)))
    for r in results:
        print(f"{os.path.basename(r['folder'])}: {r['length_ms'] / 1000:.1f}s bpm={r['bpm']} notes={r['notes']} "
              f"sp={r['sp']} hopo={r['hopo']} tap={r['tap']} open={r['open']} forced={r['forced']} "
              f"peak song/gtr={r['song_peak_db']:.1f}/{r['guitar_peak_db']:.1f} dBFS "
              f"rms song/gtr={r['song_rms_db']:.1f}/{r['guitar_rms_db']:.1f} dBFS ({r['seconds']:.1f}s)")
        for w in r["warnings"]:
            print("   design warning:", w)
    print(f"generated in {time.perf_counter() - t0:.1f}s")
    ok = True
    if not args.no_validate:
        for r in results:
            print(f"validating {os.path.basename(r['folder'])}")
            probs = validate_song(r["folder"])
            for p in probs:
                print("   PROBLEM:", p)
            ok &= not probs
        print("validation", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
