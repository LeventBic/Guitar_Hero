"""Deterministic numpy synthesis primitives for the RIFF demo songs.

Everything here is pure numpy (no scipy): FFT-domain zero-phase filters, additive / naive
oscillators, a synthesized drum kit, guitar/bass/pad voices, FFT convolution reverb and
mix helpers. All randomness goes through an explicit np.random.Generator.
"""
from __future__ import annotations

import numpy as np

SR = 44100


# --- basics ------------------------------------------------------------------------

def midi_to_hz(m: float) -> float:
    return 440.0 * 2.0 ** ((m - 69.0) / 12.0)


def fast_len(n: int) -> int:
    """Smallest 2^a*3^b*5^c >= n (fast pocketfft size)."""
    best = 1 << int(np.ceil(np.log2(max(n, 1))))
    p5 = 1
    while p5 < best:
        p35 = p5
        while p35 < best:
            p = p35
            while p < n:
                p *= 2
            best = min(best, p)
            p35 *= 3
        p5 *= 5
    return best


def lp_curve(f, fc, order=2):
    return 1.0 / np.sqrt(1.0 + (np.asarray(f) / fc) ** (2 * order))


def hp_curve(f, fc, order=2):
    f = np.maximum(np.asarray(f, dtype=np.float64), 1e-3)
    return 1.0 / np.sqrt(1.0 + (fc / f) ** (2 * order))


def peak_curve(f, f0, gain_db, width_oct=0.7):
    f = np.maximum(np.asarray(f, dtype=np.float64), 1e-3)
    g = 10.0 ** (gain_db / 20.0) - 1.0
    return 1.0 + g * np.exp(-(np.log2(f / f0) ** 2) / (2 * width_oct ** 2))


def fft_filter(x: np.ndarray, gain_fn, sr: int = SR, pad: int = 4096) -> np.ndarray:
    """Zero-phase filter with a magnitude curve gain_fn(freqs). x: (n,) or (n, ch)."""
    n = x.shape[0]
    nfft = fast_len(n + pad)
    X = np.fft.rfft(x, n=nfft, axis=0)
    g = gain_fn(np.fft.rfftfreq(nfft, 1.0 / sr))
    X *= g[:, None] if x.ndim == 2 else g
    return np.fft.irfft(X, n=nfft, axis=0)[:n]


def fft_convolve(x: np.ndarray, ir: np.ndarray) -> np.ndarray:
    """Linear convolution, output trimmed to len(x). x (n,), ir (m,)."""
    n = x.shape[0]
    nfft = fast_len(n + ir.shape[0])
    y = np.fft.irfft(np.fft.rfft(x, nfft) * np.fft.rfft(ir, nfft), nfft)
    return y[:n]


def pan_gains(pan: float) -> tuple[float, float]:
    """pan -1 (L) .. +1 (R), equal power."""
    a = (pan + 1.0) * np.pi / 4.0
    return float(np.cos(a)), float(np.sin(a))


def add_mono(buf: np.ndarray, sig: np.ndarray, start: int, gain: float = 1.0, pan: float = 0.0) -> None:
    """Mix a mono signal into a stereo buffer at sample `start` (clipped to the buffer)."""
    if start >= buf.shape[0] or sig.size == 0:
        return
    s0 = max(start, 0)
    off = s0 - start
    end = min(buf.shape[0], start + sig.shape[0])
    if end <= s0:
        return
    seg = sig[off:off + (end - s0)] * gain
    gl, gr = pan_gains(pan)
    buf[s0:end, 0] += seg * gl
    buf[s0:end, 1] += seg * gr


def naive_saw(phase_cycles: np.ndarray) -> np.ndarray:
    return 2.0 * (phase_cycles - np.floor(phase_cycles)) - 1.0


def phase_from_freq(f: np.ndarray | float, n: int, sr: int = SR) -> np.ndarray:
    """Phase in cycles for a (possibly time varying) frequency."""
    if np.isscalar(f):
        return np.arange(n) * (float(f) / sr)
    return np.cumsum(f) / sr


def release_env(n: int, sr: int, release: float) -> np.ndarray:
    """1.0 then linear fade over the last `release` seconds so the signal ends at exactly 0."""
    env = np.ones(n)
    r = min(n, max(1, int(release * sr)))
    env[n - r:] = np.linspace(1.0, 0.0, r)
    return env


