"""Otomatik chart uretici gercek-muzik olcumu: Songs/ altindaki el yapimi demo chart'lar referans alinir.

Her sarki icin YALNIZ tam miks (song.ogg + guitar.ogg toplami) auto-charter'a verilir, sonuc el yapimi
Expert chart ile karsilastirilir:
  - tempo hatasi (%), vurus hizalamasi (gercek vuruslarin 20 / 50 ms icinde yakalanma orani)
  - onset F1: uretilen Expert notalari vs gercek Expert notalari (+-50 ms)
  - kontur uyumu: eslesen ardisik nota ciftlerinde perde hareket yonu uyumu (+ korelasyon)
  - analiz ve toplam uretim suresi

Kullanim:  .venv\\Scripts\\python.exe tools\\benchmark_autochart.py [--song <ad parcasi>] [--out rapor.json]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402

from gh.autochart import analyze, generate  # noqa: E402
from gh.chart import load_song, parse_chart  # noqa: E402


def load_audio(path: str) -> tuple[np.ndarray, int]:
    try:
        import soundfile as sf
        data, sr = sf.read(path, dtype="float32", always_2d=True)
        return data.mean(axis=1), sr
    except ImportError:
        from gh.importer import decode_audio
        return decode_audio(path)


def match_times(est: np.ndarray, ref: np.ndarray, tol: float = 0.05) -> list[tuple[int, int]]:
    """Acgozlu en yakin eslesme (her tahmin en fazla bir referansla). [(tahmin_i, ref_j)]."""
    pairs = []
    for j, r in enumerate(ref):
        d = np.abs(est - r)
        pairs += [(float(d[i]), i, j) for i in np.nonzero(d <= tol)[0]]
    pairs.sort()
    used_e, used_r, out = set(), set(), []
    for _d, i, j in pairs:
        if i in used_e or j in used_r:
            continue
        used_e.add(i)
        used_r.add(j)
        out.append((i, j))
    return sorted(out)


def prf(n_est: int, n_ref: int, n_hit: int) -> tuple[float, float, float]:
    p = n_hit / max(n_est, 1)
    r = n_hit / max(n_ref, 1)
    return p, r, (2 * p * r / (p + r) if p + r > 0 else 0.0)


def low_fret(mask: int) -> int:
    return (mask & -mask).bit_length() - 1 if mask else -1


def contour(gen_notes, ref_notes, pairs) -> tuple[float, float, int]:
    """Eslesen notalar arasinda ardisik ciftlerin perde hareketi yonu uyumu ve korelasyonu."""
    dg, dr = [], []
    for (i1, j1), (i2, j2) in zip(pairs, pairs[1:]):
        if i2 != i1 + 1 or j2 != j1 + 1:
            continue
        dg.append(low_fret(gen_notes[i2].mask) - low_fret(gen_notes[i1].mask))
        dr.append(low_fret(ref_notes[j2].mask) - low_fret(ref_notes[j1].mask))
    if len(dg) < 3:
        return 0.0, 0.0, len(dg)
    dg, dr = np.sign(np.array(dg)), np.sign(np.array(dr))
    agree = float(np.mean(dg == dr))
    corr = float(np.corrcoef(dg, dr)[0, 1]) if dg.std() > 0 and dr.std() > 0 else 0.0
    return agree, corr, len(dg)


def true_beats(chart, dur: float) -> np.ndarray:
    tm = chart.tempo_map
    out, k = [], 0
    while True:
        t = tm.tick_to_time(k * chart.resolution)
        if t > dur:
            break
        out.append(t)
        k += 1
    return np.asarray(out)


def bench_song(folder: str) -> dict:
    name = os.path.basename(folder)
    song, sr = load_audio(os.path.join(folder, "song.ogg"))
    gtr_path = os.path.join(folder, "guitar.ogg")
    if os.path.exists(gtr_path):
        g, sr2 = load_audio(gtr_path)
        n = min(song.size, g.size)
        mix = song[:n] + g[:n]
    else:
        mix = song
    ref = load_song(folder)
    t0 = time.perf_counter()
    an = analyze(mix, sr)
    t_an = time.perf_counter() - t0
    t1 = time.perf_counter()
    res = generate(mix, sr, title=ref.info.name, artist=ref.info.artist, analysis=an)
    t_gen = time.perf_counter() - t1
    chart = parse_chart(res.text)
    out = {"song": name, "duration_s": round(an.duration, 1), "analysis_s": round(t_an, 2),
           "analysis_s_per_2min": round(t_an * 120.0 / an.duration, 2), "generate_s": round(t_gen, 2)}
    true_bpm = ref.tempo_map.tempos[0].bpm
    out["tempo_true"] = true_bpm
    out["tempo_est"] = round(an.tempo, 2)
    out["tempo_err_pct"] = round(100.0 * abs(an.tempo - true_bpm) / true_bpm, 2)
    tb = true_beats(ref, an.duration)
    tb = tb[(tb >= an.beats[0] - 0.1) & (tb <= an.beats[-1] + 0.1)]
    d = np.array([np.min(np.abs(an.beats - t)) for t in tb])
    out["beats_within_20ms"] = round(float(np.mean(d < 0.020)), 3)
    out["beats_within_50ms"] = round(float(np.mean(d < 0.050)), 3)
    out["beat_err_median_ms"] = round(float(np.median(d) * 1000), 1)
    # downbeat: gercek olcu baslari
    gen_bars = np.array([l.time for l in chart.tempo_map.beat_lines(an.duration) if l.kind == 0])
    ref_bars = np.array([l.time for l in ref.tempo_map.beat_lines(an.duration) if l.kind == 0])
    if gen_bars.size and ref_bars.size:
        dd = np.array([np.min(np.abs(gen_bars - t)) for t in ref_bars if t > 1.0])
        out["downbeats_within_50ms"] = round(float(np.mean(dd < 0.05)), 3)
    # onset F1 ve kontur (Expert)
    gen = chart.tracks["expert"].notes
    refn = ref.tracks["expert"].notes
    ge = np.array([n.time for n in gen])
    rt = np.array([n.time for n in refn])
    pairs = match_times(ge, rt, 0.05)
    p, r, f = prf(ge.size, rt.size, len(pairs))
    out.update({"expert_notes": int(ge.size), "true_expert_notes": int(rt.size),
                "onset_precision": round(p, 3), "onset_recall": round(r, 3), "onset_f1": round(f, 3)})
    agree, corr, npairs = contour(gen, refn, pairs)
    out.update({"contour_direction_agreement": round(agree, 3), "contour_corr": round(corr, 3),
                "contour_pairs": npairs})
    def style(notes):
        n = max(len(notes), 1)
        return {"chord": round(sum(x.is_chord for x in notes) / n, 2), "hopo": round(sum(x.type == 1 for x in notes) / n, 2),
                "sustain": round(sum(x.has_sustain for x in notes) / n, 2)}

    out["style"] = style(gen)
    out["true_style"] = style(refn)
    out["counts"] = {dname: len(chart.tracks[dname].notes) for dname in ("easy", "medium", "hard", "expert")
                     if dname in chart.tracks}
    out["true_counts"] = {dname: len(ref.tracks[dname].notes) for dname in ("easy", "medium", "hard", "expert")
                          if dname in ref.tracks}
    out["sp_phrases"] = {dname: len(chart.tracks[dname].sp_phrases) for dname in chart.tracks}
    out["validation"] = {k: v[1] for k, v in res.validation.items()}
    out["valid"] = all(v[0] for v in res.validation.values())
    out["sections"] = [s.name for s in chart.sections]
    out["diff_guitar"] = res.difficulty
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--song", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--root", default=os.path.join(ROOT, "Songs"))
    args = ap.parse_args(argv)
    folders = [f for f in sorted(glob.glob(os.path.join(args.root, "*")))
               if os.path.isdir(f) and os.path.exists(os.path.join(f, "song.ogg"))
               and (os.path.exists(os.path.join(f, "notes.chart")) or os.path.exists(os.path.join(f, "notes.mid")))
               and args.song.lower() in os.path.basename(f).lower()]
    results = []
    for f in folders:
        r = bench_song(f)
        results.append(r)
        print(f"{r['song']}")
        print(f"  tempo {r['tempo_est']} (true {r['tempo_true']}, err {r['tempo_err_pct']}%)  beats<20ms "
              f"{r['beats_within_20ms']:.0%} <50ms {r['beats_within_50ms']:.0%} (median {r['beat_err_median_ms']} ms)"
              f"  downbeats<50ms {r.get('downbeats_within_50ms', 0):.0%}")
        print(f"  expert {r['expert_notes']} vs {r['true_expert_notes']}: P {r['onset_precision']:.2f} "
              f"R {r['onset_recall']:.2f} F1 {r['onset_f1']:.2f}   contour agree {r['contour_direction_agreement']:.2f}"
              f" corr {r['contour_corr']:.2f} ({r['contour_pairs']} pairs)")
        print(f"  counts {r['counts']}  true {r['true_counts']}  SP {r['sp_phrases']}  diff {r['diff_guitar']}")
        print(f"  expert style {r['style']}  true {r['true_style']}")
        print(f"  analysis {r['analysis_s']}s for {r['duration_s']}s ({r['analysis_s_per_2min']}s per 2 min), "
              f"generate+validate {r['generate_s']}s, valid {r['valid']} {r['validation']}")
        print(f"  sections {r['sections']}")
    if results:
        mf1 = np.mean([r["onset_f1"] for r in results])
        mc = np.mean([r["contour_direction_agreement"] for r in results])
        print(f"MEAN onset F1 {mf1:.3f}  contour agreement {mc:.3f}")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
