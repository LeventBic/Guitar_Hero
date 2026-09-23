"""GELISTIRME ARACI: 'gercekci' sentetik rock miksi (distorsiyonlu gitar + bas + davul) ve gitar ground truth'u.

Demo sarkilarin gitari sade pluck sentezi oldugu icin Demucs onu gitar olarak tanimayabilir; bu uretec
Karplus-Strong telleri + pena gurultusu + tanh overdrive + kabin filtresi + cift kayit (L/R) ile daha gercekci
bir elektro gitar uretir. Bolumler: palm-mute chug riff, uzun power chord'lar, tek nota lead, gitarsiz ara.

make_mix(seed=1) -> RealMix(mix (2,L), guitar (2,L), backing (2,L), sr, bpm, events [(t, [midi..], dur, tur)])
python tools/realistic_mix.py out.wav  -> miks + gitar stem'i wav olarak (dinlemek icin)
"""
from __future__ import annotations

import sys
import wave
from dataclasses import dataclass, field

import numpy as np

SR = 44100


@dataclass
class RealMix:
    mix: np.ndarray
    guitar: np.ndarray
    backing: np.ndarray
    sr: int
    bpm: float
    events: list = field(default_factory=list)      # (zaman, [midi], sure, tur) gitar
    silent: list = field(default_factory=list)      # [(t0, t1)] gitarsiz bolgeler


def _lowpass(x: np.ndarray, cutoff: float, taps: int = 255) -> np.ndarray:
    n = np.arange(taps) - (taps - 1) / 2
    h = 2 * cutoff / SR * np.sinc(2 * cutoff / SR * n) * np.blackman(taps)
    h /= h.sum()
    return np.convolve(x, h, mode="same")


def _highpass(x: np.ndarray, cutoff: float) -> np.ndarray:
    return x - _lowpass(x, cutoff)


def _ks(freq: float, dur: float, rng, bright: float = 0.5, decay: float = 0.996, mute: bool = False) -> np.ndarray:
    """Karplus-Strong tel (periyot bloklari halinde vektorize)."""
    n = int(dur * SR)
    N = max(2, int(round(SR / freq)))
    y = np.zeros(n + N + 1)
    burst = rng.uniform(-1, 1, N)
    burst = bright * burst + (1 - bright) * np.convolve(burst, np.ones(4) / 4, mode="same")
    y[:N] = burst
    d = decay if not mute else 0.93
    k = N
    while k < n:
        e = min(k + N, n)
        prev = y[k - N:e - N]
        prev2 = y[k - N - 1:e - N - 1] if k - N - 1 >= 0 else np.concatenate([[0.0], y[k - N:e - N - 1]])
        y[k:e] = d * 0.5 * (prev + prev2[:prev.size])
        k = e
    out = y[:n]
    if mute:
        out = _lowpass(out, 900.0, 101)
    return out


def _distort(x: np.ndarray, gain: float = 14.0) -> np.ndarray:
    # not: daha yumusak (gain ~6) distorsiyonu Demucs gitar olarak tanimiyor (SDR ~1.7 dB); 14 -> ~9.6 dB
    x = _highpass(x, 90.0)
    y = np.tanh(gain * x) * 0.6 + 0.4 * np.tanh(gain * 0.4 * x)
    # kabin: 5 kHz ustu ve 80 Hz alti zayif, 2 kHz civari hafif tepe
    y = _lowpass(y, 5200.0)
    y = _highpass(y, 80.0)
    return y