def attack_env(n: int, sr: int, attack: float) -> np.ndarray:
    env = np.ones(n)
    a = min(n, max(1, int(attack * sr)))
    env[:a] = np.linspace(0.0, 1.0, a)
    return env


# --- drum kit ----------------------------------------------------------------------

def make_drum_kit(sr: int, rng: np.random.Generator) -> dict[str, np.ndarray]:
    kit: dict[str, np.ndarray] = {}

    def t_of(sec):
        return np.arange(int(sec * sr)) / sr

    # kick: sine sweep + click
    t = t_of(0.45)
    f = 48.0 + 115.0 * np.exp(-t / 0.032)
    ph = phase_from_freq(f, t.size, sr)
    k = np.sin(2 * np.pi * ph) * np.exp(-t / 0.22)
    click = rng.standard_normal(t.size) * np.exp(-t / 0.0025) * 0.35
    k = np.tanh(1.6 * (k + fft_filter(click, lambda fr: hp_curve(fr, 1500), sr)))
    kit["kick"] = k * release_env(t.size, sr, 0.02)

    # snare: two tones + band-limited noise
    t = t_of(0.38)
    tone = (0.55 * np.sin(2 * np.pi * 185 * t) * np.exp(-t / 0.055)
            + 0.25 * np.sin(2 * np.pi * 330 * t) * np.exp(-t / 0.035))
    nz = fft_filter(rng.standard_normal(t.size), lambda fr: hp_curve(fr, 1100, 2) * lp_curve(fr, 9000, 2), sr)
    nz = nz / (np.abs(nz).max() + 1e-9) * np.exp(-t / 0.11)
    kit["snare"] = np.tanh(1.3 * (tone + 0.9 * nz)) * release_env(t.size, sr, 0.03)

    # hats
    for name, dec, length in (("hat", 0.032, 0.15), ("ohat", 0.22, 0.6)):
        t = t_of(length)
        nz = fft_filter(rng.standard_normal(t.size), lambda fr: hp_curve(fr, 7000, 3) * peak_curve(fr, 10000, 4, 0.5), sr)
        nz = nz / (np.abs(nz).max() + 1e-9)
        kit[name] = nz * np.exp(-t / dec) * release_env(t.size, sr, 0.02)

    # crash & ride: noise + inharmonic partials
    t = t_of(2.6)
    nz = fft_filter(rng.standard_normal(t.size), lambda fr: hp_curve(fr, 3500, 2) * lp_curve(fr, 14000, 1), sr)
    nz = nz / (np.abs(nz).max() + 1e-9)
    partials = sum(np.sin(2 * np.pi * fr * t + rng.uniform(0, 6.28)) for fr in (3150, 4270, 5380, 6720, 8010))
    crash = (nz + 0.08 * partials) * np.exp(-t / 0.85)
    crash *= attack_env(t.size, sr, 0.002)
    kit["crash"] = crash / (np.abs(crash).max() + 1e-9) * release_env(t.size, sr, 0.1)

    t = t_of(1.2)
    nz = fft_filter(rng.standard_normal(t.size), lambda fr: hp_curve(fr, 5000, 2), sr)
    nz = nz / (np.abs(nz).max() + 1e-9)
    bell = sum(np.sin(2 * np.pi * fr * t) for fr in (2520, 3790, 5110))
    ride = 0.6 * nz * np.exp(-t / 0.35) + 0.15 * bell * np.exp(-t / 0.5)
    kit["ride"] = ride / (np.abs(ride).max() + 1e-9) * release_env(t.size, sr, 0.05)

    # toms
    for name, f0 in (("tom_h", 190.0), ("tom_m", 140.0), ("tom_l", 100.0)):
        t = t_of(0.5)
        f = f0 * (1.0 + 0.45 * np.exp(-t / 0.02))
        tom = np.sin(2 * np.pi * phase_from_freq(f, t.size, sr)) * np.exp(-t / 0.18)
        nz = fft_filter(rng.standard_normal(t.size), lambda fr: lp_curve(fr, 3000), sr)
        tom += 0.15 * nz / (np.abs(nz).max() + 1e-9) * np.exp(-t / 0.02)
        kit[name] = np.tanh(1.4 * tom) * release_env(t.size, sr, 0.03)

    # stick click (count-in)
    t = t_of(0.08)
    nz = fft_filter(rng.standard_normal(t.size), lambda fr: hp_curve(fr, 1800, 2) * lp_curve(fr, 6000, 2), sr)
    stick = nz / (np.abs(nz).max() + 1e-9) * np.exp(-t / 0.012) + 0.4 * np.sin(2 * np.pi * 2400 * t) * np.exp(-t / 0.01)
    kit["stick"] = stick * release_env(t.size, sr, 0.01)
    return kit


