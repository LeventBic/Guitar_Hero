"""Otomatik chart uretici olcumu: Songs/ altindaki el yapimi demo chart'lar ve sentetik 'gercekci' rock miksi.

Her demo sarki icin tam miks (song.ogg + guitar.ogg) olusturulur ve:
  ESKI  miks tabanli charter (gh.autochart.generate)
  YENI  gitar kalibrasyonu boru hatti (gh.ai.pipeline: Demucs ayristirma -> basic-pitch -> gitardan chart)
  ORAKL ayni boru hatti, ayristirma yerine GERCEK guitar.ogg ile (transkripsiyon + charting'in tek basina kalitesi)
calistirilir. Olculenler (el yapimi Expert chart'a karsi):
  - ayristirma kalitesi: ayristirilan gitarin gercek guitar.ogg'a gore SDR'i (dB)
  - onset F1 (+-50 ms), perde (tus) hareket yonu uyumu, akor yakalama (gercek akorlarin akor olarak cikma orani)
  - mod (guitar / mix geri donusu) ve toplam sure
--synthetic: tools/realistic_mix.py miksinde (distorsiyonlu KS gitar + bas + davul) ground truth'a karsi ayni olculer
             + gitarsiz bolgedeki nota sayisi ve uzun akor bolumundeki gereksiz chug sayisi.
--real <ses dosyasi>: ground truth olmadan sure + bolum bolum yogunluk raporu (telifli dosyalari repoya koymayin).

Kullanim:  .venv\\Scripts\\python.exe tools\\benchmark_autochart.py [--song <ad>] [--no-ai] [--synthetic] [--real f.mp3]
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
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import numpy as np  # noqa: E402

from gh.autochart import analyze, generate  # noqa: E402
from gh.chart import load_song, parse_chart  # noqa: E402


def load_audio(path: str, stereo: bool = False) -> tuple[np.ndarray, int]:
    try:
        import soundfile as sf
        data, sr = sf.read(path, dtype="float32", always_2d=True)
        return (data if stereo else data.mean(axis=1)), sr
    except ImportError:
        from gh.importer import decode_audio
        return decode_audio(path, stereo=stereo)


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


def contour(gen_vals, ref_vals, pairs) -> tuple[float, float, int]:
    """Eslesen notalar arasinda ardisik ciftlerin hareket yonu uyumu ve korelasyonu (degerler: tus / perde)."""
    dg, dr = [], []
    for (i1, j1), (i2, j2) in zip(pairs, pairs[1:]):
        if i2 != i1 + 1 or j2 != j1 + 1:
            continue
        dg.append(gen_vals[i2] - gen_vals[i1])
        dr.append(ref_vals[j2] - ref_vals[j1])
    if len(dg) < 3:
        return 0.0, 0.0, len(dg)
    dg, dr = np.sign(np.array(dg)), np.sign(np.array(dr))
    agree = float(np.mean(dg == dr))
    corr = float(np.corrcoef(dg, dr)[0, 1]) if dg.std() > 0 and dr.std() > 0 else 0.0
    return agree, corr, len(dg)


def chord_recall(gen_chord: list[bool], ref_chord: list[bool], pairs) -> tuple[float, int]:
    ref_ch = [(i, j) for i, j in pairs if ref_chord[j]]
    if not ref_ch:
        return float("nan"), 0
    return float(np.mean([gen_chord[i] for i, _j in ref_ch])), len(ref_ch)


def sdr(ref, est) -> float:
    ref = np.asarray(ref, dtype=np.float64)
    est = np.asarray(est, dtype=np.float64)
    n = min(ref.shape[-1], est.shape[-1])
    ref, est = ref[..., :n], est[..., :n]
    return float(10 * np.log10(max((ref ** 2).sum(), 1e-20) / max(((ref - est) ** 2).sum(), 1e-20)))


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


def chart_scores(text: str, ref) -> dict:
    chart = parse_chart(text)
    gen = chart.tracks["expert"].notes
    refn = ref.tracks["expert"].notes
    ge = np.array([n.time for n in gen])
    rt = np.array([n.time for n in refn])
    pairs = match_times(ge, rt, 0.05)
    p, r, f = prf(ge.size, rt.size, len(pairs))
    agree, corr, npairs = contour([low_fret(n.mask) for n in gen], [low_fret(n.mask) for n in refn], pairs)
    cr, ncr = chord_recall([n.is_chord for n in gen], [n.is_chord for n in refn], pairs)
    return {"expert_notes": int(ge.size), "true_expert_notes": int(rt.size), "onset_precision": round(p, 3),
            "onset_recall": round(r, 3), "onset_f1": round(f, 3), "contour_direction_agreement": round(agree, 3),
            "contour_corr": round(corr, 3), "contour_pairs": npairs,
            "chord_recall": round(cr, 3) if cr == cr else None, "true_chords_matched": ncr,
            "chord_share": round(float(np.mean([n.is_chord for n in gen])) if gen else 0.0, 3),
            "counts": {d: len(chart.tracks[d].notes) for d in ("easy", "medium", "hard", "expert")}}


def bench_song(folder: str, ai: bool = True) -> dict:
    name = os.path.basename(folder)
    song, sr = load_audio(os.path.join(folder, "song.ogg"), stereo=True)
    g, _sr2 = load_audio(os.path.join(folder, "guitar.ogg"), stereo=True)
    n = min(song.shape[0], g.shape[0])
    song, g = song[:n], g[:n]
    if song.shape[1] == 1:
        song = np.repeat(song, 2, axis=1)
    if g.shape[1] == 1:
        g = np.repeat(g, 2, axis=1)
    mix = song + g
    ref = load_song(folder)
    out = {"song": name, "duration_s": round(n / sr, 1)}
    # ESKI: miks tabanli
    t0 = time.perf_counter()
    an = analyze(mix.mean(axis=1), sr)
    res = generate(mix.mean(axis=1), sr, title=ref.info.name, artist=ref.info.artist, analysis=an)
    out["old_seconds"] = round(time.perf_counter() - t0, 1)
    out["old"] = chart_scores(res.text, ref)
    out["tempo_true"] = ref.tempo_map.tempos[0].bpm
    out["tempo_est"] = round(an.tempo, 2)
    tb = true_beats(ref, an.duration)
    tb = tb[(tb >= an.beats[0] - 0.1) & (tb <= an.beats[-1] + 0.1)]
    d = np.array([np.min(np.abs(an.beats - t)) for t in tb])
    out["beats_within_50ms"] = round(float(np.mean(d < 0.050)), 3)
    if not ai:
        return out
    from gh.ai import pipeline
    kw = dict(title=ref.info.name, artist=ref.info.artist)
    t0 = time.perf_counter()
    new = pipeline.chart_with_guitar(mix, sr, **kw)
    out["new_seconds"] = round(time.perf_counter() - t0, 1)
    out["new_mode"] = new.mode
    out["new_reason"] = getattr(new.stats, "reason", "")
    out["new_timings"] = {k: round(v, 1) for k, v in new.timings.items()}
    if new.guitar is not None:
        out["sep_sdr_db"] = round(sdr(g.T, new.guitar), 2)
    else:
        from gh.ai.demucs import separate
        st = separate(mix)
        out["sep_sdr_db"] = round(sdr(g.T, st.guitar), 2)
        out["sep_guitar_rms_db"] = round(20 * np.log10(st.energy["guitar"] / max(st.energy["mix"], 1e-9) + 1e-9), 1)
    out["new"] = chart_scores(new.result.text, ref)
    # ORAKL: gercek gitar stem'i ile (ayristirma atlanir)
    t0 = time.perf_counter()
    orc = pipeline.chart_with_guitar(mix, sr, stems=(g.T, song.T), **kw)
    out["oracle_seconds"] = round(time.perf_counter() - t0, 1)
    out["oracle_mode"] = orc.mode
    out["oracle"] = chart_scores(orc.result.text, ref)
    return out


# --------------------------------------------------------------------------- sentetik gercekci miks

def bench_synthetic() -> dict:
    from realistic_mix import make_mix

    from gh.ai import pipeline
    m = make_mix()
    t0 = time.perf_counter()
    new = pipeline.chart_with_guitar(m.mix, m.sr, title="Synthetic Rock", artist="RIFF")
    secs = time.perf_counter() - t0
    out = {"song": "synthetic distorted-guitar mix", "duration_s": round(m.mix.shape[1] / m.sr, 1),
           "new_seconds": round(secs, 1), "new_mode": new.mode, "new_timings": {k: round(v, 1) for k, v in
                                                                               new.timings.items()}}
    if new.guitar is not None:
        out["sep_sdr_db"] = round(sdr(m.guitar, new.guitar), 2)
        out["backing_sdr_db"] = round(sdr(m.backing, new.backing), 2)
    ev_t = np.array([e[0] for e in m.events])
    ev_root = [min(e[1]) if e[3] != "lead" else e[1][0] for e in m.events]
    ev_chord = [len(set(p % 12 for p in e[1])) >= 2 for e in m.events]

    def score(text, label):
        ch = parse_chart(text)
        gen = ch.tracks["expert"].notes
        ge = np.array([n.time for n in gen])
        pairs = match_times(ge, ev_t, 0.05)
        p, r, f = prf(ge.size, ev_t.size, len(pairs))
        agree, corr, npairs = contour([low_fret(n.mask) for n in gen], ev_root, pairs)
        cr, ncr = chord_recall([n.is_chord for n in gen], ev_chord, pairs)
        silent = sum(1 for n in gen for s0, s1 in m.silent if s0 + 0.2 <= n.time <= s1 - 0.1)
        # uzun akor bolumu (B): gercek olay olmayan yerlerdeki notalar
        b0 = min(e[0] for e in m.events if e[2] > 0.8) - 0.1
        b1 = max(e[0] + e[2] for e in m.events if e[2] > 0.8)
        extra = sum(1 for n in gen if b0 <= n.time <= b1 and np.min(np.abs(ev_t - n.time)) > 0.06)
        sus = sum(1 for n in gen if b0 <= n.time <= b1 and n.has_sustain)
        return {label: {"expert_notes": int(ge.size), "true_events": int(ev_t.size), "onset_precision": round(p, 3),
                        "onset_recall": round(r, 3), "onset_f1": round(f, 3),
                        "contour_direction_agreement": round(agree, 3), "contour_pairs": npairs,
                        "chord_recall": round(cr, 3) if cr == cr else None, "true_chords_matched": ncr,
                        "notes_in_guitarless_gap": silent, "extra_notes_in_held_chords": extra,
                        "sustains_in_held_chords": sus}}

    out.update(score(new.result.text, "new"))
    mono = m.mix.mean(axis=0)
    old = generate(mono, m.sr, title="Synthetic Rock", artist="RIFF")
    out.update(score(old.text, "old"))
    return out


def bench_real(path: str) -> dict:
    from gh.ai import pipeline
    from gh.importer import decode_audio
    x, sr = decode_audio(path, stereo=True)
    t0 = time.perf_counter()
    new = pipeline.chart_with_guitar(x, sr, title=os.path.basename(path), artist="")
    secs = time.perf_counter() - t0
    ch = parse_chart(new.result.text)
    notes = ch.tracks["expert"].notes
    out = {"file": os.path.basename(path), "duration_s": round(x.shape[0] / sr, 1), "seconds": round(secs, 1),
           "mode": new.mode, "timings": {k: round(v, 1) for k, v in new.timings.items()},
           "counts": {d: len(ch.tracks[d].notes) for d in ("easy", "medium", "hard", "expert")},
           "chords": sum(n.is_chord for n in notes), "hopos": sum(n.type == 1 for n in notes),
           "sustains": sum(n.has_sustain for n in notes)}
    dens = []
    for k in range(0, int(out["duration_s"]), 20):
        nn = [n for n in notes if k <= n.time < k + 20]
        dens.append((f"{k // 60}:{k % 60:02d}", len(nn), sum(n.is_chord for n in nn)))
    out["per_20s_notes_chords"] = dens
    return out


def _fmt(s: dict) -> str:
    return (f"F1 {s['onset_f1']:.2f} (P {s['onset_precision']:.2f} R {s['onset_recall']:.2f})  contour "
            f"{s['contour_direction_agreement']:.2f}  chord recall "
            f"{s['chord_recall'] if s['chord_recall'] is not None else '-'}  notes {s['expert_notes']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--song", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--root", default=os.path.join(ROOT, "Songs"))
    ap.add_argument("--no-ai", action="store_true", help="only the old mix-based charter")
    ap.add_argument("--synthetic", action="store_true", help="also run the realistic synthetic rock mix")
    ap.add_argument("--no-demo", action="store_true")
    ap.add_argument("--real", default="", help="audio file without ground truth (timing + density report)")
    args = ap.parse_args(argv)
    results = []
    folders = [] if args.no_demo else [
        f for f in sorted(glob.glob(os.path.join(args.root, "*")))
        if os.path.isdir(f) and os.path.exists(os.path.join(f, "song.ogg"))
        and os.path.exists(os.path.join(f, "guitar.ogg"))
        and (os.path.exists(os.path.join(f, "notes.chart")) or os.path.exists(os.path.join(f, "notes.mid")))
        and args.song.lower() in os.path.basename(f).lower()]
    for f in folders:
        r = bench_song(f, ai=not args.no_ai)
        results.append(r)
        print(f"{r['song']} ({r['duration_s']} s)")
        print(f"  OLD (mix)    {_fmt(r['old'])}  [{r['old_seconds']} s]")
        if "new" in r:
            print(f"  NEW ({r['new_mode']:6s}) {_fmt(r['new'])}  [{r['new_seconds']} s]  sep SDR "
                  f"{r['sep_sdr_db']} dB {r.get('new_reason', '')}")
            print(f"  ORACLE stem  {_fmt(r['oracle'])}  [{r['oracle_seconds']} s] mode {r['oracle_mode']}")
    if args.synthetic:
        r = bench_synthetic()
        results.append(r)
        print(f"{r['song']} ({r['duration_s']} s)  mode {r['new_mode']}  sep SDR {r.get('sep_sdr_db')} dB  "
              f"[{r['new_seconds']} s]")
        for k in ("old", "new"):
            s = r[k]
            print(f"  {k.upper():4s} {_fmt(s)}  gap notes {s['notes_in_guitarless_gap']}  extra in held chords "
                  f"{s['extra_notes_in_held_chords']}  sustains {s['sustains_in_held_chords']}")
    if args.real:
        r = bench_real(args.real)
        results.append(r)
        print(json.dumps(r, indent=1))
    if folders:
        for k in ("old", "new", "oracle"):
            vals = [r[k] for r in results if k in r and "onset_f1" in r[k]]
            if vals:
                print(f"MEAN {k:6s} onset F1 {np.mean([v['onset_f1'] for v in vals]):.3f}  contour "
                      f"{np.mean([v['contour_direction_agreement'] for v in vals]):.3f}")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=2, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
