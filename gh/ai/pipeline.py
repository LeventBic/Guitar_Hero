"""Gitar kalibrasyonu boru hatti: stereo miks -> Demucs gitar ayristirma -> basic-pitch notalari ->
tempo/olcu/bolumler (tum miks, gh.autochart.analyze) -> gitardan chart (gh.autochart.guitar).

Gitar yoksa / cok zayifsa eski miks tabanli charter'a (gh.autochart.generate) duser ve `notice` doldurulur.
Ilerleme metinleri Ingilizce (gh.i18n.stage ile cevrilir); iptal: `cancel` (threading.Event) -> Cancelled.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from .runtime import Cancelled, check_cancel

SR = 44100
MAX_AI_SECONDS = 12 * 60.0          # daha uzun seslerde bellek (~1.5 GB) yerine miks modu
BP_MIN_NOTE_FRAMES = 7              # basic-pitch varsayilani 11 kare (128 ms); kisa pena / chug notalari icin ~81 ms
STAGES = ("Separating guitar", "Transcribing guitar notes", "Finding tempo and bars", "Placing notes",
          "Preparing difficulties")
# (baslangic, bitis) ilerleme oranlari; ayristirma toplam surenin buyuk kismi
SPANS = {"sep": (0.02, 0.74), "bp": (0.74, 0.80), "tempo": (0.80, 0.90), "place": (0.90, 0.94),
         "diff": (0.94, 0.995)}


@dataclass
class GuitarChartOutput:
    result: object                               # gh.autochart.ChartResult
    mode: str                                    # "guitar" | "mix"
    guitar: np.ndarray | None = None             # (2, L) 44.1 kHz ayristirilmis gitar
    backing: np.ndarray | None = None            # (2, L) diger kaynaklar
    sr: int = SR
    stats: object = None                         # gh.autochart.guitar.GuitarStats
    notice: str = ""                             # i18n anahtari (ornek: imp.no_guitar)
    timings: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)    # basic-pitch NoteEvent listesi (hata ayiklama / olcum)
    events: list = field(default_factory=list)   # GuitarEvent listesi
    lead_regions: list = field(default_factory=list)   # [(t0, t1)] s: lead cizgisi cikarilan solo bolgeleri


def resample_hq(x: np.ndarray, sr: int, target: int) -> np.ndarray:
    """FFT tabanli (bant sinirli) yeniden ornekleme, son eksen. Oynatma kalitesinde (48k -> 44.1k gibi)."""
    x = np.asarray(x, dtype=np.float32)
    if sr == target or x.shape[-1] == 0:
        return x
    n = x.shape[-1]
    m = int(round(n * target / sr))
    X = np.fft.rfft(x, axis=-1)
    k = m // 2 + 1
    if X.shape[-1] >= k:
        Y = X[..., :k]
    else:
        Y = np.zeros(X.shape[:-1] + (k,), dtype=X.dtype)
        Y[..., :X.shape[-1]] = X
    return (np.fft.irfft(Y, n=m, axis=-1) * (m / n)).astype(np.float32)


def to_stereo(samples: np.ndarray) -> np.ndarray:
    x = np.asarray(samples, dtype=np.float32)
    if x.ndim == 1:
        return np.stack([x, x])
    if x.shape[0] > 8 and x.shape[1] <= 8:
        x = x.T
    if x.shape[0] == 1:
        x = np.concatenate([x, x])
    return np.ascontiguousarray(x[:2])


def _sub(progress, key):
    lo, hi = SPANS[key]
    text = {"sep": STAGES[0], "bp": STAGES[1], "tempo": STAGES[2], "place": STAGES[3], "diff": STAGES[4]}[key]

    def cb(f, _t=None):
        if progress is not None:
            try:
                progress(lo + (hi - lo) * max(0.0, min(1.0, float(f))), text)
            except Exception:
                pass
    return cb


def chart_with_guitar(samples: np.ndarray, sr: int, *, title: str = "Unknown", artist: str = "Unknown",
                      album: str = "", year: str = "", genre: str = "", music_stream: str = "song.ogg",
                      progress=None, cancel=None, stems: tuple[np.ndarray, np.ndarray] | None = None,
                      threads: int | None = None, check: bool = True) -> GuitarChartOutput:
    """samples: (L,) / (L, ch) / (ch, L) float. stems: (gitar, backing) hazirsa ayristirma atlanir (R)."""
    from ..autochart import analyze, generate
    from ..autochart import dsp
    from ..autochart.guitar import GuitarInput, activity, build_events, generate_guitar, guitar_presence
    from . import basic_pitch
    from .demucs import separate

    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    x = to_stereo(samples)
    if sr != SR:
        x = resample_hq(x, sr, SR)
    meta = dict(title=title, artist=artist, album=album, year=year, genre=genre, music_stream=music_stream)
    # 1) ayristirma
    cb = _sub(progress, "sep")
    cb(0.0)
    if stems is None:
        st = separate(x, progress=cb, cancel=cancel, threads=threads)
        guitar, backing = st.guitar, st.backing
    else:
        guitar, backing = to_stereo(stems[0]), to_stereo(stems[1])
        n = min(guitar.shape[1], backing.shape[1], x.shape[1])
        guitar, backing, x = guitar[:, :n], backing[:, :n], x[:, :n]
        cb(1.0)
    timings["separation"] = time.perf_counter() - t0
    check_cancel(cancel)
    # 2) gitar notalari
    t1 = time.perf_counter()
    cb = _sub(progress, "bp")
    cb(0.0)
    g22 = dsp.resample(guitar.mean(axis=0), SR, 22050)
    notes, post = basic_pitch.transcribe(g22, progress=cb, cancel=cancel, threads=threads,
                                         min_note_len=BP_MIN_NOTE_FRAMES)
    timings["transcription"] = time.perf_counter() - t1
    check_cancel(cancel)
    # 3) tempo / olcu / bolumler (tum miks)
    t2 = time.perf_counter()
    mix_mono = x.mean(axis=0)
    an = analyze(mix_mono, SR, progress=_sub(progress, "tempo"))
    timings["analysis"] = time.perf_counter() - t2
    check_cancel(cancel)
    # 4) gitar olaylari + varlik karari
    t3 = time.perf_counter()
    place = _sub(progress, "place")
    place(0.0)
    m22 = dsp.resample(mix_mono, SR, 22050)
    n = min(g22.size, m22.size)
    gi = GuitarInput(audio=g22[:n], sr=22050, mix=m22[:n], notes=notes, note_post=post["note"],
                     onset_post=post["onset"], post_times=basic_pitch.model_frames_to_time(post["note"].shape[0]),
                     mix_onsets=[(o.time, o.strength) for o in an.onsets])
    act_t, act, gdb = activity(gi)
    pa = dsp.PitchAnalyzer(g22[:n] / max(float(np.abs(g22[:n]).max()), 1e-9))
    lead: list = []
    events = build_events(gi, act_t, act, pa, lead_out=lead)
    stats = guitar_presence(events, act, gdb, an.duration)
    place(1.0)
    check_cancel(cancel)
    out = GuitarChartOutput(result=None, mode="mix", sr=SR, stats=stats, notes=notes, events=events,
                            lead_regions=list(lead))
    diff = _sub(progress, "diff")
    res = None
    if stats.present:
        try:
            res = generate_guitar(an, events, progress=diff, check=check, lead_regions=lead, **meta)
            out.mode = "guitar"
            out.guitar, out.backing = guitar, backing
        except (ValueError, RuntimeError) as exc:
            stats.present = False
            stats.reason = f"guitar chart failed: {exc}"
    if res is None:
        res = generate(mix_mono, SR, analysis=an, progress=diff, check=check, **meta)
        out.notice = "imp.no_guitar"
    out.result = res
    timings["charting"] = time.perf_counter() - t3
    timings["total"] = time.perf_counter() - t0
    out.timings = timings
    return out


__all__ = ["chart_with_guitar", "GuitarChartOutput", "Cancelled", "STAGES", "resample_hq", "MAX_AI_SECONDS"]