# --- pitched voices ----------------------------------------------------------------

def lead_guitar_note(midis: list[float], dur: float, sr: int, *, kind: str = "strum", sustain: bool = False,
                     drive: float = 5.0, rng: np.random.Generator | None = None,
                     release: float = 0.012, natural_decay: float = 0.55) -> np.ndarray:
    """Distorted plucked lead-guitar tone (additive harmonics with per-harmonic decay -> tanh).

    kind: 'strum' (hard pick attack + pick noise), 'hopo' (soft attack, slight slide up), 'tap'.
    sustain: ring at level with delayed vibrato; otherwise decays naturally.
    Output ends at exactly zero (release fade) so the next note's onset is clean.
    """
    n = max(1, int(round(dur * sr)))
    t = np.arange(n) / sr
    cents = np.zeros(n)
    if kind == "hopo":
        cents -= 45.0 * np.exp(-t / 0.010)
    elif kind == "tap":
        cents -= 20.0 * np.exp(-t / 0.006)
    if sustain and dur > 0.3:
        depth = 28.0 * np.clip((t - 0.22) / 0.45, 0.0, 1.0)
        cents += depth * np.sin(2 * np.pi * 5.6 * np.maximum(t - 0.22, 0.0))
    ratio = 2.0 ** (cents / 1200.0)

    x = np.zeros(n)
    vg = 1.0 / np.sqrt(len(midis))
    for vi, m in enumerate(midis):
        f0 = midi_to_hz(m)
        ph = phase_from_freq(f0 * ratio, n, sr)
        kmax = int(min(10, (0.42 * sr) // f0))
        for k in range(1, kmax + 1):
            amp = (1.0 / k) * (1.0 if k % 2 else 0.7)
            dec = 0.9 + 0.55 * k
            x += vg * amp * np.exp(-t * dec) * np.sin(2 * np.pi * k * ph + 0.37 * k * (vi + 1))
    # input level envelope: pluck energy decays -> distortion keeps it compressed
    inp = (0.25 + 0.75 * np.exp(-t / 0.35)) if sustain else (0.08 + 0.92 * np.exp(-t / 0.22))
    x *= inp
    if kind == "strum" and rng is not None:
        nl = min(n, int(0.006 * sr))
        pick = rng.standard_normal(nl) * np.linspace(1.0, 0.0, nl) * 0.5
        x[:nl] += pick
    y = np.tanh(drive * x) / np.tanh(drive)
    # output envelope
    if kind == "strum":
        env = attack_env(n, sr, 0.0015)
        level = 1.0
    elif kind == "hopo":
        env = attack_env(n, sr, 0.006)
        level = 0.78
    else:  # tap
        env = attack_env(n, sr, 0.003)
        level = 0.85
    if sustain:
        env *= 1.0 - 0.25 * np.clip(t / max(dur, 1e-3), 0.0, 1.0)
    else:
        env *= np.exp(-t / natural_decay)
    env *= release_env(n, sr, min(release, dur * 0.5))
    return (y * env * level).astype(np.float64)


def rhythm_guitar_hit(midis: list[float], dur: float, sr: int, *, drive: float = 4.0, muted: bool = False,
                      detune_cents: float = 0.0) -> np.ndarray:
    """Power-chord rhythm guitar (naive saws -> tanh). muted=True gives a short palm-muted chug."""
    n = max(1, int(round(dur * sr)))
    t = np.arange(n) / sr
    x = np.zeros(n)
    r = 2.0 ** (detune_cents / 1200.0)
    for i, m in enumerate(midis):
        f0 = midi_to_hz(m) * r
        x += naive_saw(np.arange(n) * (f0 / sr) + 0.21 * i) / len(midis)
    if muted:
        x *= np.exp(-t / 0.05)
        y = np.tanh(drive * 0.7 * x)
        env = attack_env(n, sr, 0.002) * np.exp(-t / 0.09)
    else:
        x *= 0.3 + 0.7 * np.exp(-t / 0.6)
        y = np.tanh(drive * x)
        env = attack_env(n, sr, 0.003) * (0.55 + 0.45 * np.exp(-t / 0.3))
    env *= release_env(n, sr, min(0.03, dur * 0.4))
    return y * env


def bass_note(midi: float, dur: float, sr: int, *, grit: float = 1.5) -> np.ndarray:
    n = max(1, int(round(dur * sr)))
    t = np.arange(n) / sr
    f0 = midi_to_hz(midi)
    ph = np.arange(n) * (f0 / sr)
    x = np.sin(2 * np.pi * ph) + 0.35 * naive_saw(ph + 0.25) * np.exp(-t / 0.25)
    x = np.tanh(grit * x) / np.tanh(grit)
    env = attack_env(n, sr, 0.004) * (0.45 + 0.55 * np.exp(-t / 0.35)) * release_env(n, sr, min(0.02, dur * 0.4))
    return x * env


def pad_chord(midis: list[float], dur: float, sr: int, *, organ: bool = False) -> np.ndarray:
    n = max(1, int(round(dur * sr)))
    t = np.arange(n) / sr
    x = np.zeros(n)
    for m in midis:
        f0 = midi_to_hz(m)
        if organ:
            for h, a in ((1, 1.0), (2, 0.6), (3, 0.35), (4, 0.25), (6, 0.1)):
                x += a * np.sin(2 * np.pi * f0 * h * t + h)
        else:
            for d in (-7.0, 7.0):
                x += 0.5 * naive_saw(t * f0 * 2.0 ** (d / 1200.0) + (d > 0) * 0.5)
    x /= max(1, len(midis))
    env = attack_env(n, sr, 0.12 if not organ else 0.03) * release_env(n, sr, min(0.25, dur * 0.4))
    return x * env


# --- reverb / master ------------------------------------------------------------------

def make_reverb_ir(sr: int, rng: np.random.Generator, seconds: float = 1.6, predelay: float = 0.015,
                   damp_hz: float = 5000.0) -> np.ndarray:
    """Stereo IR (m, 2): decaying filtered noise with a small predelay."""
    n = int(seconds * sr)
    t = np.arange(n) / sr
    ir = rng.standard_normal((n, 2)) * np.exp(-t / (seconds / 6.9))[:, None]
    ir = fft_filter(ir, lambda f: lp_curve(f, damp_hz, 1) * hp_curve(f, 200, 1), sr)
    pd = int(predelay * sr)
    ir = np.vstack([np.zeros((pd, 2)), ir])
    ir /= np.sqrt((ir ** 2).sum(axis=0, keepdims=True)) + 1e-12
    return ir


def apply_reverb(x: np.ndarray, ir: np.ndarray) -> np.ndarray:
    """x (n, 2) -> wet (n, 2); each input channel feeds both IR channels (L->L, R->R + cross)."""
    mono = x.mean(axis=1)
    wet = np.empty_like(x)
    wet[:, 0] = fft_convolve(0.7 * x[:, 0] + 0.3 * mono, ir[:, 0])
    wet[:, 1] = fft_convolve(0.7 * x[:, 1] + 0.3 * mono, ir[:, 1])
    return wet


def rms(x: np.ndarray, gate: float = 1e-4) -> float:
    """RMS over the non-silent part of the signal."""
    m = np.abs(x).max(axis=1) if x.ndim == 2 else np.abs(x)
    sel = x[m > gate]
    return float(np.sqrt(np.mean(sel ** 2))) if sel.size else 0.0


def peak_normalize(x: np.ndarray, peak_db: float) -> np.ndarray:
    pk = float(np.abs(x).max())
    if pk <= 0:
        return x
    return x * (10.0 ** (peak_db / 20.0) / pk)


def soft_limit(x: np.ndarray, ceiling: float) -> np.ndarray:
    """Transparent below 70% of ceiling, tanh knee above -> never exceeds ceiling."""
    knee = 0.7 * ceiling
    a = np.abs(x)
    over = a > knee
    y = x.copy()
    rng_ = ceiling - knee
    y[over] = np.sign(x[over]) * (knee + rng_ * np.tanh((a[over] - knee) / rng_))
    return y
