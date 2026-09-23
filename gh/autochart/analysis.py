"""Ses analizi: onset zarfi -> tempo -> vurus izgarasi -> olcu fazi -> onset'ler ve ozellikleri -> bolumler.

analyze(samples, sr, progress=None) -> Analysis
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import dsp
from .dsp import FPS
from .tempo import (BPM_MAX, BPM_MIN, beat_contrast, downbeat_phase, estimate_tempo_candidates,
                    local_period_curve, prior, pulse_scores, refine_beats, track_beats)

# onset zamanlarinin STFT kaynakli sistematik gecikme duzeltmesi (sentetik verilerle olculdu)
ONSET_BIAS = 0.0
# akinin tepe noktasi vurusun ~0-5 ms gerisinde (demo miksleri ~+5, sentetik tikler ~0): ortasi
BEAT_BIAS = 0.0025


@dataclass
class Onset:
    time: float
    strength: float       # 0..1 (yerel olarak normalize)
    raw: float            # ham zarf yuksekligi
    pitch: float = 60.0   # midi
    clarity: float = 0.0  # perdelilik
    bright: float = 0.0   # spektral merkez (Hz)
    sustain: float = 0.0  # enerjinin surdugu sure (s)
    width: float = 0.0    # genis bantli vurgu orani 0..1
    low: float = 0.0      # bas bandi vurgusu (normalize)


@dataclass
class SectionInfo:
    beat: int             # baslangic vurus indeksi (grid'de)
    name: str
    cluster: int = -1
    energy: float = 0.0


@dataclass
class Analysis:
    duration: float
    tempo: float                          # global bpm
    beats: np.ndarray                     # tespit edilen vurus zamanlari (s)
    downbeat: int                         # beats[downbeat] ilk olcu basi (0..3)
    onsets: list[Onset] = field(default_factory=list)
    sections: list[SectionInfo] = field(default_factory=list)   # indeksler `beats` uzerinde
    beat_chroma: np.ndarray | None = None  # (vurus, 12)
    beat_energy: np.ndarray | None = None  # (vurus,) RMS
    tempo_candidates: list = field(default_factory=list)
    timings: dict = field(default_factory=dict)

    @property
    def bar_starts(self) -> np.ndarray:
        return self.beats[self.downbeat::4]


def _progress(cb, frac, text):
    if cb is not None:
        try:
            cb(float(frac), text)
        except Exception:
            pass


def choose_tempo(env: np.ndarray) -> tuple[float, np.ndarray, np.ndarray, list]:
    """En iyi tempo adayini sec (oktav hatasi kontrolu ile). (bpm, periyot egrisi, vurus kareleri, adaylar)."""
    cands = estimate_tempo_candidates(env)
    best = cands[0][0]
    options = [best]
    for k in (0.5, 2.0):
        b = best * k
        if BPM_MIN <= b <= BPM_MAX:
            options.append(b)
    results = []
    for b in options:
        per = 60.0 * FPS / b
        curve = local_period_curve(env, per)
        frames = track_beats(env, curve)
        secs = frames / FPS
        con = beat_contrast(env, secs)
        ps = float(pulse_scores(env, np.array([b]))[0])
        # skor: periyodiklik x oncelik x (vurus - ara konum) farki
        score = max(ps, 1e-6) ** 0.5 * float(prior(b)) * max(con, 1e-6)
        results.append((score, b, curve, frames, con, ps))
    results.sort(key=lambda r: -r[0])
    score, b, curve, frames, con, ps = results[0]
    info = [(round(r[1], 2), round(r[0], 4), round(r[4], 3), round(r[5], 3)) for r in results]
    return b, curve, frames, info


def detect_onsets(bands: dsp.OnsetBands) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Melodi agirlikli zarf uzerinde tepe secimi. (zaman s, guc 0..1, ham)."""
    env = 0.9 * bands.melody / max(np.percentile(bands.melody, 99.5), 1e-9) + \
        0.1 * bands.full / max(np.percentile(bands.full, 99.5), 1e-9)
    env = np.clip(env, 0, 1.5)
    # yerel normalizasyon (~4 s): sessiz bolumlerdeki notalar da yakalanir
    loc = dsp.max_filter1d(env, int(4 * FPS))
    loc = dsp.moving_average(loc, int(2 * FPS))
    norm = env / np.maximum(loc, 0.08)
    peaks = dsp.pick_peaks(norm, pre_max=3, post_max=3, pre_avg=8, post_avg=6, delta=0.07, wait=3)
    times = np.array([(p + dsp.parabolic_offset(norm, int(p))) / FPS for p in peaks]) - ONSET_BIAS
    strength = np.clip(norm[peaks], 0, 1.0) if peaks.size else np.zeros(0)
    return times, strength, env[peaks] if peaks.size else np.zeros(0)


