"""Synthesized sound effects (pure numpy, no pygame import).

Every public function returns an ``np.int16`` array of shape ``(n, 2)`` at the requested sample rate,
normalized to about -6 dBFS peak. Output is deterministic (fixed seeds). The front end turns them
into sounds with ``pygame.sndarray.make_sound`` (mixer must be initialised stereo, 16-bit).
"""
from __future__ import annotations

import numpy as np

PEAK_DB = -6.0

__all__ = ["miss_buzz", "sp_ready", "sp_activate", "sp_phrase_complete", "sp_deactivate", "menu_move",
           "menu_select", "menu_back", "metronome", "crowd_cheer", "fail_sound", "countdown_tick", "build_all"]


# --- helpers ------------------------------------------------------------------------------

def _t(sr: int, seconds: float) -> np.ndarray:
    return np.arange(int(round(sr * seconds))) / sr


def _hz(midi: float) -> float:
    return 440.0 * 2.0 ** ((midi - 69.0) / 12.0)


def _fft_filter(x: np.ndarray, sr: int, gain_fn) -> np.ndarray:
    """Zero-phase filter by magnitude curve. x: (n,) or (n, ch)."""
    n = x.shape[0]
    nfft = 1 << int(np.ceil(np.log2(n + 2048)))
    X = np.fft.rfft(x, n=nfft, axis=0)
    g = gain_fn(np.fft.rfftfreq(nfft, 1.0 / sr))
    X *= g[:, None] if x.ndim == 2 else g
    return np.fft.irfft(X, n=nfft, axis=0)[:n]


def _lp(f, fc, order=2):
    return 1.0 / np.sqrt(1.0 + (f / fc) ** (2 * order))


def _hp(f, fc, order=2):
    f = np.maximum(f, 1e-3)
    return 1.0 / np.sqrt(1.0 + (fc / f) ** (2 * order))


def _fade(x: np.ndarray, sr: int, fade_in: float = 0.002, fade_out: float = 0.01) -> np.ndarray:
    x = x.copy()
    n = x.shape[0]
    a = min(n, max(1, int(fade_in * sr)))
    r = min(n, max(1, int(fade_out * sr)))
    ramp_in = np.linspace(0.0, 1.0, a)
    ramp_out = np.linspace(1.0, 0.0, r)
    if x.ndim == 2:
        ramp_in, ramp_out = ramp_in[:, None], ramp_out[:, None]
    x[:a] *= ramp_in
    x[n - r:] *= ramp_out
    return x


def _finish(x: np.ndarray, sr: int, width: float = 0.0, peak_db: float = PEAK_DB) -> np.ndarray:
    """mono (n,) or stereo (n, 2) float -> int16 (n, 2) at peak_db. width: Haas spread for mono."""
    if x.ndim == 1:
        if width > 0:
            d = max(1, int(width * 0.001 * sr))
            right = np.concatenate([np.zeros(d), x[:-d]]) if x.size > d else x
            x = np.stack([x, 0.85 * x + 0.15 * right], axis=1)
        else:
            x = np.stack([x, x], axis=1)
    x = _fade(x, sr, 0.001, 0.008)
    pk = float(np.abs(x).max())
    if pk > 0:
        x = x * (10.0 ** (peak_db / 20.0) / pk)
    return np.round(x * 32767.0).astype(np.int16)


def _bell(freq: float, t: np.ndarray, decay: float) -> np.ndarray:
    """Soft bell/chime: fundamental + a few inharmonic partials."""
    out = np.zeros_like(t)
    for ratio, amp, dmul in ((1.0, 1.0, 1.0), (2.0, 0.35, 0.6), (2.76, 0.2, 0.4), (5.4, 0.08, 0.25)):
        out += amp * np.sin(2 * np.pi * freq * ratio * t) * np.exp(-t / (decay * dmul))
    return out * (1.0 - np.exp(-t / 0.0015))


