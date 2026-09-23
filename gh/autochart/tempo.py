"""Tempo tahmini, dinamik programlamali vurus (beat) takibi (Ellis 2007 tarzi, yerel tempo egrisiyle)
ve olcu fazi (downbeat) secimi. Yalniz numpy.
"""
from __future__ import annotations

import numpy as np

from .dsp import FPS, moving_average, moving_median

BPM_MIN, BPM_MAX = 70.0, 210.0
PRIOR_CENTER = 120.0     # algisal tempo onceligi (log-normal merkez)
PRIOR_SIGMA = 1.0        # oktav


def autocorr(env: np.ndarray, max_lag: int) -> np.ndarray:
    e = np.asarray(env, dtype=np.float64)
    e = e - e.mean()
    n = 1
    while n < 2 * e.size:
        n *= 2
    f = np.fft.rfft(e, n)
    ac = np.fft.irfft(f * np.conj(f), n)[: max_lag + 1]
    ac /= max(ac[0], 1e-12)
    # yansiz tahmin: uzun gecikmelerde azalan ortusmeyi telafi et
    ac *= e.size / np.maximum(e.size - np.arange(ac.size), 1)
    return ac


def _interp(ac: np.ndarray, lag: np.ndarray) -> np.ndarray:
    return np.interp(lag, np.arange(ac.size), ac, right=0.0)


def pulse_scores(env: np.ndarray, bpms: np.ndarray) -> np.ndarray:
    """Her aday tempo icin periyodiklik skoru: periyodun katlarinda (1..4) otokorelasyon (tepeye tolerans)."""
    periods = 60.0 * FPS / bpms
    max_lag = int(periods.max() * 4.5) + 4
    ac = autocorr(env, max_lag)
    acm = np.maximum.reduce([np.roll(ac, -1), ac, np.roll(ac, 1)])   # +-1 kare tolerans
    s = np.zeros_like(bpms)
    for k, w in ((1, 1.0), (2, 0.7), (3, 0.45), (4, 0.35)):
        s += w * _interp(acm, periods * k)
    return s


def prior(bpm) -> np.ndarray:
    return np.exp(-0.5 * (np.log2(np.asarray(bpm) / PRIOR_CENTER) / PRIOR_SIGMA) ** 2)


def estimate_tempo_candidates(env: np.ndarray) -> list[tuple[float, float]]:
    """[(bpm, skor)] en iyi adaylar (70..210), azalan skor."""
    bpms = np.arange(BPM_MIN, BPM_MAX + 0.001, 0.25)
    sc = pulse_scores(env, bpms) * prior(bpms)
    out = []
    order = np.argsort(-sc)
    for i in order:
        b = bpms[i]
        if all(abs(np.log2(b / o)) > 0.04 for o, _ in out):
            out.append((float(b), float(sc[i])))
        if len(out) >= 6:
            break
    return out


# --------------------------------------------------------------------------- yerel tempo

def local_period_curve(env: np.ndarray, period: float, win_s: float = 8.0, hop_s: float = 1.0,
                       spread: float = 0.30) -> np.ndarray:
    """Kare basina periyot (kare). Pencereli otokorelasyonla [period/(1+spread), period*(1+spread)]
    araliginda en iyi gecikme; buyuk sicramalar medyanla yumusatilir."""
    n = env.size
    win = int(win_s * FPS)
    hop = int(hop_s * FPS)
    if n < win + 4:
        return np.full(n, period)
    lags = np.arange(int(period / (1 + spread)), int(period * (1 + spread)) + 2)
    centers, pers = [], []
    for s in range(0, n - win + 1, hop):
        seg = env[s:s + win]
        if seg.std() <= 1e-9:
            continue
        ac = autocorr(seg, int(lags.max() * 2.2) + 2)
        # birinci ve ikinci kat birlikte (daha keskin)
        sc = ac[lags] + 0.6 * np.interp(2 * lags, np.arange(ac.size), ac)
        sc *= np.exp(-0.5 * (np.log(lags / period) / 0.12) ** 2) * 0.5 + 0.5   # globale yakinlik tercihi
        j = int(np.argmax(sc))
        p = float(lags[j])
        if 0 < j < lags.size - 1:
            a, b, c = sc[j - 1], sc[j], sc[j + 1]
            den = a - 2 * b + c
            if den < 0:
                p += float(np.clip(0.5 * (a - c) / den, -0.5, 0.5))
        centers.append(s + win / 2)
        pers.append(p)
    if len(pers) < 3:
        return np.full(n, period)
    pers = moving_median(np.asarray(pers), 5)
    return np.interp(np.arange(n), np.asarray(centers), pers)


