"""Ayristirilmis gitar partisinden chart (yalniz numpy; pygame IMPORT ETMEZ, deterministik).

Girdi: tum miksin analizi (tempo haritasi / vuruslar / bolumler - gh.autochart.analyze), ayristirilmis gitar
stem'i ve onun polifonik nota olaylari (gh.ai.basic_pitch: baslangic, bitis, midi, genlik) + kare posteriorlari.

Akis
1. Aktivite: gitar RMS'i miksle karsilastirilir; gitarin sustugu bolgelere nota konmaz (davul/vokal doldurulmaz).
2. Olaylar: gitar stem'inin spektral akisi (pena vuruslari, palm-mute chug'lari) + basic-pitch nota baslangiclari
   45 ms icinde birlestirilir; her olayin perde kumesi (akor), kok perdesi, suresi (sustain) ve vurus gucu.
3. Akorlar: kok + kvint (+ oktav) = power chord -> 2'li sekil; 3+ farkli perde sinifi -> 3'lu sekil;
   yalniz oktav katlari / harmonikler -> tek nota.
4. Niceleme: 16'lik / uclemeler (charter.quantize ile ayni kural), yogunluk tavani.
5. Perdeler: cumle cumle (1.5 vurustan uzun bosluk / bolum siniri = yeni cumle). <=5 farkli perdeli cumlede
   perde merdiveni: ayni perde = ayni tus, yukari = yukari, buyuk aralik (kvart/oktav) = buyuk sicrama, cumlenin
   sarkidaki yuksekligine gore yeniden ortalama. Daha zengin cumlelerde kayan pencereli Viterbi (assign_frets).
6. Hizli pena notalari (dogal HOPO olacak ama guclu vurus) -> force strum; legato kosular dogal HOPO kalir.
7. Uzun notalar sustain (whammy), bolum tekrarlarinda desen yeniden kullanimi, sonra charter.finalize:
   Hard/Medium/Easy indirgeme, SP, dogrulama (parse + bot full combo, 0 overstrum).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import dsp
from .analysis import Analysis
from .charter import (FIRST_NOTE_MIN, HOPO_TICKS, RES, STRAIGHT, TRIPLET, ChartResult, GNote, _progress,
                      assign_frets, build_context, cap_density, chord_shape, finalize, reuse_patterns, set_sustains)

GUITAR_MIDI_LO, GUITAR_MIDI_HI = 35, 86       # B1 (7 tel / drop) .. D6 (22. perde)
MAX_NPS_GUITAR = 12.0
CLUSTER_S = 0.045
MIN_EVENT_STRENGTH = 0.2
HARMONIC_INTERVALS = {12, 19, 24, 28, 31, 36}
SEXTUPLET = np.arange(7) / 6.0
LEAD_LO, LEAD_HI = 59, 92                     # zayif lead cizgisinin perde bandi (B3 .. G#6)
LEAD_HARMONICS = np.array([0, 12, 19, 24, 28, 31, 34, 36])
LEAD_MIN_RATE = 5.0                           # aciklanamayan yuksek onset tepesi / s
LEAD_MIN_SECONDS = 3.0


@dataclass
class GuitarEvent:
    time: float
    strength: float                       # 0..1 vurus gucu
    pitches: list[int] = field(default_factory=list)
    root: float = 0.0                     # kontur icin kok perde (midi)
    size: int = 1                         # akor buyuklugu (1..3)
    end: float = 0.0                      # sesin surdugu son an (s)
    picked: bool = True                   # belirgin pena vurusu (akida tepe var)
    low: float = 0.0                      # gitar stem'inde alcak bant (80-300 Hz) enerji orani (ritim / chug)
    bright: float = 0.0                   # spektral merkez (Hz): distorsiyon gostergesi


@dataclass
class GuitarInput:
    """gh.ai boru hattindan gelen gitar bilgisi (pygame / onnxruntime'dan bagimsiz)."""
    audio: np.ndarray                     # ayristirilmis gitar, mono
    sr: int
    mix: np.ndarray                       # ayni uzunlukta tam miks, mono (aktivite referansi)
    notes: list = field(default_factory=list)          # NoteEvent benzeri: start, end, pitch, amplitude, onset
    note_post: np.ndarray | None = None   # (kare, 88) basic-pitch 'note' posteriorlari
    onset_post: np.ndarray | None = None  # (kare, 88) basic-pitch 'onset' posteriorlari
    post_times: np.ndarray | None = None  # (kare,) saniye
    mix_onsets: list = field(default_factory=list)     # [(zaman, guc)] tum miksin onset'leri (chug doldurma)


@dataclass
class GuitarStats:
    active_fraction: float = 0.0
    guitar_db: float = -120.0             # gitar RMS / miks RMS (dB)
    events: int = 0
    present: bool = False
    reason: str = ""


# --------------------------------------------------------------------------- aktivite

def _frame_rms(x: np.ndarray, sr: int, hop_s: float = 0.05, win_s: float = 0.1) -> np.ndarray:
    hop = max(1, int(sr * hop_s))
    win = max(hop, int(sr * win_s))
    x = np.asarray(x, dtype=np.float32)
    n = max(1, 1 + (x.size - win) // hop) if x.size >= win else 1
    c = np.concatenate([[0.0], np.cumsum(x.astype(np.float64) ** 2)])
    idx = np.arange(n) * hop
    hi = np.minimum(idx + win, x.size)
    return np.sqrt(np.maximum(c[hi] - c[idx], 0) / np.maximum(hi - idx, 1))


def activity(gi: GuitarInput, hop_s: float = 0.05) -> tuple[np.ndarray, np.ndarray, float]:
    """(kare zamanlari, aktif mi, gitar/miks dB). Gitar miksin ~18 dB altindan zayifsa ya da mutlak olarak cok
    sessizse o bolge 'gitarsiz' sayilir."""
    g = _frame_rms(gi.audio, gi.sr, hop_s)
    m = _frame_rms(gi.mix, gi.sr, hop_s)
    n = min(g.size, m.size)
    g, m = g[:n], m[:n]
    ref = max(float(np.percentile(m, 95)) if n else 0.0, 1e-6)
    rel = 20 * np.log10(np.maximum(g, 1e-9) / np.maximum(m, ref * 0.03))
    ab = 20 * np.log10(np.maximum(g, 1e-9) / ref)
    act = (rel > -18.0) & (ab > -42.0)
    # kisa bosluklari kapat, tekil kareleri at (~0.35 s medyan), kenarlara 0.25 s pay
    if n >= 7:
        act = dsp.moving_median(act.astype(np.float64), 7) > 0.5
    pad = int(round(0.25 / hop_s))
    if pad and n:
        act = dsp.max_filter1d(act.astype(np.float64), 2 * pad + 1) > 0.5
    gdb = 20 * math.log10(max(float(np.sqrt(np.mean(np.asarray(gi.audio, np.float64) ** 2))), 1e-9) /
                          max(float(np.sqrt(np.mean(np.asarray(gi.mix, np.float64) ** 2))), 1e-9))
    return np.arange(n) * hop_s, act, gdb


# --------------------------------------------------------------------------- olaylar

def flux_onsets(x: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    """Gitar stem'inde spektral aki tepeleri (zaman, guc 0..1)."""
    y = dsp.resample(dsp.to_mono(x), sr, dsp.SR)
    peak = float(np.abs(y).max()) if y.size else 0.0
    if peak <= 0:
        return np.zeros(0), np.zeros(0)
    bands = dsp.onset_bands(y / peak)
    full = bands.full / max(np.percentile(bands.full, 99.5), 1e-9)
    mel = bands.melody / max(np.percentile(bands.melody, 99.5), 1e-9)
    env = np.clip(0.6 * full + 0.4 * mel, 0, 1.5)
    loc = dsp.max_filter1d(env, int(4 * dsp.FPS))
    loc = dsp.moving_average(loc, int(2 * dsp.FPS))
    norm = env / np.maximum(loc, 0.08)
    peaks = dsp.pick_peaks(norm, pre_max=3, post_max=3, pre_avg=8, post_avg=6, delta=0.07, wait=3)
    if not peaks.size:
        return np.zeros(0), np.zeros(0)
    times = np.array([(p + dsp.parabolic_offset(norm, int(p))) / dsp.FPS for p in peaks])
    return times, np.clip(norm[peaks], 0, 1.0)


def chord_size(pitches: list[int]) -> int:
    """Perde kumesinden gitar akoru buyuklugu: 1 (tek nota / oktav / harmonik), 2 (power chord, ikili), 3."""
    ps = sorted(set(int(p) for p in pitches))
    if len(ps) <= 1:
        return 1
    root = ps[0]
    iv = [p - root for p in ps[1:]]
    real = [d for d in iv if d not in HARMONIC_INTERVALS]
    if not real:
        return 1                          # yalniz oktavlar / dogal harmonikler
    pcs = {(p - root) % 12 for p in ps}
    if pcs <= {0, 7} or pcs <= {0, 5, 7}:
        return 2
    return 3 if len(pcs) >= 3 else 2


def _posterior_pitches(post: np.ndarray | None, times: np.ndarray | None, t: float, a_off: float, b_off: float,
                       thr: float, top: int = 4) -> tuple[list[int], list[float]]:
    """Posterior matrisinde [t+a_off, t+b_off] araliginda perde ekseninde yerel tepe yapan perdeler (>= thr)."""
    if post is None or times is None or not times.size:
        return [], []
    a = int(np.searchsorted(times, t + a_off))
    b = max(a + 1, int(np.searchsorted(times, t + b_off)))
    if a >= post.shape[0]:
        return [], []
    act = post[a:b].max(axis=0)
    lo, hi = GUITAR_MIDI_LO - 21, GUITAR_MIDI_HI - 21
    cand = []
    for i in range(max(1, lo), min(act.size - 1, hi + 1)):
        v = float(act[i])
        if v >= thr and v >= act[i - 1] and v >= act[i + 1]:
            cand.append((v, i + 21))
    cand.sort(reverse=True)
    cand = cand[:top]
    return [p for _v, p in cand], [v for v, _p in cand]


def analyse_pitches(pitches: list[int], amps: list[float]) -> tuple[list[int], float, int]:
    """Ayni anda baslayan perdeler -> (tutulan perdeler, kontur perdesi, akor buyuklugu).

    Zayif perdeler (en gucluden %50 asagi) atilir; tek el pozisyonu bir oktavi asmaz (daha genis araliktaki
    notalar ikinci gitar / harmonik sayilir). Akor yoksa kontur perdesi en belirgin (en guclu) notadir, akorda
    en alttaki (kok)."""
    if not pitches:
        return [], 0.0, 1
    mx = max(amps)
    keep = sorted({int(p) for p, a in zip(pitches, amps) if a >= 0.55 * mx})
    salient = int(pitches[int(np.argmax(amps))])
    group = [p for p in keep if keep[0] <= p <= keep[0] + 12]
    size = chord_size(group)
    if size >= 2:
        return group, float(group[0]), size
    return keep, float(salient), 1


def _posterior_end(gi: GuitarInput, t: float, pitch: int, max_s: float = 4.0, thr: float = 0.25) -> float:
    if gi.note_post is None or gi.post_times is None:
        return t
    col = pitch - 21
    if not 0 <= col < gi.note_post.shape[1]:
        return t
    i = int(np.searchsorted(gi.post_times, t + 0.03))
    last = i
    gap = 0
    while i < gi.post_times.size and gi.post_times[i] < t + max_s:
        if gi.note_post[i, col] >= thr:
            last = i
            gap = 0
        else:
            gap += 1
            if gap > 3:
                break
        i += 1
    return float(gi.post_times[min(last, gi.post_times.size - 1)])


def build_events(gi: GuitarInput, act_t: np.ndarray, act: np.ndarray,
                 pitch_analyzer: dsp.PitchAnalyzer | None = None,
                 lead_out: list | None = None) -> list[GuitarEvent]:
    """Aki tepeleri + basic-pitch baslangiclari -> birlestirilmis gitar olaylari (yalniz aktif bolgelerde).
    lead_out: verilirse lead cizgisiyle degistirilen (solo) bolgeler [(t0, t1)] eklenir."""
    hop = float(act_t[1] - act_t[0]) if act_t.size > 1 else 0.05

    def active(t: float) -> bool:
        if not act.size:
            return False
        return bool(act[min(act.size - 1, max(0, int(round(t / hop))))])

    ft, fs = flux_onsets(gi.audio, gi.sr)
    notes = [n for n in gi.notes if GUITAR_MIDI_LO <= int(n.pitch) <= GUITAR_MIDI_HI]
    starts = np.array([float(n.start) for n in notes])
    cands: list[float] = [float(t) for t in ft if active(float(t))]
    cands += [float(n.start) for n in notes if active(float(n.start))]
    cands.sort()
    clusters: list[list[float]] = []
    for c in cands:
        if clusters and c - clusters[-1][0] <= CLUSTER_S:
            clusters[-1].append(c)
        else:
            clusters.append([c])
    tw = 0.045
    events: list[GuitarEvent] = []
    for cl in clusters:
        lo_t, hi_t = cl[0] - 1e-6, cl[-1] + 1e-6
        fi = np.nonzero((ft >= lo_t) & (ft <= hi_t))[0]
        if fi.size:
            j = int(fi[np.argmax(fs[fi])])
            s_f, tc = float(fs[j]), float(ft[j])
        else:
            s_f = 0.0
            tc = float(np.median(cl))
        k0, k1 = np.searchsorted(starts, tc - tw), np.searchsorted(starts, tc + tw, side="right")
        near = notes[k0:k1]
        on_near = [n for n in near if getattr(n, "onset", True)]
        if on_near:
            # basic-pitch'in onset'li notalari: ayni anda baslayanlar = akor
            pitches = [int(n.pitch) for n in on_near]
            amps = [float(n.amplitude) for n in on_near]
            s_bp = min(1.0, 1.3 * max(amps))
        else:
            # yeni nota kanitini onset posteriorundan ara; yalniz en guclu perde (calan notalarin kuyrugu ya da
            # komsu onset'ler akor sanilmasin - akorlar yalniz basic-pitch'in ayni anda baslattigi notalardan)
            pitches, amps = _posterior_pitches(gi.onset_post, gi.post_times, tc, -0.02, 0.04, 0.3, top=4)
            if pitches:
                # distorsiyonlu akorlarda en guclu aday cogu zaman bir harmoniktir: guclu adaylarin en alcagi
                strong = [(p, a) for p, a in zip(pitches, amps) if a >= 0.6 * max(amps)]
                p0, a0 = min(strong)
                pitches, amps = [p0], [a0]
            s_bp = min(1.0, max(amps)) if amps else 0.0
            if pitches and s_f < 0.3 and s_bp < 0.45:
                continue
            if not pitches and near and s_f >= 0.35:
                j = int(np.argmax([n.amplitude for n in near]))
                pitches, amps = [int(near[j].pitch)], [float(near[j].amplitude)]
                s_bp = 0.5 * amps[0]
            if not pitches:
                if s_f < 0.75:
                    continue                      # zayif, perdesiz aki tepesi (sizinti / gurultu)
                pitches, amps = _posterior_pitches(gi.note_post, gi.post_times, tc, 0.015, 0.12, 0.33, top=1)
                if not pitches and pitch_analyzer is not None:
                    p, clar = pitch_analyzer.pitch(tc)
                    if clar >= 0.15:
                        pitches, amps = [int(round(p))], [0.3]
                if not pitches:
                    continue
        strength = max(s_f, s_bp)
        if strength < MIN_EVENT_STRENGTH:
            continue
        keep, root, size = analyse_pitches(pitches, amps)
        ends = [float(n.end) for n in near if int(n.pitch) in keep]
        end = max(ends) if ends else _posterior_end(gi, tc, int(root))
        low = bright = 0.0
        if pitch_analyzer is not None:
            # gitar stem'inde kok perdenin (ve harmoniklerinin) enerjisi ne kadar suruyor: tutulan akorlar
            end = max(end, tc + pitch_analyzer.sustain(tc, float(min(keep))))
            low, bright = _low_ratio(pitch_analyzer, tc), pitch_analyzer.brightness(tc)
        events.append(GuitarEvent(time=tc, strength=float(strength), pitches=keep, root=float(root), size=size,
                                  end=max(end, tc), picked=s_f >= 0.45, low=low, bright=bright))
    fix_octaves(events)
    events = chug_fill(gi, events, active)
    regions = weak_lead_regions(gi, flux_times=ft)
    if regions:
        events = apply_lead(gi, events, regions, active)
        if lead_out is not None:
            lead_out.extend(regions)
    return events


# --------------------------------------------------------------------------- zayif lead (distorsiyonlu solo)

def onset_peaks(gi: GuitarInput, lo: int, hi: int, thr: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """basic-pitch onset posteriorunda [lo, hi] perde bandinin zamanda yerel tepeleri: (zaman, perde, deger)."""
    if gi.onset_post is None or gi.post_times is None or gi.onset_post.shape[0] < 3:
        return np.zeros(0), np.zeros(0, dtype=int), np.zeros(0)
    band = gi.onset_post[:, lo - 21:hi - 21 + 1]
    m = band.max(axis=1)
    pk = np.r_[False, (m[1:-1] > m[:-2]) & (m[1:-1] >= m[2:]) & (m[1:-1] > thr), False]
    n = min(pk.size, gi.post_times.size)
    pk = pk[:n]
    return gi.post_times[:n][pk], band[:n][pk].argmax(axis=1) + lo, m[:n][pk]


def _explained(gi: GuitarInput, times: np.ndarray, pitches: np.ndarray, tol: float = 0.04,
               held_s: float = 0.3) -> np.ndarray:
    """Tepe transkribe edilmis notalarla aciklanabiliyor mu: ayni anda (+-tol) baslayan bir nota var (pena
    vurusunun distorsiyon harmonikleri) ya da o an tutulan uzun (>= held_s) bir notanin harmonigi (oktav, 12'li,
    ...; tutulan distorsiyonlu akorlarin vuruntusu)."""
    st = np.array([float(n.start) for n in gi.notes])
    en = np.array([float(n.end) for n in gi.notes])
    sp = np.array([int(n.pitch) for n in gi.notes])
    order = np.argsort(st)
    st, en, sp = st[order], en[order], sp[order]
    held = en - st >= held_s
    hs, he, hp = st[held], en[held], sp[held]
    out = np.zeros(times.size, dtype=bool)
    for i, (t, p) in enumerate(zip(times, pitches)):
        a, b = np.searchsorted(st, t - tol), np.searchsorted(st, t + tol, side="right")
        if b > a:
            out[i] = True
            continue
        k = (hs <= t) & (he >= t)
        if k.any():
            d = int(p) - hp[k]
            out[i] = bool(np.any(np.min(np.abs(d[:, None] - LEAD_HARMONICS[None, :]), axis=1) <= 1))
    return out


def weak_lead_regions(gi: GuitarInput, win: float = 6.0, hop: float = 1.0,
                      flux_times: np.ndarray | None = None) -> list[tuple[float, float]]:
    """Distorsiyonlu solo: ritim gitari (chug) ile ayni stem'de, basic-pitch notalari esigin altinda kalir ama
    yuksek perdede yogun onset tepeleri birakir. Tepelerin cogu hicbir notayla / harmonigiyle
    aciklanamiyor (>= %50), saniyede >= 5, perdeleri yuksek (medyan >= 72) ve en az %40'i gitar stem'inde gercek
    bir ataga (spektral aki tepesi, +-30 ms) denk geliyorsa bolge 'zayif lead' sayilir. Son kosul tutulan
    distorsiyonlu akorlarin vuruntusunu (akisi olmayan harmonik tepeleri) eler."""
    pt, pp, _pv = onset_peaks(gi, 64, LEAD_HI, 0.3)
    if pt.size < LEAD_MIN_RATE * win:
        return []
    if flux_times is None:
        flux_times, _fs = flux_onsets(gi.audio, gi.sr)
    ft = np.sort(np.asarray(flux_times, dtype=np.float64))
    if not ft.size:
        return []
    k = np.clip(np.searchsorted(ft, pt), 1, ft.size - 1) if ft.size > 1 else np.zeros(pt.size, dtype=int)
    near = np.minimum(np.abs(ft[k] - pt), np.abs(ft[np.maximum(k - 1, 0)] - pt))
    attack = near <= 0.03
    un = ~_explained(gi, pt, pp)
    marked: list[tuple[float, float]] = []
    for s in np.arange(0.0, float(pt[-1]) + hop, hop):
        w = (pt >= s) & (pt < s + win)
        n = int(w.sum())
        u = w & un
        nu = int(u.sum())
        if (nu >= LEAD_MIN_RATE * win and nu >= 0.5 * n and float(np.median(pp[u])) >= 72
                and float(attack[u].mean()) >= 0.4):
            marked.append((float(s), float(s + win)))
    regions: list[tuple[float, float]] = []
    for a, b in marked:
        if regions and a <= regions[-1][1]:
            regions[-1] = (regions[-1][0], max(regions[-1][1], b))
        else:
            regions.append((a, b))
    out = []
    for a, b in regions:                       # pencere kenarlarini ilk / son aciklanamayan tepeye daralt
        k = np.nonzero((pt >= a) & (pt < b) & un)[0]
        if k.size:
            a2, b2 = float(pt[k[0]]) - 0.05, float(pt[k[-1]]) + 0.1
            if b2 - a2 >= LEAD_MIN_SECONDS:
                out.append((a2, b2))
    return out


def lead_events(gi: GuitarInput, regions: list[tuple[float, float]], active) -> list[GuitarEvent]:
    """Zayif lead bolgelerinde tek sesli cizgi: onset tepeleri (dusuk esik), 40 ms icinde en gucluye birlestirilir,
    perde = tepe perdesi, bitis = nota posteriorunun dusuk esikle takibi."""
    pt, pp, pv = onset_peaks(gi, LEAD_LO, LEAD_HI, 0.25)
    keep = np.zeros(pt.size, dtype=bool)
    for a, b in regions:
        keep |= (pt >= a) & (pt <= b)
    pt, pp, pv = pt[keep], pp[keep], pv[keep]
    merged: list[tuple[float, int, float]] = []
    for t, p, v in zip(pt, pp, pv):
        if merged and t - merged[-1][0] <= CLUSTER_S - 0.005:
            if v > merged[-1][2]:
                merged[-1] = (float(t), int(p), float(v))
            continue
        merged.append((float(t), int(p), float(v)))
    merged = _drop_pitch_spikes(merged)
    out = []
    for i, (t, p, v) in enumerate(merged):
        if not active(t):
            continue
        nxt = merged[i + 1][0] if i + 1 < len(merged) else t + 4.0
        end = min(_posterior_end(gi, t, p, thr=0.12), nxt)
        out.append(GuitarEvent(time=t, strength=float(min(1.0, 0.3 + v)), pitches=[p], root=float(p), size=1,
                               end=max(end, t), picked=False, low=0.0, bright=0.0))
    return out


def _drop_pitch_spikes(line: list[tuple[float, int, float]], span: float = 0.35) -> list[tuple[float, int, float]]:
    """Tek sesli cizgide komsularin (+-span s) medyanindan bir oktavdan fazla sapan tekil perdeler: oktav
    kaydirmasi yetiyorsa kaydir (harmonik / oktav hatasi), yetmiyorsa at."""
    if len(line) < 3:
        return line
    t = np.array([x[0] for x in line])
    p = np.array([x[1] for x in line], dtype=np.float64)
    out = []
    for i, (ti, pi, vi) in enumerate(line):
        a, b = np.searchsorted(t, ti - span), np.searchsorted(t, ti + span, side="right")
        nb = np.r_[p[a:i], p[i + 1:b]]
        if nb.size < 2:
            out.append((ti, pi, vi))
            continue
        med = float(np.median(nb))
        if abs(pi - med) <= 12:
            out.append((ti, pi, vi))
            continue
        q = pi - 12 * int(round((pi - med) / 12))
        if abs(q - med) <= 7 and LEAD_LO <= q <= LEAD_HI:
            out.append((ti, int(q), vi))
    return out


def apply_lead(gi: GuitarInput, events: list[GuitarEvent], regions: list[tuple[float, float]],
               active) -> list[GuitarEvent]:
    """Zayif lead bolgelerindeki ritim (chug) olaylarini lead cizgisiyle degistir (Guitar Hero sololari calar)."""
    lead = lead_events(gi, regions, active)
    if not lead:
        return events

    def inside(t: float) -> bool:
        return any(a <= t <= b for a, b in regions)
    return sorted([e for e in events if not inside(e.time)] + lead, key=lambda e: e.time)


def _low_ratio(pa: dsp.PitchAnalyzer, t: float) -> float:
    """Onset sonrasi ~50 ms'de 80-300 Hz enerjisinin 80-5000 Hz'e orani."""
    m = pa.mag[pa.frame_of(t + 0.05)]
    f = pa.freqs
    tot = float(m[(f >= 80) & (f < 5000)].sum())
    return float(m[(f >= 80) & (f < 300)].sum()) / tot if tot > 0 else 0.0


def fix_octaves(events: list[GuitarEvent], window: float = 2.0) -> None:
    """basic-pitch'in alcak distorsiyonlu notalarda yaptigi oktav hatalari (E2 <-> E3): ayni perde sinifi
    +-window s icinde baska bir oktavda en az iki kat sik goruluyorsa o oktava tasi (kontur ziplamasin).
    Esit siklikta gidip gelen gercek oktav desenleri korunur."""
    if len(events) < 3:
        return
    times = np.array([e.time for e in events])
    roots = np.array([e.root for e in events])
    new = roots.copy()
    for i, e in enumerate(events):
        lo, hi = np.searchsorted(times, e.time - window), np.searchsorted(times, e.time + window)
        seg = roots[lo:hi]
        same = seg[np.abs(np.round(seg - e.root)) % 12 == 0]
        if same.size < 3:
            continue
        vals, counts = np.unique(same, return_counts=True)
        best = vals[int(np.argmax(counts))]
        own = int(np.count_nonzero(same == e.root))
        if best != e.root and counts.max() >= 2 * own:
            new[i] = best
    for e, r in zip(events, new):
        d = float(r - e.root)
        if d:
            e.root = float(r)
            e.pitches = [int(p + d) for p in e.pitches]


def chug_fill(gi: GuitarInput, events: list[GuitarEvent], active) -> list[GuitarEvent]:
    """Palm-mute 'makineli' bolumler: Demucs chug vuruslarini cogu zaman davula verir, gitar stem'inde yalniz
    ton kalir. Gitar calarken (kisa, parcali notalar - uzun tutulan akor degil), alcak perdede ve miks yogun
    (>= 5 onset/s) ise miksin onset'lerine ayni perdeyle tekrar notalari eklenir."""
    if not gi.mix_onsets or not events:
        return events
    ev_t = np.array([e.time for e in events])
    mt = np.array([t for t, _s in gi.mix_onsets])
    added: list[GuitarEvent] = []
    for t, s in gi.mix_onsets:
        if s < 0.15 or not active(t):
            continue
        k = int(np.searchsorted(ev_t, t))
        if (k > 0 and t - ev_t[k - 1] <= 0.06) or (k < ev_t.size and ev_t[k] - t <= 0.06):
            continue
        if k == 0 or k >= ev_t.size:
            continue
        prev, nxt = events[k - 1], events[k]
        if t - prev.time > 0.7 or nxt.time - t > 0.7:
            continue
        if prev.end > t and prev.end - prev.time > 0.6:
            continue                              # tutulan akor / uzun nota: doldurma
        if prev.root > 52 and prev.low < 0.3:
            continue                              # yalniz alcak (ritim) partiler; lead notalarinin arasi dolmaz
        dens = np.count_nonzero(np.abs(mt - t) <= 0.75) / 1.5
        if dens < 5.0:
            continue
        src = prev if prev.root <= nxt.root else nxt      # ritim gitarinin alcak notasi (chug'lar kokte)
        added.append(GuitarEvent(time=float(t), strength=float(min(0.55, 0.25 + 0.5 * s)), pitches=list(src.pitches),
                                 root=src.root, size=src.size, end=float(t) + 0.05, picked=True, low=src.low,
                                 bright=src.bright))
    if not added:
        return events
    return sorted(events + added, key=lambda e: e.time)


def guitar_presence(events: list[GuitarEvent], act: np.ndarray, gdb: float, duration: float) -> GuitarStats:
    st = GuitarStats(events=len(events), guitar_db=gdb)
    st.active_fraction = float(np.mean(act)) if act.size else 0.0
    need = max(16, int(0.25 * duration))
    if gdb < -30.0:
        st.reason = f"guitar stem too quiet ({gdb:.1f} dB)"
    elif st.active_fraction < 0.12:
        st.reason = f"guitar audible only {st.active_fraction:.0%} of the song"
    elif len(events) < need:
        st.reason = f"only {len(events)} guitar notes (need {need})"
    else:
        st.present = True
    return st


# --------------------------------------------------------------------------- niceleme

def quantize_events(events: list[GuitarEvent], tm, first_tick: int, last_tick: int
                    ) -> tuple[list[GNote], dict[int, GuitarEvent]]:
    """charter.quantize ile ayni izgara kurali (vurus basina 16'lik ya da uclemeler); tick basina en guclu olay."""
    by_beat: dict[int, list[tuple[float, int]]] = {}
    for i, e in enumerate(events):
        tf = tm.time_to_tick(e.time) / RES
        b = int(math.floor(tf))
        by_beat.setdefault(b, []).append((tf - b, i))
    out: dict[int, tuple[GNote, GuitarEvent]] = {}
    for b in sorted(by_beat):
        items = by_beat[b]
        fr = np.array([f for f, _ in items])
        e_str = np.abs(fr[:, None] - STRAIGHT[None, :]).min(axis=1)
        e_tri = np.abs(fr[:, None] - TRIPLET[None, :]).min(axis=1)
        e_six = np.abs(fr[:, None] - SEXTUPLET[None, :]).min(axis=1)
        trip_like = int(((np.abs(fr - 1 / 3) < 0.05) | (np.abs(fr - 2 / 3) < 0.05)).sum())
        six_like = int(((np.abs(fr - 1 / 6) < 0.04) | (np.abs(fr - 5 / 6) < 0.04)).sum())
        div = 4
        if six_like >= 1 and len(items) >= 4 and e_six.sum() < 0.6 * min(e_str.sum(), e_tri.sum()):
            div = 6                                   # 16'lik ucleme (metal 'gallop' / makineli chug)
        elif trip_like >= 1 and e_tri.sum() < 0.7 * e_str.sum() and len(items) >= 2:
            div = 3
        for f, i in items:
            q = int(round(f * div))
            tick = b * RES + q * (RES // div)
            if tick < first_tick or tick > last_tick:
                continue
            e = events[i]
            cur = out.get(tick)
            if cur is None or e.strength > cur[1].strength:
                g = GNote(tick=tick, time=tm.tick_to_time(tick), strength=e.strength, pitch=e.root, clarity=1.0,
                          width=0.0, low=0.0, sustain_s=max(0.0, e.end - e.time),
                          triplet=div != 4 and q not in (0, div), chord=e.size)
                out[tick] = (g, e)
    ticks = sorted(out)
    return [out[t][0] for t in ticks], {t: out[t][1] for t in ticks}


# --------------------------------------------------------------------------- perdeler

def ladder_step(d: float) -> int:
    """Iki farkli perde arasindaki tus adimi: yakin (<=4 yarim ton) 1, kvart/kvint 2, oktav ve ustu 3."""
    a = abs(d)
    if a <= 4.5:
        return 1
    if a <= 9.5:
        return 2
    return 3


def ladder_frets(values: list[float], register: float) -> list[int]:
    """<=5 farkli perdeli cumle: monoton, tutarli (ayni perde = ayni tus) merdiven. register 0..1: cumlenin
    sarkidaki yuksekligi (alcak riff -> yesil/kirmizi tarafi, yuksek lead -> mavi/turuncu tarafi)."""
    distinct = sorted(set(values))
    if len(distinct) > 5:
        raise ValueError("ladder needs <= 5 distinct pitches")
    steps = [ladder_step(b - a) for a, b in zip(distinct, distinct[1:])]
    while sum(steps) > 4:
        k = max(range(len(steps)), key=lambda j: (steps[j], -j))
        steps[k] -= 1
    pos = [0]
    for s in steps:
        pos.append(pos[-1] + s)
    span = pos[-1]
    base = int(round(float(np.clip(register, 0.0, 1.0)) * (4 - span)))
    fmap = {p: base + q for p, q in zip(distinct, pos)}
    return [fmap[v] for v in values]


def split_phrases(notes: list[GNote], section_starts: set[int], gap_ticks: int = int(1.5 * RES)) -> list[list[int]]:
    phrases: list[list[int]] = []
    for i, n in enumerate(notes):
        new = i == 0 or n.tick - notes[i - 1].tick > gap_ticks or any(
            notes[i - 1].tick < s <= n.tick for s in section_starts)
        if new:
            phrases.append([i])
        else:
            phrases[-1].append(i)
    return phrases


def map_frets(notes: list[GNote], section_starts: set[int]) -> None:
    """Cumle bazli perde secimi + akor sekilleri (yerinde)."""
    if not notes:
        return
    allp = np.array([n.pitch for n in notes], dtype=np.float64)
    for ph in split_phrases(notes, section_starts):
        vals = [notes[i].pitch for i in ph]
        if len(set(vals)) <= 5:
            med = float(np.median(vals))
            rel = float((allp < med).mean() + 0.5 * (allp == med).mean())      # sarki icindeki yukseklik
            ab = float(np.clip((med - 45.0) / 30.0, 0.0, 1.0))                 # A2 .. D#5 mutlak yukseklik
            frets = ladder_frets(vals, 0.35 * rel + 0.65 * ab)
        else:
            reg = np.clip((np.asarray(vals, dtype=np.float64) - 45.0) / 30.0, 0.0, 1.0)
            frets = assign_frets(vals, 5, None, fold=False, window=12, distinct_rank=True, same_cost=12.0,
                                 register=reg, register_weight=0.5)
        for i, f in zip(ph, frets):
            n = notes[i]
            n.fret = int(f)
            n.mask = chord_shape(n.fret, max(1, min(3, n.chord or 1)), 0)


def accent_chords(notes: list[GNote], evmap: dict[int, GuitarEvent], bright_hz: float = 1900.0) -> None:
    """Distorsiyonlu ritim gitarinda basic-pitch akorlari cogu zaman tek (ya da harmonik) nota gorur. Guclu,
    alcak perdeli, 8'lik izgarada ve hizli kosu icinde olmayan pena vuruslari power chord (2'li) sayilir."""
    for i, n in enumerate(notes):
        e = evmap.get(n.tick)
        if e is None or n.chord >= 2:
            continue
        if not (e.picked and e.strength >= 0.85 and e.bright >= bright_hz and (e.low >= 0.25 or n.pitch <= 57)):
            continue
        if n.tick % (RES // 2):
            continue
        gp = n.tick - notes[i - 1].tick if i else 10 ** 6
        gn = notes[i + 1].tick - n.tick if i + 1 < len(notes) else 10 ** 6
        if min(gp, gn) < RES // 2:
            continue
        n.chord = 2


def mark_force_strums(notes: list[GNote], evmap: dict[int, GuitarEvent]) -> None:
    """Dogal HOPO olacak (yakin, farkli perde) ama guclu pena vurusuyla calinan notalar strum kalir."""
    from .charter import _natural_hopo
    prev = None
    for n in notes:
        e = evmap.get(n.tick)
        n.force_strum = bool(e is not None and e.picked and e.strength >= 0.6 and _natural_hopo(prev, n))
        prev = n


def solo_ticks(notes: list[GNote], tm, regions: list[tuple[float, float]], min_notes: int = 8
               ) -> list[tuple[int, int]]:
    """Solo bolgeleri (s) -> icindeki ilk / son Expert notasinin tick'leri."""
    out = []
    for a, b in regions:
        ta, tb = tm.time_to_tick(a), tm.time_to_tick(b)
        inside = [n.tick for n in notes if ta - RES // 8 <= n.tick <= tb + RES // 8]
        if len(inside) >= min_notes and not any(s <= inside[0] <= e for s, e in out):
            out.append((inside[0], inside[-1]))
    return out


def make_expert_guitar(ctx, events: list[GuitarEvent]) -> list[GNote]:
    tm = ctx.tm
    first = int(math.ceil(tm.time_to_tick(FIRST_NOTE_MIN)))
    notes, evmap = quantize_events(events, tm, first, ctx.last_tick)
    notes = cap_density(notes, MAX_NPS_GUITAR)
    if not notes:
        return notes
    for n in notes:
        for si, (st, en, _cl) in enumerate(ctx.section_ticks):
            if st <= n.tick < en:
                n.section = si
                break
    accent_chords(notes, evmap)
    map_frets(notes, {st for st, _en, _cl in ctx.section_ticks})
    reuse_patterns(notes, ctx.section_ticks)
    set_sustains(notes, tm, ctx.an)
    mark_force_strums(notes, evmap)
    return notes


def generate_guitar(an: Analysis, events: list[GuitarEvent], *, title: str = "Unknown", artist: str = "Unknown",
                    album: str = "", year: str = "", genre: str = "", music_stream: str = "song.ogg",
                    progress=None, check: bool = True, lead_regions: list | None = None) -> ChartResult:
    _progress(progress, 0.05, "Building tempo map")
    ctx = build_context(an)
    _progress(progress, 0.2, "Placing notes")
    expert = make_expert_guitar(ctx, events)
    if len(expert) < 8:
        raise ValueError("could not find enough guitar notes in this audio")
    solos = solo_ticks(expert, ctx.tm, lead_regions or [])
    return finalize(ctx, expert, title=title, artist=artist, album=album, year=year, genre=genre,
                    music_stream=music_stream, progress=progress, check=check, lo=0.5, solos=solos)