def beat_sync(frames_feat: np.ndarray, fps: float, beats: np.ndarray, duration: float) -> np.ndarray:
    """Vurus araliklarinda ortalama ozellik (vurus, d)."""
    edges = np.concatenate([beats, [beats[-1] + (beats[-1] - beats[-2] if beats.size > 1 else 0.5)]])
    idx = np.clip(np.round(edges * fps).astype(int), 0, frames_feat.shape[0])
    out = np.zeros((beats.size, frames_feat.shape[1]))
    for i in range(beats.size):
        a, b = idx[i], max(idx[i + 1], idx[i] + 1)
        out[i] = frames_feat[a:b].mean(axis=0) if b <= frames_feat.shape[0] and a < b else 0
    return out


def analyze(samples: np.ndarray, sr: int, progress=None) -> Analysis:
    import time as _time
    t0 = _time.perf_counter()
    timings = {}
    _progress(progress, 0.02, "Preparing audio")
    x = dsp.to_mono(samples)
    x = dsp.resample(x, int(sr), dsp.SR)
    peak = float(np.abs(x).max()) if x.size else 0.0
    if peak > 0:
        x = x / peak
    duration = x.size / dsp.SR
    if duration < 5.0:
        raise ValueError("audio is too short (need at least 5 seconds)")
    timings["resample"] = _time.perf_counter() - t0

    _progress(progress, 0.08, "Detecting onsets")
    bands = dsp.onset_bands(x)
    env = dsp.normalize_env(bands.full)
    timings["onset_env"] = _time.perf_counter() - t0

    _progress(progress, 0.2, "Estimating tempo")
    bpm, curve, frames, cand_info = choose_tempo(env)
    timings["tempo"] = _time.perf_counter() - t0

    _progress(progress, 0.35, "Tracking beats")
    beats = refine_beats(frames, env, curve) - BEAT_BIAS
    if beats.size >= 8:
        ibi = np.diff(beats)
        bpm = float(60.0 / np.median(ibi))
    timings["beats"] = _time.perf_counter() - t0

    _progress(progress, 0.45, "Analysing pitch")
    pa = dsp.PitchAnalyzer(x)
    chroma = pa.chroma_frames()
    bchroma = beat_sync(chroma, pa.fps, beats, duration) if beats.size > 1 else np.zeros((beats.size, 12))
    rms_frames = np.sqrt((pa.mag.astype(np.float64) ** 2).mean(axis=1, keepdims=True))
    benergy = beat_sync(rms_frames, pa.fps, beats, duration)[:, 0] if beats.size > 1 else np.zeros(beats.size)
    # akor degisimi (kroma farki) vurus basina
    cc = np.zeros(beats.size)
    if beats.size > 2:
        nc = bchroma / np.maximum(np.linalg.norm(bchroma, axis=1, keepdims=True), 1e-9)
        cc[1:] = 1.0 - (nc[1:] * nc[:-1]).sum(axis=1)
    down = downbeat_phase(beats, bands.low, bands.full, cc)
    timings["pitch_frames"] = _time.perf_counter() - t0

    _progress(progress, 0.55, "Finding notes")
    otimes, ostr, oraw = detect_onsets(bands)
    lowz = bands.low / max(np.percentile(bands.low, 99), 1e-9)
    onsets: list[Onset] = []
    for t, s, r in zip(otimes, ostr, oraw):
        if t < 0 or t > duration - 0.05:
            continue
        f = int(round(t * FPS))
        p, clar = pa.pitch(float(t))
        on = Onset(time=float(t), strength=float(s), raw=float(r), pitch=p, clarity=clar,
                   bright=pa.brightness(float(t)), width=float(bands.width[max(0, min(f, bands.width.size - 1))]),
                   low=float(np.clip(lowz[max(0, f - 2):f + 3].max() if lowz.size else 0, 0, 2)))
        on.sustain = pa.sustain(on.time, on.pitch)
        onsets.append(on)
    timings["onsets"] = _time.perf_counter() - t0

    _progress(progress, 0.7, "Finding song sections")
    from .structure import find_sections
    sections = find_sections(beats, down, bchroma, benergy, bands, pa)
    timings["sections"] = _time.perf_counter() - t0
    return Analysis(duration=duration, tempo=bpm, beats=beats, downbeat=down, onsets=onsets,
                    sections=sections, beat_chroma=bchroma, beat_energy=benergy,
                    tempo_candidates=cand_info, timings=timings)