# --------------------------------------------------------------------------- DP vurus takibi

def track_beats(env: np.ndarray, period_curve: np.ndarray, tightness: float = 300.0) -> np.ndarray:
    """Ellis DP: yerel skor = normalize onset; gecis cezasi -tightness*log(dt/P)^2. Vurus kareleri."""
    n = env.size
    e = np.asarray(env, dtype=np.float64)
    sd = e.std()
    e = e / sd if sd > 0 else e
    # hafif yumusatma (P/16 genislikli gauss)
    p0 = float(np.median(period_curve))
    w = max(1, int(p0 / 16))
    g = np.exp(-0.5 * (np.arange(-2 * w, 2 * w + 1) / max(w, 1)) ** 2)
    local = np.convolve(e, g / g.sum(), mode="same")
    score = np.zeros(n)
    back = -np.ones(n, dtype=np.int64)
    for t in range(n):
        P = period_curve[t]
        lo = int(t - round(2.0 * P))
        hi = int(t - round(0.5 * P))
        if hi < 0:
            score[t] = local[t]
            continue
        lo = max(lo, 0)
        taus = np.arange(lo, hi + 1)
        cost = -tightness * np.log((t - taus) / P) ** 2
        cand = score[taus] + cost
        j = int(np.argmax(cand))
        if cand[j] > 0:
            score[t] = local[t] + cand[j]
            back[t] = taus[j]
        else:
            score[t] = local[t]
    # son vurus: son periyottaki en yuksek skor (librosa gibi yerel maksimumlar arasindan)
    tail = int(round(period_curve[-1]))
    start = max(0, n - 2 * tail)
    seg = score[start:]
    # kuvvetli skorlar icinde en sondakini tercih et
    thr = 0.5 * np.median(score[max(0, n - 20 * tail):]) if n > tail else 0
    cands = [i for i in range(seg.size) if seg[i] >= thr and (i == 0 or seg[i] >= seg[i - 1])
             and (i == seg.size - 1 or seg[i] >= seg[i + 1])]
    last = start + (max(cands, key=lambda i: seg[i]) if cands else int(np.argmax(seg)))
    beats = [last]
    while back[beats[-1]] >= 0:
        beats.append(int(back[beats[-1]]))
    beats = np.asarray(beats[::-1], dtype=np.int64)
    # bastaki / sondaki zayif (sessiz) vuruslari at
    if beats.size > 4:
        strength = local[beats]
        thr = 0.5 * np.sqrt(np.mean(strength ** 2))
        ok = np.nonzero(strength >= thr)[0]
        if ok.size:
            beats = beats[ok[0]: ok[-1] + 1]
    return beats


