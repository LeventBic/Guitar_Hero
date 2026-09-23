"""Sarki yapisi: olcu tabanli kroma/tini oz-benzerlik matrisi, Foote yenilik egrisi ile bolum sinirlari,
tekrar eden bolumlerin kumelenmesi ve sezgisel adlandirma (Intro / Verse / Chorus / Bridge / Outro)."""
from __future__ import annotations

import numpy as np

from .dsp import FPS


def _bar_features(beats, down, bchroma, benergy, bands) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[int]]:
    """Olcu basina (kroma 12, tini 12, enerji) ve olcu baslangic vurus indeksleri."""
    starts = list(range(down, beats.size - 3, 4))
    if not starts:
        return np.zeros((0, 12)), np.zeros((0, 12)), np.zeros(0), []
    # tini: log bant spektrumunun DCT'si (MFCC benzeri), olcu ortalamasi
    ls = bands.logspec
    nb = ls.shape[1]
    k = np.arange(nb)
    dct = np.cos(np.pi / nb * (k[None, :] + 0.5) * np.arange(1, 13)[:, None])   # (12, nb)
    chroma, timbre, energy = [], [], []
    envs = [bands.low, bands.mid, bands.high, bands.melody]
    scales = [max(float(np.percentile(e, 99)), 1e-9) for e in envs]
    for s in starts:
        e = min(s + 4, beats.size - 1)
        chroma.append(bchroma[s:e].mean(axis=0))
        a = int(beats[s] * FPS)
        b = int(beats[e] * FPS) if e < beats.size else ls.shape[0]
        seg = ls[a:max(b, a + 1)]
        tim = dct @ seg.mean(axis=0) if seg.size else np.zeros(12)
        # ritim dokusu: bant basina onset yogunlugu ve 8'lik/16'lik konum enerjisi
        dens = [float(env[a:max(b, a + 1)].mean() / sc) for env, sc in zip(envs, scales)]
        timbre.append(np.concatenate([tim, 4.0 * np.asarray(dens)]))
        # yogunluk: ortalama log genlik (ses yuksekligi) + onset yogunlugu
        energy.append(float(seg.mean()) + 0.5 * float(np.mean(dens)) if seg.size else 0.0)
    return np.asarray(chroma), np.asarray(timbre), np.asarray(energy), starts


def _unit(a):
    a = np.asarray(a, dtype=np.float64)
    return a / np.maximum(np.linalg.norm(a, axis=1, keepdims=True), 1e-9)


def _novelty(S: np.ndarray, L: int = 4) -> np.ndarray:
    n = S.shape[0]
    x = np.arange(-L, L)
    sign = np.sign(x + 0.5)
    K = np.outer(sign, sign) * np.exp(-0.5 * (np.add.outer(x + 0.5, x + 0.5) ** 2 + 0) / (L ** 2) * 0.5)
    nov = np.zeros(n)
    for i in range(2, n - 1):
        lo, hi = max(0, i - L), min(n, i + L)
        k = K[L - (i - lo):L + (hi - i), L - (i - lo):L + (hi - i)]
        blk = S[lo:hi, lo:hi]
        nov[i] = (blk * k).sum() / np.abs(k).sum() * (2 * L) ** 2 / 16
    nov = np.maximum(nov, 0)
    return nov / nov.max() if nov.max() > 0 else nov


def segment_bars(feat: np.ndarray, n_bars: int, energy: np.ndarray) -> list[int]:
    """Olcu indekslerinde bolum sinirlari (0 dahil)."""
    if n_bars < 12:
        return list(range(0, n_bars, 8)) or [0]
    S = feat @ feat.T
    nov = _novelty(S, 4)
    # enerji sicramalari da sinir isaretidir
    le = np.log(np.maximum(energy, 1e-9))
    ej = np.zeros(n_bars)
    ej[1:] = np.abs(np.diff(le))
    ej = ej / ej.max() if ej.max() > 0 else ej
    score = 0.75 * nov + 0.25 * ej
    bounds = [0]
    cand = [i for i in range(2, n_bars - 1) if score[i] >= score[i - 1] and score[i] >= score[i + 1]
            and score[i] > 0.25]
    # 4'un katlarina yakin sinirlari tercih et
    cand.sort(key=lambda i: -(score[i] + (0.12 if i % 4 == 0 else 0.0)))
    chosen = []
    for i in cand:
        if all(abs(i - j) >= 4 for j in chosen + [0, n_bars]):
            chosen.append(i)
    bounds += sorted(chosen)
    # cok uzun bolumleri 8 olcude bol
    out = []
    ext = bounds + [n_bars]
    for a, b in zip(ext[:-1], ext[1:]):
        out.append(a)
        L = b - a
        if L > 16:
            parts = int(round(L / 8))
            for p in range(1, parts):
                out.append(a + int(round(p * L / parts)))
    return sorted(set(out))