def _midi_hz(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


def _guitar_take(events, total: int, rng, detune: float, jitter: float) -> np.ndarray:
    out = np.zeros(total)
    for t, notes, dur, kind in events:
        t0 = t + rng.normal(0, jitter)
        i = int(max(0, t0) * SR)
        mute = kind == "mute"
        sig = np.zeros(int((dur + 0.05) * SR))
        for m in notes:
            s = _ks(_midi_hz(m) * (1 + detune * rng.normal()), dur + 0.05, rng, bright=0.7, mute=mute)
            sig[:s.size] += s[:sig.size]
        rel = np.ones(sig.size)
        k = int(0.02 * SR)
        rel[-k:] = np.linspace(1, 0, k)
        sig *= rel
        seg = sig[:max(0, total - i)]
        out[i:i + seg.size] += seg * (0.8 if mute else 1.0)
    return _distort(out / 3.0)


def _drums(beats: np.ndarray, total: int, rng) -> np.ndarray:
    out = np.zeros(total)
    tk = np.arange(int(0.25 * SR)) / SR
    kick = np.sin(2 * np.pi * np.cumsum(45 + 110 * np.exp(-tk * 30)) / SR) * np.exp(-tk * 12)
    ts = np.arange(int(0.2 * SR)) / SR
    snare = (0.8 * _highpass(rng.uniform(-1, 1, ts.size), 1500) + 0.5 * np.sin(2 * np.pi * 185 * ts)) * np.exp(-ts * 22)
    th = np.arange(int(0.06 * SR)) / SR
    hat = _highpass(rng.uniform(-1, 1, th.size), 7000) * np.exp(-th * 70)

    def add(sig, t, g):
        i = int(t * SR)
        seg = sig[:max(0, total - i)]
        out[i:i + seg.size] += g * seg

    ibi = float(np.median(np.diff(beats)))
    for k, b in enumerate(beats):
        add(kick if k % 2 == 0 else snare, b, 0.9 if k % 2 == 0 else 0.6)
        add(hat, b, 0.25)
        add(hat, b + ibi / 2, 0.18)
    return out


def _bass(events, total: int) -> np.ndarray:
    out = np.zeros(total)
    for t, notes, dur, kind in events:
        f = _midi_hz(min(notes) - 12)
        n = int(dur * SR)
        tt = np.arange(n) / SR
        sig = sum(np.sin(2 * np.pi * f * h * tt) / h ** 1.5 for h in range(1, 6))
        sig *= np.exp(-tt * 3) * np.minimum(1, tt / 0.005)
        i = int(t * SR)
        seg = sig[:max(0, total - i)]
        out[i:i + seg.size] += 0.5 * seg
    return _lowpass(out, 700)


def riff_events(bpm: float, start: float) -> tuple[list, list, float]:
    """Gitar olaylari: (zaman, [midi], sure, tur)."""
    b = 60.0 / bpm
    ev = []
    t = start
    E5, G5, A5, D5, C5, B5 = [40, 47, 52], [43, 50, 55], [45, 52, 57], [38, 45, 50], [36, 43, 48], [47, 54, 59]
    # A: palm-mute chug riff (8'likler) + aksanli power chord'lar, 8 olcu
    pattern = [("m", 40), ("m", 40), ("c", G5), ("m", 40), ("m", 40), ("c", A5), ("m", 40), ("c", G5)]
    for bar in range(8):
        for k, (kind, n) in enumerate(pattern):
            notes = [n, n + 7] if kind == "m" else n
            ev.append((t + k * b / 2, notes, b / 2 * 0.9, "mute" if kind == "m" else "chord"))
        t += 4 * b
    # B: uzun power chord'lar (yarim / tam notalar), 8 olcu
    prog = [C5, D5, E5, E5, C5, D5, B5, E5]
    for bar, ch in enumerate(prog):
        if bar % 2 == 0:
            ev.append((t, ch, 2 * b * 0.95, "chord"))
            ev.append((t + 2 * b, ch, 2 * b * 0.95, "chord"))
        else:
            ev.append((t, ch, 4 * b * 0.97, "chord"))
        t += 4 * b
    # C: tek nota lead (E minor pentatonik), 16'lik / 8'lik, 8 olcu
    lead = [64, 67, 69, 71, 69, 67, 64, 62, 64, 67, 69, 72, 71, 69, 67, 69,
            76, 74, 71, 69, 71, 69, 67, 64, 62, 64, 67, 64, 62, 59, 57, 59]
    for bar in range(8):
        seq = lead[(bar % 2) * 16:(bar % 2) * 16 + 16]
        if bar % 4 == 3:          # olcu sonu: 8'lik + uzun nota
            for k in range(6):
                ev.append((t + k * b / 2, [seq[k]], b / 2 * 0.95, "lead"))
            ev.append((t + 3 * b, [seq[6]], b * 0.95, "lead"))
        else:
            for k in range(16):
                ev.append((t + k * b / 4, [seq[k]], b / 4 * 0.95, "lead"))
        t += 4 * b
    silent_start = t
    t += 8 * b                      # D: gitarsiz 2 olcu (davul + bas devam eder)
    silent = [(silent_start, t)]
    # E: chug riff tekrar, 4 olcu
    for bar in range(4):
        for k, (kind, n) in enumerate(pattern):
            notes = [n, n + 7] if kind == "m" else n
            ev.append((t + k * b / 2, notes, b / 2 * 0.9, "mute" if kind == "m" else "chord"))
        t += 4 * b
    return ev, silent, t


def make_mix(seed: int = 1, bpm: float = 120.0) -> RealMix:
    rng = np.random.default_rng(seed)
    start = 2.0
    events, silent, end = riff_events(bpm, start)
    total = int((end + 2.0) * SR)
    gl = _guitar_take(events, total, rng, 0.0015, 0.004)
    gr = _guitar_take(events, total, rng, 0.0015, 0.004)
    guitar = np.stack([gl, gr])
    beats = np.arange(start, end, 60.0 / bpm)
    drums = _drums(beats, total, rng)
    bass_events = [(t, n, d, k) for t, n, d, k in events if k != "lead"]
    bass = _bass(bass_events, total)
    # gitarsiz arada bas yuruyusu
    for s0, s1 in silent:
        bass += _bass([(s0 + k * 60.0 / bpm, [40 + (k % 4) * 2], 60.0 / bpm * 0.9, "b")
                       for k in range(int((s1 - s0) * bpm / 60))], total)
    backing = np.stack([drums * 0.9 + bass * 0.8, drums * 0.9 + bass * 0.8])
    g = 0.5 / max(np.abs(guitar).max(), 1e-9)
    guitar *= g
    mix = guitar + backing
    peak = np.abs(mix).max()
    s = 0.89 / peak
    return RealMix(mix=(mix * s).astype(np.float32), guitar=(guitar * s).astype(np.float32),
                   backing=(backing * s).astype(np.float32), sr=SR, bpm=bpm, events=events, silent=silent)


def write_wav(path: str, x: np.ndarray, sr: int = SR) -> None:
    a = np.asarray(x)
    if a.ndim == 2 and a.shape[0] <= 2:
        a = a.T
    if a.ndim == 1:
        a = a[:, None]
    d = (np.clip(a, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(d.shape[1])
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(d.tobytes())


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "realistic_mix.wav"
    m = make_mix()
    write_wav(out, m.mix)
    write_wav(out.replace(".wav", "_guitar.wav"), m.guitar)
    print(f"wrote {out} ({m.mix.shape[1] / SR:.1f}s, {len(m.events)} guitar events)")