def _sweep_noise(n: int, sr: int, f0: float, f1: float, rng: np.random.Generator, bw_oct: float = 0.6) -> np.ndarray:
    """Noise through a band-pass whose centre glides (log) from f0 to f1 (Hann overlap-add)."""
    noise = rng.standard_normal(n)
    hop = 1024
    win = 2 * hop
    out = np.zeros(n + win)
    w = np.hanning(win)
    freqs = np.fft.rfftfreq(win, 1.0 / sr)
    lf = np.log2(np.maximum(freqs, 1.0))
    for start in range(0, n, hop):
        seg = np.zeros(win)
        chunk = noise[start:start + win]
        seg[:chunk.size] = chunk
        pos = min(1.0, start / max(1, n - 1))
        fc = f0 * (f1 / f0) ** pos
        g = np.exp(-((lf - np.log2(fc)) ** 2) / (2 * bw_oct ** 2))
        out[start:start + win] += np.fft.irfft(np.fft.rfft(seg * w) * g, win)
    return out[:n]


def _saw(freq: float, t: np.ndarray, harmonics: int = 12) -> np.ndarray:
    out = np.zeros_like(t)
    for k in range(1, harmonics + 1):
        out += np.sin(2 * np.pi * freq * k * t) / k
    return out


# --- gameplay -----------------------------------------------------------------------------------

def miss_buzz(sr: int) -> np.ndarray:
    """Muted-string clunk + fret buzz for missed notes / overstrums (~0.25 s)."""
    rng = np.random.default_rng(101)
    t = _t(sr, 0.25)
    body = np.zeros_like(t)
    for f in (82.4, 87.3, 123.5):              # dissonant, muted low strings
        ph = 2 * np.pi * f * t
        body += np.sign(np.sin(ph)) * 0.5 + np.sin(ph)
    buzz = np.tanh(3.0 * body) * np.exp(-t / 0.07)
    buzz = _fft_filter(buzz, sr, lambda f: _lp(f, 1600, 2) * _hp(f, 60, 1))
    thump = _fft_filter(rng.standard_normal(t.size), sr, lambda f: _lp(f, 900, 2)) * np.exp(-t / 0.018)
    thump /= np.abs(thump).max() + 1e-9
    return _finish(buzz / (np.abs(buzz).max() + 1e-9) + 0.6 * thump, sr, width=6)


def sp_ready(sr: int) -> np.ndarray:
    """Short two-note chime when the Star Power bar reaches 50%."""
    t = _t(sr, 0.55)
    x = 0.8 * _bell(_hz(88), t, 0.25)            # E6
    d = int(0.07 * sr)
    x[d:] += _bell(_hz(95), t[:-d], 0.3)          # B6
    return _finish(x, sr, width=12)


def sp_activate(sr: int) -> np.ndarray:
    """Rising whoosh into a bright major chord (~1 s)."""
    rng = np.random.default_rng(303)
    t = _t(sr, 1.1)
    n = t.size
    whoosh = _sweep_noise(n, sr, 300.0, 6000.0, rng, 0.5)
    whoosh *= np.clip(t / 0.35, 0.0, 1.0) ** 2 * np.exp(-np.maximum(t - 0.35, 0.0) / 0.12)
    whoosh /= np.abs(whoosh).max() + 1e-9
    chord = np.zeros(n)
    on = int(0.33 * sr)
    tc = t[: n - on]
    for m in (76, 80, 83, 88):                   # E major, bright
        for det in (-0.08, 0.08):
            chord[on:] += _saw(_hz(m + det), tc, 10)
    chord[on:] *= (1.0 - np.exp(-tc / 0.01)) * np.exp(-tc / 0.35)
    chord = _fft_filter(chord, sr, lambda f: _lp(f, 7000, 1) * _hp(f, 200, 1))
    chord /= np.abs(chord).max() + 1e-9
    sparkle = np.zeros(n)
    sparkle[on:] = _bell(_hz(100), tc, 0.2) * 0.4
    left = 0.8 * whoosh + chord + sparkle
    rng2 = np.random.default_rng(304)
    whoosh_r = _sweep_noise(n, sr, 300.0, 6000.0, rng2, 0.5)
    whoosh_r *= np.clip(t / 0.35, 0.0, 1.0) ** 2 * np.exp(-np.maximum(t - 0.35, 0.0) / 0.12)
    whoosh_r /= np.abs(whoosh_r).max() + 1e-9
    right = 0.8 * whoosh_r + chord + sparkle
    return _finish(np.stack([left, right], axis=1), sr)


