"""torch.stft / torch.istft ile ayni sonucu veren numpy STFT ve Demucs'un _spec/_ispec sarmalayicilari.

Kurallar (torch): center=True, pad_mode='reflect', periyodik Hann penceresi, normalized=True (1/sqrt(n_fft)),
onesided. iSTFT: pencereli overlap-add / pencere karesi zarfi, merkez dolgusu kirpilir, `length`e kesilir.
Demucs (htdemucs.py): _spec 1.5 hop reflect dolgu + son frekans kutusu atilir + ilk/son 2 kare kirpilir.
"""
from __future__ import annotations

import math

import numpy as np


def hann(n: int) -> np.ndarray:
    """torch.hann_window(n) (periyodik)."""
    k = np.arange(n, dtype=np.float64)
    return (0.5 - 0.5 * np.cos(2.0 * np.pi * k / n)).astype(np.float32)


def _pad_last(x: np.ndarray, left: int, right: int, mode: str) -> np.ndarray:
    pw = [(0, 0)] * (x.ndim - 1) + [(left, right)]
    return np.pad(x, pw, mode=mode)


def stft(x: np.ndarray, n_fft: int, hop: int) -> np.ndarray:
    """x (..., L) float32 -> (..., n_fft//2+1, kare) complex64."""
    x = np.asarray(x, dtype=np.float32)
    xp = _pad_last(x, n_fft // 2, n_fft // 2, "reflect")
    frames = np.lib.stride_tricks.sliding_window_view(xp, n_fft, axis=-1)[..., ::hop, :]
    win = hann(n_fft)
    z = np.fft.rfft(frames * win, axis=-1)
    z *= np.float32(1.0 / math.sqrt(n_fft))
    return np.swapaxes(z, -1, -2).astype(np.complex64, copy=False)


def istft(z: np.ndarray, hop: int, length: int) -> np.ndarray:
    """z (..., bins, kare) -> (..., length) float32 (torch.istft, center=True, normalized=True)."""
    z = np.asarray(z)
    n_fft = 2 * (z.shape[-2] - 1)
    if n_fft % hop:
        raise ValueError("n_fft must be a multiple of hop")
    r = n_fft // hop
    n_frames = z.shape[-1]
    zz = np.swapaxes(z, -1, -2) * np.float32(math.sqrt(n_fft))
    frames = np.fft.irfft(zz, n=n_fft, axis=-1).astype(np.float32)          # (..., kare, n_fft)
    win = hann(n_fft)
    frames *= win
    lead = frames.shape[:-2]
    seg = frames.reshape(*lead, n_frames, r, hop)
    out = np.zeros((*lead, n_frames + r - 1, hop), dtype=np.float32)
    wsq = (win * win).reshape(r, hop)
    env = np.zeros((n_frames + r - 1, hop), dtype=np.float32)
    for j in range(r):
        out[..., j:j + n_frames, :] += seg[..., :, j, :]
        env[j:j + n_frames, :] += wsq[j]
    y = out.reshape(*lead, -1)
    env = env.reshape(-1)
    start = n_fft // 2
    y = y[..., start:start + length]
    env = env[start:start + length]
    if y.shape[-1] < length:                         # torch: eksik kisim sifir
        y = _pad_last(y, 0, length - y.shape[-1], "constant")
        env = np.pad(env, (0, length - env.size), constant_values=1.0)
    return (y / np.where(env > 1e-11, env, 1.0)).astype(np.float32)


# --------------------------------------------------------------------------- Demucs sarmalayicilari

def demucs_spec(x: np.ndarray, nfft: int = 4096, hop: int = 1024) -> np.ndarray:
    """HTDemucs._spec: x (..., L) -> (..., nfft//2, ceil(L/hop)) complex64."""
    L = x.shape[-1]
    le = int(math.ceil(L / hop))
    pad = hop // 2 * 3
    xp = _pad_last(np.asarray(x, dtype=np.float32), pad, pad + le * hop - L, "reflect")
    z = stft(xp, nfft, hop)[..., :-1, :]
    assert z.shape[-1] == le + 4, (z.shape, le)
    return z[..., 2:2 + le]


def demucs_ispec(z: np.ndarray, length: int, hop: int = 1024) -> np.ndarray:
    """HTDemucs._ispec: (..., nfft//2, T) -> (..., length)."""
    pw = [(0, 0)] * (z.ndim - 2) + [(0, 1), (2, 2)]
    z = np.pad(z, pw)
    pad = hop // 2 * 3
    le = hop * int(math.ceil(length / hop)) + 2 * pad
    x = istft(z, hop, le)
    return x[..., pad:pad + length]


def cac_magnitude(z: np.ndarray) -> np.ndarray:
    """HTDemucs._magnitude (cac=True): (B, C, F, T) complex -> (B, 2C, F, T) [c0.re, c0.im, c1.re, ...]."""
    B, C, F, T = z.shape
    m = np.stack([z.real, z.imag], axis=2)            # (B, C, 2, F, T)
    return m.reshape(B, C * 2, F, T).astype(np.float32)


def cac_to_complex(m: np.ndarray) -> np.ndarray:
    """HTDemucs._mask (cac=True): (B, S, 2C, F, T) -> (B, S, C, F, T) complex64."""
    B, S, C2, F, T = m.shape
    m = m.reshape(B, S, C2 // 2, 2, F, T)
    return (m[:, :, :, 0] + 1j * m[:, :, :, 1]).astype(np.complex64)
