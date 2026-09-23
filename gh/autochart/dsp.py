"""Sinyal isleme temelleri (yalniz numpy): yeniden ornekleme, STFT, log-frekans filtre bankasi,
cok bantli spektral aki (onset zarfi), tepe secimi, harmonik toplam perde tahmini, kroma.

Tum fonksiyonlar deterministiktir (rastgelelik yok) ve float32 ile bellek dostu calisir.
"""
from __future__ import annotations

import numpy as np

SR = 22050            # analiz ornekleme hizi
HOP = 256             # onset STFT adimi (11.6 ms)
N_FFT = 1024          # onset STFT penceresi (46 ms)
P_HOP = 256             # perde STFT adimi (11.6 ms)
P_FFT = 2048            # perde STFT penceresi (93 ms, 10.8 Hz cozunurluk)
FPS = SR / HOP        # onset kare hizi (~86.13)


# --------------------------------------------------------------------------- yeniden ornekleme

def _lowpass_fir(cutoff: float, taps: int = 63) -> np.ndarray:
    """cutoff: Nyquist'e gore normalize (0..1). Blackman pencereli sinc."""
    n = np.arange(taps) - (taps - 1) / 2.0
    h = cutoff * np.sinc(cutoff * n) * np.blackman(taps)
    return (h / h.sum()).astype(np.float32)


def to_mono(samples: np.ndarray) -> np.ndarray:
    x = np.asarray(samples)
    if x.ndim == 2:
        # (n, kanal) veya (kanal, n)
        if x.shape[0] < x.shape[1] and x.shape[0] <= 8:
            x = x.T
        x = x.astype(np.float32).mean(axis=1)
    x = x.astype(np.float32, copy=False)
    if np.issubdtype(np.asarray(samples).dtype, np.integer):
        info = np.iinfo(np.asarray(samples).dtype)
        x = x / float(max(abs(info.min), info.max))
    return x


def resample(x: np.ndarray, sr: int, target: int = SR) -> np.ndarray:
    """Analiz icin yeterli kalitede yeniden ornekleme (alcak geciren FIR + dogrusal interpolasyon)."""
    x = np.asarray(x, dtype=np.float32)
    if sr == target or x.size == 0:
        return x.copy()
    if sr == 2 * target:
        y = np.convolve(x, _lowpass_fir(0.45), mode="same")
        return y[::2].astype(np.float32)
    if sr > target:
        x = np.convolve(x, _lowpass_fir(0.9 * target / sr), mode="same").astype(np.float32)
    n_out = int(round(x.size * target / sr))
    t = np.arange(n_out, dtype=np.float64) * (sr / target)
    return np.interp(t, np.arange(x.size), x).astype(np.float32)


# --------------------------------------------------------------------------- STFT