def sp_phrase_complete(sr: int) -> np.ndarray:
    """Quick ascending sparkle (~0.4 s) when a Star Power phrase is completed."""
    rng = np.random.default_rng(505)
    t = _t(sr, 0.42)
    x = np.zeros(t.size)
    for i, m in enumerate((84, 88, 91, 96, 100)):
        d = int(i * 0.035 * sr)
        x[d:] += (0.7 + 0.08 * i) * _bell(_hz(m), t[: t.size - d], 0.09)
    shimmer = _fft_filter(rng.standard_normal(t.size), sr, lambda f: _hp(f, 6000, 2)) * np.exp(-t / 0.12)
    x += 0.15 * shimmer / (np.abs(shimmer).max() + 1e-9)
    return _finish(x, sr, width=9)


def sp_deactivate(sr: int) -> np.ndarray:
    """Soft falling sweep when Star Power runs out (~0.6 s)."""
    rng = np.random.default_rng(606)
    t = _t(sr, 0.6)
    f = 1100.0 * (300.0 / 1100.0) ** (t / t[-1])
    ph = 2 * np.pi * np.cumsum(f) / sr
    tone = (np.sin(ph) + 0.3 * np.sin(2 * ph)) * np.exp(-t / 0.25)
    air = _sweep_noise(t.size, sr, 4000.0, 400.0, rng, 0.5) * np.exp(-t / 0.2)
    air /= np.abs(air).max() + 1e-9
    return _finish(tone + 0.35 * air, sr, width=10)


def fail_sound(sr: int) -> np.ndarray:
    """Distorted guitar dive-bomb + low rumble (~1.5 s) when the player fails."""
    rng = np.random.default_rng(707)
    t = _t(sr, 1.5)
    f = _hz(52) * 2.0 ** (-24.0 * np.clip(t / 1.3, 0.0, 1.0) ** 1.5 / 12.0)
    ph = 2 * np.pi * np.cumsum(f) / sr
    g = np.sin(ph) + 0.5 * np.sin(2 * ph + 0.3) + 0.3 * np.sin(3 * ph + 0.7)
    g = np.tanh(4.0 * g) * np.exp(-t / 0.8)
    g = _fft_filter(g, sr, lambda fr: _lp(fr, 2500, 2) * _hp(fr, 50, 1))
    rumble = _fft_filter(rng.standard_normal(t.size), sr, lambda fr: _lp(fr, 200, 2)) * np.exp(-t / 0.5)
    rumble /= np.abs(rumble).max() + 1e-9
    x = g / (np.abs(g).max() + 1e-9) + 0.4 * rumble
    return _finish(x, sr, width=8)


def crowd_cheer(sr: int, seconds: float = 3.0) -> np.ndarray:
    """Crowd swell: band-limited noise bed + 'whoo' voices + claps, rising then fading."""
    rng = np.random.default_rng(909)
    t = _t(sr, seconds)
    n = t.size
    swell = np.clip(t / (0.3 * seconds), 0.0, 1.0) ** 1.5 * np.clip((seconds - t) / (0.35 * seconds), 0.0, 1.0)
    chans = []
    for ch in range(2):
        bed = _fft_filter(rng.standard_normal(n), sr, lambda f: _hp(f, 250, 1) * _lp(f, 3500, 2))
        bed /= np.abs(bed).max() + 1e-9
        voices = np.zeros(n)
        for _ in range(14):                     # individual "whoo"s: formant-ish gliding tones
            start = int(rng.uniform(0.0, 0.8) * n)
            ln = int(rng.uniform(0.3, 0.9) * sr)
            ln = min(ln, n - start)
            if ln <= 10:
                continue
            tv = np.arange(ln) / sr
            f0 = rng.uniform(250.0, 520.0) * (1.0 + 0.25 * np.sin(np.pi * tv / tv[-1]))
            ph = 2 * np.pi * np.cumsum(f0) / sr
            v = (np.sin(ph) + 0.4 * np.sin(2 * ph) + 0.2 * np.sin(3 * ph)) * np.sin(np.pi * tv / tv[-1]) ** 2
            voices[start:start + ln] += v * rng.uniform(0.3, 0.7)
        claps = np.zeros(n)
        clap = _fft_filter(rng.standard_normal(int(0.03 * sr)), sr, lambda f: _hp(f, 900, 2) * _lp(f, 5000, 1))
        clap *= np.exp(-np.arange(clap.size) / (0.006 * sr))
        clap /= np.abs(clap).max() + 1e-9
        for _ in range(int(40 * seconds)):
            s = int(rng.uniform(0.0, 1.0) * (n - clap.size))
            claps[s:s + clap.size] += clap * rng.uniform(0.2, 0.6)
        chans.append((0.9 * bed + 0.35 * voices + 0.35 * claps) * swell)
    return _finish(np.stack(chans, axis=1), sr)