def refine_beats(beat_frames: np.ndarray, env: np.ndarray, period_curve: np.ndarray) -> np.ndarray:
    """Kare -> saniye; her vurus +-P/8 icindeki onset agirlik merkezine hafifce cekilir, sonra yerel
    dogrusal regresyonla (+-4 vurus) duzgunlestirilir. Sabit tempolu parcalarda global dogruya oturtur."""
    b = beat_frames.astype(np.float64)
    if b.size < 3:
        return b / FPS
    e = np.asarray(env, dtype=np.float64)
    ref = b.copy()
    for i, f in enumerate(beat_frames):
        r = max(1, int(period_curve[min(int(f), period_curve.size - 1)] / 8))
        lo, hi = max(0, f - r), min(e.size, f + r + 1)
        seg = e[lo:hi]
        if seg.sum() > 1e-9 and seg.max() > 0.5 * max(e[max(0, f - 4 * r):f + 4 * r + 1].max(), 1e-9):
            k = int(np.argmax(seg))
            # tepe konumu (parabolik)
            pk = lo + k
            if 0 < pk < e.size - 1:
                a, c0, d = e[pk - 1], e[pk], e[pk + 1]
                den = a - 2 * c0 + d
                off = 0.5 * (a - d) / den if den < 0 else 0.0
                ref[i] = pk + float(np.clip(off, -0.5, 0.5))
    t = ref / FPS
    idx = np.arange(t.size, dtype=np.float64)
    # global dogru uygun mu? (sabit tempo)
    A = np.vstack([idx, np.ones_like(idx)]).T
    coef, *_ = np.linalg.lstsq(A, t, rcond=None)
    fit = A @ coef
    res = t - fit
    if np.sqrt(np.mean(res ** 2)) < 0.012 and np.abs(res).max() < 0.05:
        # sabit tempo: aykirilari cikarip yeniden oturt
        ok = np.abs(res) < 0.025
        coef, *_ = np.linalg.lstsq(A[ok], t[ok], rcond=None)
        return A @ coef
    # degisken tempo: yerel dogrusal regresyon (agirlikli, aykiri dayanikli)
    out = np.empty_like(t)
    K = 4
    for i in range(t.size):
        lo, hi = max(0, i - K), min(t.size, i + K + 1)
        x = idx[lo:hi]
        y = t[lo:hi]
        w = np.exp(-0.5 * ((x - i) / 2.5) ** 2)
        for _ in range(2):
            Aw = np.vstack([x - i, np.ones_like(x)]).T * w[:, None]
            c, *_ = np.linalg.lstsq(Aw, y * w, rcond=None)
            r = y - (c[0] * (x - i) + c[1])
            w = w * (np.abs(r) < 0.03)
            if w.sum() < 2:
                w = np.exp(-0.5 * ((x - i) / 2.5) ** 2)
                break
        out[i] = c[1]
    # monotonluk
    for i in range(1, out.size):
        if out[i] <= out[i - 1] + 0.1:
            out[i] = out[i - 1] + max(0.1, t[i] - t[i - 1])
    return out


def beat_contrast(env: np.ndarray, beats_s: np.ndarray) -> float:
    """(vurus anlarindaki ortalama onset gucu - vurus ici 16'lik konumlarin ortalamasi) / genel ortalama.
    Oktav secimi icin: yanlis (yarim/cift) tempoda bu fark kuculur."""
    if beats_s.size < 4:
        return 0.0
    e = np.asarray(env, dtype=np.float64)
    mx = np.maximum.reduce([np.roll(e, k) for k in (-2, -1, 0, 1, 2)])

    def at(ts):
        return mx[np.clip(np.round(ts * FPS).astype(int), 0, e.size - 1)]

    on = at(beats_s).mean()
    a, b = beats_s[:-1], beats_s[1:]
    off = np.mean([at(a + (b - a) * q).mean() for q in (0.25, 0.5, 0.75)])
    return float((on - off) / (mx.mean() + 1e-9))


# --------------------------------------------------------------------------- olcu fazi

def downbeat_phase(beats_s: np.ndarray, low_env: np.ndarray, full_env: np.ndarray,
                   chroma_change: np.ndarray, beats_per_bar: int = 4) -> int:
    """Hangi vurus indeksinin (mod 4) olcu basi oldugu: bas davul/bas enerjisi + akor degisimi."""
    if beats_s.size < beats_per_bar * 2:
        return 0
    fr = np.clip(np.round(beats_s * FPS).astype(int), 0, low_env.size - 1)

    def z(a):
        a = np.asarray(a, dtype=np.float64)
        s = a.std()
        return (a - a.mean()) / s if s > 0 else a * 0

    mxl = np.maximum.reduce([np.roll(low_env, k) for k in (-2, -1, 0, 1, 2)])
    mxf = np.maximum.reduce([np.roll(full_env, k) for k in (-2, -1, 0, 1, 2)])
    feat = 1.0 * z(mxl[fr]) + 0.5 * z(mxf[fr]) + 1.2 * z(chroma_change)
    scores = [feat[p::beats_per_bar].mean() - feat.mean() for p in range(beats_per_bar)]
    return int(np.argmax(scores))


def smooth(a: np.ndarray, size: int) -> np.ndarray:
    return moving_average(np.asarray(a, dtype=np.float64), size)