def stft_mag(x: np.ndarray, n_fft: int, hop: int, chunk: int = 2048, max_bin: int | None = None) -> np.ndarray:
    """Merkezli (kare k zamani = k*hop/sr) Hann pencereli STFT genligi, (kare, bin) float32.
    max_bin: yalniz ilk max_bin frekans kutusu saklanir (uzun sarkilarda bellek)."""
    pad = n_fft // 2
    xp = np.pad(np.asarray(x, dtype=np.float32), (pad, pad))
    n_frames = 1 + max(0, (xp.size - n_fft) // hop)
    win = np.hanning(n_fft).astype(np.float32)
    nb = n_fft // 2 + 1 if max_bin is None else min(max_bin, n_fft // 2 + 1)
    out = np.empty((n_frames, nb), dtype=np.float32)
    frames = np.lib.stride_tricks.sliding_window_view(xp, n_fft)[::hop]
    for s in range(0, n_frames, chunk):
        blk = frames[s:s + chunk] * win
        out[s:s + chunk] = np.abs(np.fft.rfft(blk, axis=1)[:, :nb]).astype(np.float32)
    return out


def log_filterbank(n_fft: int, sr: int = SR, fmin: float = 30.0, fmax: float = 11000.0,
                   bands_per_octave: int = 6) -> tuple[np.ndarray, np.ndarray]:
    """Ucgen log-frekans filtre bankasi. (bin, bant) matris ve bant merkez frekanslari."""
    n_oct = np.log2(fmax / fmin)
    n_bands = int(np.floor(n_oct * bands_per_octave))
    centers = fmin * 2.0 ** (np.arange(n_bands + 2) / bands_per_octave)
    freqs = np.arange(n_fft // 2 + 1) * sr / n_fft
    fb = np.zeros((freqs.size, n_bands), dtype=np.float32)
    for b in range(n_bands):
        lo, c, hi = centers[b], centers[b + 1], centers[b + 2]
        up = (freqs - lo) / max(c - lo, 1e-9)
        down = (hi - freqs) / max(hi - c, 1e-9)
        tri = np.maximum(0.0, np.minimum(up, down))
        if tri.sum() <= 0:            # dar bant (dusuk frekans): en yakin bin
            tri[np.argmin(np.abs(freqs - c))] = 1.0
        fb[:, b] = tri / tri.sum()
    return fb, centers[1:-1]


def max_filter1d(a: np.ndarray, size: int, axis: int = -1) -> np.ndarray:
    """Kayan maksimum (merkezli, kenarlar kirpilir)."""
    if size <= 1:
        return a
    a = np.moveaxis(a, axis, -1)
    r = size // 2
    pad = np.pad(a, [(0, 0)] * (a.ndim - 1) + [(r, size - 1 - r)], mode="edge")
    out = np.lib.stride_tricks.sliding_window_view(pad, size, axis=-1).max(axis=-1)
    return np.moveaxis(out, -1, axis)


def moving_average(a: np.ndarray, size: int) -> np.ndarray:
    size = max(1, int(size))
    if size == 1:
        return a.astype(np.float64)
    k = np.ones(size) / size
    r = size // 2
    pad = np.pad(a.astype(np.float64), (r, size - 1 - r), mode="edge")
    return np.convolve(pad, k, mode="valid")


def moving_median(a: np.ndarray, size: int) -> np.ndarray:
    size = max(1, int(size) | 1)
    r = size // 2
    pad = np.pad(np.asarray(a, dtype=np.float64), (r, r), mode="edge")
    return np.median(np.lib.stride_tricks.sliding_window_view(pad, size), axis=-1)


# --------------------------------------------------------------------------- onset zarfi

class OnsetBands:
    """Onset STFT'sinden cikan bant zarflari (kare hizi FPS)."""

    def __init__(self, full, low, mid, high, melody, width, logspec, centers):
        self.full = full          # tum bantlar
        self.low = low            # < 150 Hz (kick, bas)
        self.mid = mid            # 150 - 2000 Hz
        self.high = high          # > 5 kHz (zil, hi-hat)
        self.melody = melody      # 250 - 5000 Hz (melodi / gitar)
        self.width = width        # anlik akinin yayildigi bant orani (genis bantli vurgu)
        self.logspec = logspec    # (kare, bant) log genlik
        self.centers = centers


def onset_bands(x: np.ndarray) -> OnsetBands:
    mag = stft_mag(x, N_FFT, HOP)
    fb, centers = log_filterbank(N_FFT)
    spec = mag @ fb
    logspec = np.log1p(100.0 * spec).astype(np.float32)
    # SuperFlux: frekans ekseninde max filtre + 2 kare gecikmeli fark (vibratoya dayanikli)
    ref = max_filter1d(logspec, 3, axis=1)
    lag = 2
    diff = np.zeros_like(logspec)
    diff[lag:] = logspec[lag:] - ref[:-lag]
    np.maximum(diff, 0.0, out=diff)

    def band(lo, hi):
        sel = (centers >= lo) & (centers < hi)
        return diff[:, sel].sum(axis=1) if sel.any() else np.zeros(diff.shape[0], np.float32)

    full = diff.sum(axis=1)
    low = band(0, 150)
    mid = band(150, 2000)
    high = band(5000, 1e9)
    melody = band(250, 5000)
    thr = 0.15 * np.maximum(diff.max(axis=1, keepdims=True), 1e-6)
    width = (diff > np.maximum(thr, 0.05)).mean(axis=1)
    return OnsetBands(full, low, mid, high, melody, width.astype(np.float32), logspec, centers)


def normalize_env(env: np.ndarray, win_s: float = 8.0) -> np.ndarray:
    """Yerel ortalama cikar, pozitif kismi al, global std ile olcekle."""
    e = np.asarray(env, dtype=np.float64)
    loc = moving_average(e, int(win_s * FPS / 8))   # ~1 s yerel ortalama
    e = np.maximum(0.0, e - loc)
    s = e.std()
    return e / s if s > 0 else e


# --------------------------------------------------------------------------- tepe secimi

def pick_peaks(env: np.ndarray, *, pre_max: int = 3, post_max: int = 3, pre_avg: int = 10,
               post_avg: int = 7, delta: float = 0.07, wait: int = 4) -> np.ndarray:
    """librosa/madmom tarzi uyarlamali tepe secimi. env [0,1]'e normalize edilmis olmali."""
    e = np.asarray(env, dtype=np.float64)
    n = e.size
    if n == 0:
        return np.zeros(0, dtype=np.int64)
    mx = max_filter1d(np.pad(e, (pre_max, post_max), mode="edge"), pre_max + post_max + 1)[pre_max:pre_max + n]
    csum = np.concatenate([[0.0], np.cumsum(e)])
    idx = np.arange(n)
    lo = np.clip(idx - pre_avg, 0, n)
    hi = np.clip(idx + post_avg + 1, 0, n)
    avg = (csum[hi] - csum[lo]) / np.maximum(hi - lo, 1)
    cand = np.nonzero((e >= mx) & (e >= avg + delta) & (e > 0))[0]
    out = []
    last = -10 ** 9
    for i in cand:
        if i - last > wait:
            out.append(i)
            last = i
        elif e[i] > e[last]:      # ayni bekleme araliginda daha guclu tepe
            out[-1] = i
            last = i
    return np.asarray(out, dtype=np.int64)


def parabolic_offset(y: np.ndarray, i: int) -> float:
    """Tepe i etrafinda parabolik kesirli kaydirma (-0.5..0.5)."""
    if i <= 0 or i >= y.size - 1:
        return 0.0
    a, b, c = y[i - 1], y[i], y[i + 1]
    den = a - 2 * b + c
    if den >= 0:
        return 0.0
    return float(np.clip(0.5 * (a - c) / den, -0.5, 0.5))


# --------------------------------------------------------------------------- perde / kroma

MIDI_LO, MIDI_HI = 40, 88          # E2 .. E6 aday temel frekanslar
PITCH_STEP = 1.0 / 3.0             # yari ton / 3


def midi_to_hz(m):
    return 440.0 * 2.0 ** ((np.asarray(m) - 69.0) / 12.0)


class PitchAnalyzer:
    """Uzun pencereli STFT uzerinden onset basina 'yeni enerji' spektrumu ve harmonik toplam perde."""

    def __init__(self, x: np.ndarray):
        max_bin = int(6000.0 / (SR / P_FFT)) + 2               # perde/kroma icin 6 kHz yeter (bellek: yarisi)
        self.mag = stft_mag(x, P_FFT, P_HOP, max_bin=max_bin)  # (kare, ~559)
        self.fps = SR / P_HOP
        self.freqs = np.arange(self.mag.shape[1]) * SR / P_FFT
        self.cands = np.arange(MIDI_LO, MIDI_HI + 1e-9, PITCH_STEP)
        f0 = midi_to_hz(self.cands)
        nh = 6
        # harmonik toplam agirlik matrisi (bin, aday): her harmonik icin dogrusal interpolasyon
        W = np.zeros((self.freqs.size, self.cands.size), dtype=np.float32)
        binw = SR / P_FFT
        for h in range(1, nh + 1):
            fh = f0 * h
            ok = fh < min(5500.0, SR / 2 - binw)
            pos = fh / binw
            i0 = np.floor(pos).astype(int)
            fr = pos - i0
            w = 0.84 ** (h - 1)
            cols = np.nonzero(ok)[0]
            W[i0[cols], cols] += (w * (1 - fr[cols])).astype(np.float32)
            W[i0[cols] + 1, cols] += (w * fr[cols]).astype(np.float32)
        self.W = W
        # melodi bandi agirligi: < 180 Hz (bas) ve > 5 kHz bastir
        f = self.freqs
        self.band_w = (np.clip((f - 120.0) / 120.0, 0, 1) * np.clip((6000.0 - f) / 2000.0, 0, 1)).astype(np.float32)
        # kroma matrisi (bin -> 12 perde sinifi), 55 Hz .. 5 kHz
        C = np.zeros((self.freqs.size, 12), dtype=np.float32)
        valid = (f >= 55) & (f <= 5000)
        pc = np.mod(np.round(12 * np.log2(np.maximum(f, 1e-9) / 440.0) + 69), 12).astype(int)
        C[np.nonzero(valid)[0], pc[valid]] = 1.0
        self.C = C

    def frame_of(self, t: float) -> int:
        return int(np.clip(round(t * self.fps), 0, self.mag.shape[0] - 1))

    def new_energy(self, t: float) -> np.ndarray:
        """Onset'ten sonraki pencere - onceki pencere (pozitif kisim): yeni baslayan sesin spektrumu."""
        half = P_FFT / 2 / SR
        post = self.mag[self.frame_of(t + half * 0.85)]
        pre = self.mag[self.frame_of(t - half * 1.05)]
        return np.maximum(0.0, post - pre)

    def salience(self, spec: np.ndarray) -> np.ndarray:
        s = spec * self.band_w
        # hafif beyazlatma: genis bantli (davul) enerjiyi bastir
        loc = np.convolve(s, np.ones(31) / 31, mode="same")
        s = np.maximum(0.0, s - 0.9 * loc)
        return s @ self.W

    def pitch(self, t: float) -> tuple[float, float]:
        """(midi perde, perdelilik 0..1)."""
        sal = self.salience(self.new_energy(t))
        if not np.isfinite(sal).all() or sal.max() <= 0:
            sal = self.salience(self.mag[self.frame_of(t + 0.09)])
        if sal.max() <= 0:
            return 60.0, 0.0
        # yuksek perdelere hafif tercih (melodi genelde ustte)
        sal = sal * (1.0 + 0.004 * (self.cands - MIDI_LO))
        i = int(np.argmax(sal))
        # perdelilik: tepe, en iyi 'baska perde' (oktav/beşli disinda) adayina gore ne kadar baskin
        d = np.abs(self.cands - self.cands[i])
        far = (np.abs(d - 12) > 0.7) & (np.abs(d - 7) > 0.7) & (np.abs(d - 19) > 0.7) & (d > 0.7)
        second = float(sal[far].max()) if far.any() else 0.0
        clarity = 1.0 - second / (float(sal[i]) + 1e-9)
        return float(self.cands[i]), float(np.clip(clarity, 0.0, 1.0))

    def sustain(self, t: float, midi: float, max_s: float = 4.0) -> float:
        """Perdenin (ve 2-3. harmoniklerin) enerjisinin tepe degerinin %30'u ustunde kaldigi sure (s)."""
        f0 = float(midi_to_hz(midi))
        binw = SR / P_FFT
        bins = []
        for h in (1, 2, 3):
            b = int(round(f0 * h / binw))
            if 1 <= b < self.mag.shape[1] - 1:
                bins += [b - 1, b, b + 1]
        if not bins:
            return 0.0
        i0 = self.frame_of(t + 0.04)
        i1 = min(self.mag.shape[0], i0 + int(max_s * self.fps) + 1)
        e = self.mag[i0:i1][:, bins].sum(axis=1)
        if e.size < 2:
            return 0.0
        pk = e[: max(2, int(0.15 * self.fps))].max()
        if pk <= 0:
            return 0.0
        below = np.nonzero(e < 0.3 * pk)[0]
        n = below[0] if below.size else e.size
        return n / self.fps

    def chroma_frames(self) -> np.ndarray:
        c = (self.mag ** 2) @ self.C
        c = np.sqrt(c)
        return c / np.maximum(c.max(axis=1, keepdims=True), 1e-9)

    def brightness(self, t: float) -> float:
        m = self.mag[self.frame_of(t + 0.05)]
        s = m.sum()
        return float((m * self.freqs).sum() / s) if s > 0 else 0.0
