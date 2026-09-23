"""Demucs v4 htdemucs_6s kaynak ayristirma (onnxruntime + numpy).

Ag (encoder/decoder/cross-transformer) ONNX'te; STFT/iSTFT ve cikti maskesi (cac) numpy'da (gh.ai.spec),
demucs.onnx / demucs.cpp projelerindeki yaklasim. Uzun ses demucs.apply.apply_model(split=True, overlap=0.25,
shifts=0) ile birebir ayni sekilde ~7.8 s'lik parcalara bolunur, ucgen agirlikla overlap-add yapilir.

separate(stereo, ...) -> Stems(guitar, backing, ...) (44.1 kHz, (2, L) float32)
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import numpy as np

from .runtime import DEMUCS_FILE, check_cancel, session
from .spec import cac_magnitude, cac_to_complex, demucs_ispec, demucs_spec

SOURCES = ("drums", "bass", "other", "vocals", "guitar", "piano")
GUITAR = SOURCES.index("guitar")
SR = 44100
SEGMENT = 343980            # int(39/5 s * 44100): htdemucs egitim parca uzunlugu
OVERLAP = 0.25


@dataclass
class Stems:
    guitar: np.ndarray                      # (2, L)
    backing: np.ndarray                     # (2, L) diger 5 kaynagin toplami
    sr: int = SR
    energy: dict = field(default_factory=dict)   # kaynak -> RMS (tum sarki)
    seconds: float = 0.0
    chunks: int = 0


def chunk_weight(n: int = SEGMENT) -> np.ndarray:
    """apply_model ucgen agirligi (transition_power=1)."""
    w = np.concatenate([np.arange(1, n // 2 + 1), np.arange(n - n // 2, 0, -1)]).astype(np.float32)
    return w / w.max()


def chunk_plan(length: int, segment: int = SEGMENT, overlap: float = OVERLAP) -> list[tuple[int, int]]:
    """[(offset, parca uzunlugu)]."""
    stride = int((1 - overlap) * segment)
    return [(o, min(segment, length - o)) for o in range(0, length, stride)]


def padded_chunk(mix: np.ndarray, offset: int, length: int, target: int = SEGMENT) -> np.ndarray:
    """demucs TensorChunk.padded: parcayi ortalayarak (komsu gercek sesle, yoksa sifirla) target'a tamamla."""
    total = mix.shape[-1]
    delta = target - length
    start = offset - delta // 2
    end = start + target
    cs, ce = max(0, start), min(total, end)
    out = np.zeros((mix.shape[0], target), dtype=np.float32)
    out[:, cs - start:cs - start + (ce - cs)] = mix[:, cs:ce]
    return out


def center_trim(x: np.ndarray, length: int) -> np.ndarray:
    delta = x.shape[-1] - length
    if delta:
        x = x[..., delta // 2: x.shape[-1] - (delta - delta // 2)]
    return x


def run_segment(sess, chunk: np.ndarray) -> np.ndarray:
    """(2, SEGMENT) -> (S, 2, SEGMENT): HTDemucs.forward (egitim uzunlugunda)."""
    mix = chunk[None].astype(np.float32)
    z = demucs_spec(mix)                                   # (1, 2, 2048, 336)
    mag = cac_magnitude(z)                                 # (1, 4, 2048, 336)
    x, xt = sess.run(None, {"mix": mix, "mag": mag})
    zout = cac_to_complex(x)                               # (1, S, 2, 2048, 336)
    xs = demucs_ispec(zout, mix.shape[-1])
    return (xt + xs)[0]


def separate(audio: np.ndarray, *, progress=None, cancel=None, threads: int | None = None,
             keep_all: bool = False) -> Stems:
    """audio: (2, L) veya (L, 2) veya (L,) float, 44.1 kHz. Gitar + (diger 5 kaynak toplami)."""
    t0 = time.perf_counter()
    x = np.asarray(audio, dtype=np.float32)
    if x.ndim == 1:
        x = np.stack([x, x])
    elif x.shape[0] != 2 and x.shape[-1] == 2:
        x = x.T
    if x.shape[0] == 1:
        x = np.concatenate([x, x])
    x = np.ascontiguousarray(x[:2])
    L = x.shape[-1]
    ref = x.mean(axis=0)
    mean = float(ref.mean())
    std = float(ref.std(ddof=1)) + 1e-8 if L > 1 else 1.0
    mix = (x - mean) / std
    sess = session(DEMUCS_FILE, threads)
    plan = chunk_plan(L)
    weight = chunk_weight()
    guitar = np.zeros((2, L), dtype=np.float32)
    backing = np.zeros((2, L), dtype=np.float32)
    allsrc = np.zeros((len(SOURCES), 2, L), dtype=np.float32) if keep_all else None
    wsum = np.zeros(L, dtype=np.float32)
    energy = np.zeros(len(SOURCES))
    for k, (off, n) in enumerate(plan):
        check_cancel(cancel)
        out = run_segment(sess, padded_chunk(mix, off, n))
        out = center_trim(out, n)
        w = weight[:n]
        guitar[:, off:off + n] += w * out[GUITAR]
        backing[:, off:off + n] += w * (out.sum(axis=0) - out[GUITAR])
        if allsrc is not None:
            allsrc[:, :, off:off + n] += w * out
        wsum[off:off + n] += w
        if progress is not None:
            progress((k + 1) / len(plan))
    wsum = np.maximum(wsum, 1e-8)
    guitar = guitar / wsum * std + mean
    backing = backing / wsum * std + mean * (len(SOURCES) - 1)
    for i, name in enumerate(SOURCES):
        if allsrc is not None:
            allsrc[i] = allsrc[i] / wsum * std + mean
            energy[i] = float(np.sqrt(np.mean(allsrc[i] ** 2)))
    st = Stems(guitar=guitar, backing=backing, seconds=time.perf_counter() - t0, chunks=len(plan))
    st.energy = {"guitar": float(np.sqrt(np.mean(guitar ** 2))), "backing": float(np.sqrt(np.mean(backing ** 2))),
                 "mix": float(np.sqrt(np.mean(x ** 2)))}
    if allsrc is not None:
        st.energy.update({n: float(e) for n, e in zip(SOURCES, energy)})
        st.all = allsrc  # type: ignore[attr-defined]
    return st


def estimate_seconds(duration_s: float, sec_per_chunk: float = 1.1) -> float:
    """Kaba sure tahmini (ilerleme ekrani icin)."""
    n = math.ceil(duration_s * SR / int((1 - OVERLAP) * SEGMENT))
    return n * sec_per_chunk