# --- menus / timing -------------------------------------------------------------------------------

def _blip(sr: int, freqs: list[float], step: float, decay: float, length: float) -> np.ndarray:
    t = _t(sr, length)
    x = np.zeros(t.size)
    for i, f in enumerate(freqs):
        d = int(i * step * sr)
        tt = t[: t.size - d]
        x[d:] += (np.sin(2 * np.pi * f * tt) + 0.25 * np.sin(4 * np.pi * f * tt)) * np.exp(-tt / decay) \
            * (1.0 - np.exp(-tt / 0.001))
    return x


def menu_move(sr: int) -> np.ndarray:
    """Tiny tick for moving the menu cursor (~50 ms)."""
    return _finish(_blip(sr, [1320.0], 0.0, 0.012, 0.05), sr, width=4)


def menu_select(sr: int) -> np.ndarray:
    """Rising two-note confirm (~0.18 s)."""
    return _finish(_blip(sr, [880.0, 1318.5], 0.06, 0.05, 0.18), sr, width=6)


def menu_back(sr: int) -> np.ndarray:
    """Falling two-note cancel (~0.18 s)."""
    return _finish(_blip(sr, [659.3, 440.0], 0.06, 0.05, 0.18), sr, width=6)


def metronome(sr: int, accent: bool = False) -> np.ndarray:
    """Woodblock-style click; accent = higher and brighter (bar downbeat)."""
    t = _t(sr, 0.06)
    f = 1650.0 if accent else 1100.0
    x = (np.sin(2 * np.pi * f * t) + 0.4 * np.sin(2 * np.pi * f * 2.71 * t)) * np.exp(-t / 0.012)
    return _finish(x, sr, peak_db=PEAK_DB if accent else PEAK_DB - 3.0)


def countdown_tick(sr: int) -> np.ndarray:
    """Drumstick-like click for the pre-song / unpause countdown (~80 ms)."""
    rng = np.random.default_rng(1111)
    t = _t(sr, 0.08)
    nz = _fft_filter(rng.standard_normal(t.size), sr, lambda f: _hp(f, 1800, 2) * _lp(f, 6500, 2))
    nz = nz / (np.abs(nz).max() + 1e-9) * np.exp(-t / 0.01)
    tone = 0.6 * np.sin(2 * np.pi * 2350.0 * t) * np.exp(-t / 0.015)
    return _finish(nz + tone, sr)


def build_all(sr: int) -> dict[str, np.ndarray]:
    """All effects by name (metronome split into accent / normal)."""
    return {
        "miss": miss_buzz(sr),
        "sp_ready": sp_ready(sr),
        "sp_activate": sp_activate(sr),
        "sp_phrase_complete": sp_phrase_complete(sr),
        "sp_deactivate": sp_deactivate(sr),
        "menu_move": menu_move(sr),
        "menu_select": menu_select(sr),
        "menu_back": menu_back(sr),
        "metronome_accent": metronome(sr, True),
        "metronome": metronome(sr, False),
        "crowd_cheer": crowd_cheer(sr),
        "fail": fail_sound(sr),
        "countdown_tick": countdown_tick(sr),
    }