def cluster_sections(bounds: list[int], n_bars: int, cfeat: np.ndarray, tfeat: np.ndarray) -> list[int]:
    """Bolumleri benzerlige gore kumele (olcu olcu hizalanmis kroma+tini). Kume id listesi."""
    segs = list(zip(bounds, bounds[1:] + [n_bars]))
    labels = [-1] * len(segs)
    nxt = 0
    for i, (a, b) in enumerate(segs):
        best, bj = 0.0, -1
        for j in range(i):
            c, d = segs[j]
            L = min(b - a, d - c)
            if L < 2:
                continue
            simc = (cfeat[a:a + L] * cfeat[c:c + L]).sum(axis=1).mean()
            simt = (tfeat[a:a + L] * tfeat[c:c + L]).sum(axis=1).mean()
            lenpen = min(b - a, d - c) / max(b - a, d - c)
            sim = (0.65 * simc + 0.35 * simt) * (0.85 + 0.15 * lenpen)
            if sim > best:
                best, bj = sim, j
        if bj >= 0 and best > 0.93:
            labels[i] = labels[bj]
        else:
            labels[i] = nxt
            nxt += 1
    return labels


def name_sections(labels: list[int], energies: list[float]) -> list[str]:
    n = len(labels)
    if n == 0:
        return []
    counts: dict[int, int] = {}
    for l in labels:
        counts[l] = counts.get(l, 0) + 1
    cl_energy: dict[int, list[float]] = {}
    for l, e in zip(labels, energies):
        cl_energy.setdefault(l, []).append(e)
    mean_e = {l: float(np.mean(v)) for l, v in cl_energy.items()}
    med = float(np.median(energies))
    repeated = [l for l, c in counts.items() if c >= 2]
    names_for: dict[int, str] = {}
    if repeated:
        chorus = max(repeated, key=lambda l: (mean_e[l], counts[l]))
        names_for[chorus] = "Chorus"
        rest = [l for l in repeated if l != chorus]
        if rest:
            verse = max(rest, key=lambda l: (counts[l], -abs(mean_e[l] - med)))
            names_for[verse] = "Verse"
            # koru hep onceleyen kume -> Pre-Chorus
            for l in rest:
                if l == verse:
                    continue
                pos = [i for i, x in enumerate(labels) if x == l]
                if pos and all(i + 1 < n and labels[i + 1] == chorus for i in pos):
                    names_for[l] = "Pre-Chorus"
    out = []
    seen: dict[str, int] = {}
    generic = 0
    for i, (l, e) in enumerate(zip(labels, energies)):
        base = names_for.get(l)
        if base is None:
            if i == 0 and (e <= med or n > 2):
                base = "Intro"
            elif i == n - 1 and n > 2:
                base = "Outro"
            elif counts[l] == 1 and e > med:
                base = "Bridge"
            else:
                generic += 1
                base = f"Section {generic}"
                out.append(base)
                continue
        if base in ("Intro", "Outro", "Pre-Chorus", "Bridge"):
            seen[base] = seen.get(base, 0) + 1
            out.append(base if seen[base] == 1 else f"{base} {seen[base]}")
        else:
            seen[base] = seen.get(base, 0) + 1
            out.append(f"{base} {seen[base]}")
    return out


def find_sections(beats, down, bchroma, benergy, bands, pa):
    from .analysis import SectionInfo
    cf, tf, en, starts = _bar_features(beats, down, bchroma, benergy, bands)
    n_bars = len(starts)
    if n_bars == 0:
        return [SectionInfo(beat=down, name="Section 1", cluster=0)]
    cfu = _unit(cf)
    tfz = (tf - tf.mean(axis=0)) / np.maximum(tf.std(axis=0), 1e-6)
    tfu = _unit(tfz)
    # akorlar olcu olcu degistigi icin kroma 2 olculuk ortalamayla (ilerleyisin 'rengi') katilir
    c2 = cf.copy()
    c2[:-1] = (cf[:-1] + cf[1:]) / 2
    feat = _unit(np.hstack([_unit(c2 - c2.mean(axis=0)) * 0.5, tfu * 1.0]))
    try:
        bounds = segment_bars(feat, n_bars, en)
    except Exception:
        bounds = list(range(0, n_bars, 8))
    # tini benzerligi icin merkezlenmemis (0..1 araliginda daha kararli) versiyon
    tfu2 = _unit(tf)
    labels = cluster_sections(bounds, n_bars, cfu, tfu2)
    ext = bounds + [n_bars]
    energies = [float(en[a:b].mean()) for a, b in zip(ext[:-1], ext[1:])]
    names = name_sections(labels, energies)
    return [SectionInfo(beat=starts[a], name=nm, cluster=l, energy=e)
            for a, nm, l, e in zip(bounds, names, labels, energies)]
