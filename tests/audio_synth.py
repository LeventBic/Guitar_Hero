"""Testler icin sentetik muzik: bilinen tempoda (veya tempo kaymasiyla) davul izi + bilinen onset'li melodi.

render_song(bpm=128, bars=16, ...) -> SynthSong(samples, sr, beats, drum_onsets, melody)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# olcu basina melodi deseni: (vurus konumu, derece) ; derece -> majör olcek
MOTIFS = [
    [(0.0, 0), (0.5, 2), (1.0, 4), (1.5, 2), (2.0, 5), (3.0, 4), (3.5, 2)],
    [(0.0, 7), (1.0, 5), (1.5, 4), (2.0, 2), (2.5, 4), (3.0, 0)],
    [(0.0, 4), (0.5, 4), (1.0, 5), (2.0, 7), (2.5, 9), (3.0, 7), (3.5, 5)],
    [(0.0, 2), (1.0, 0), (2.0, -1), (3.0, 0)],
]
SCALE = [0, 2, 4, 5, 7, 9, 11]


@dataclass
class SynthSong:
    samples: np.ndarray
    sr: int
    beats: np.ndarray            # gercek vurus zamanlari (s)
    drum_onsets: np.ndarray      # kick + snare zamanlari
    melody: list                 # [(zaman, midi)]

    @property
    def all_onsets(self) -> np.ndarray:
        return np.unique(np.round(np.concatenate([self.drum_onsets, [t for t, _ in self.melody]]), 4))


def _deg_to_midi(deg: int, tonic: int = 64) -> int:
    o, i = divmod(deg, 7)
    return tonic + 12 * o + SCALE[i]


def _kick(sr):
    n = int(0.18 * sr)
    t = np.arange(n) / sr
    f = 50 + 90 * np.exp(-t * 35)
    return np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t * 18) * _fade(n)


def _fade(n: int) -> np.ndarray:
    """Ornek sonunda tiklama olmasin diye kosinus kapanis (son %30)."""
    k = max(1, int(n * 0.3))
    w = np.ones(n)
    w[-k:] = 0.5 * (1 + np.cos(np.linspace(0, np.pi, k)))
    return w


def _snare(sr, rng):
    n = int(0.16 * sr)
    t = np.arange(n) / sr
    noise = rng.uniform(-1, 1, n)
    noise = np.convolve(noise, [1, -0.6], mode="same")      # hafif parlak
    return (0.7 * noise + 0.4 * np.sin(2 * np.pi * 190 * t)) * np.exp(-t * 28) * _fade(n)


def _tone(midi, dur, sr):
    n = int(dur * sr)
    t = np.arange(n) / sr
    f0 = 440.0 * 2 ** ((midi - 69) / 12)
    sig = sum(np.sin(2 * np.pi * f0 * h * t) / h for h in range(1, 7))
    env = np.minimum(1.0, t / 0.004) * np.exp(-t * 3.0)
    rel = np.minimum(1.0, (dur - t) / 0.012)
    return sig * env * np.clip(rel, 0, 1)


def beat_times(bpm: float, n_beats: int, start: float = 2.0, end_bpm: float | None = None) -> np.ndarray:
    if end_bpm is None:
        return start + np.arange(n_beats) * 60.0 / bpm
    out = [start]
    for k in range(1, n_beats):
        b = bpm + (end_bpm - bpm) * (k - 1) / max(n_beats - 2, 1)
        out.append(out[-1] + 60.0 / b)
    return np.asarray(out)


def render_song(bpm: float = 128.0, bars: int = 16, sr: int = 22050, *, end_bpm: float | None = None,
                start: float = 2.0, seed: int = 3, tail: float = 2.0) -> SynthSong:
    rng = np.random.default_rng(seed)
    beats = beat_times(bpm, bars * 4 + 1, start, end_bpm)
    total = int((beats[-1] + tail) * sr)
    out = np.zeros(total)
    kick, snare = _kick(sr), _snare(sr, rng)
    drums = []

    def add(sig, t, gain):
        i = int(round(t * sr))
        seg = sig[: max(0, min(sig.size, total - i))]
        out[i:i + seg.size] += gain * seg

    for k in range(bars * 4):
        if k % 2 == 0:
            add(kick, beats[k], 0.9)
        else:
            add(snare, beats[k], 0.45)
        drums.append(beats[k])
    melody = []
    events = []
    for b in range(bars):
        motif = MOTIFS[b % len(MOTIFS)]
        shift = 0 if (b // 4) % 2 == 0 else 2
        for pos, deg in motif:
            k = b * 4 + int(pos)
            frac = pos - int(pos)
            t = beats[k] + frac * (beats[k + 1] - beats[k])
            events.append((t, _deg_to_midi(deg + shift)))
    events.sort()
    for i, (t, m) in enumerate(events):
        nxt = events[i + 1][0] if i + 1 < len(events) else t + 1.0
        add(_tone(m, max(0.05, nxt - t), sr), t, 0.28)
        melody.append((t, m))
    out = out / (np.abs(out).max() + 1e-9) * 0.8
    return SynthSong(out.astype(np.float32), sr, beats[:-1], np.asarray(drums), melody)


def write_wav(path: str, song: SynthSong) -> None:
    import wave
    data = (np.clip(song.samples, -1, 1) * 32767).astype(np.int16)
    st = np.repeat(data[:, None], 2, axis=1)
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(song.sr)
        w.writeframes(st.tobytes())
