"""Gitar kalibrasyonu: numpy STFT (Demucs kurallari), parca plani, akor / perde merdiveni kurallari, gercek gitar
stem'i verilerek (ayristirma atlanir) gitardan chart, gitarsiz geri donus, uctan uca AI ice aktarma + yeniden chart
ve iptal. Model dosyalari / onnxruntime yoksa AI testleri atlanir."""
from __future__ import annotations

import os
import sys
import threading

import numpy as np
import pytest

from audio_synth import write_wav
from gh.ai import models_available
from gh.chart import load_song, parse_chart

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AI_OK, AI_WHY = models_available()
needs_ai = pytest.mark.skipif(not AI_OK, reason=f"guitar AI unavailable: {AI_WHY}")


# --------------------------------------------------------------------------- saf numpy parcalar

def test_demucs_spec_roundtrip():
    from gh.ai.spec import demucs_ispec, demucs_spec
    # Demucs Nyquist bandini ve kenardaki 2 kareyi atar: bant sinirli sinyal, ic bolgede birebir geri donmeli
    t = np.arange(44100) / 44100
    rng = np.random.default_rng(0)
    x = sum(a * np.sin(2 * np.pi * f * t + p) for a, f, p in
            zip(rng.uniform(0.02, 0.1, 12), rng.uniform(60, 12000, 12), rng.uniform(0, 6, 12)))
    x = np.stack([x, x[::-1]]).astype(np.float32)
    z = demucs_spec(x)
    assert z.shape == (2, 2048, int(np.ceil(x.shape[-1] / 1024)))
    y = demucs_ispec(z, x.shape[-1])
    assert np.max(np.abs(y - x)[:, 2048:-2048]) < 1e-4


def test_chunk_plan_covers_everything():
    from gh.ai.demucs import SEGMENT, chunk_plan
    n = int(SEGMENT * 3.3)
    plan = chunk_plan(n)
    covered = np.zeros(n, bool)
    for off, ln in plan:
        assert 0 < ln <= SEGMENT
        covered[off:off + ln] = True
    assert covered.all() and plan[0][0] == 0


@pytest.mark.parametrize("pitches,size", [
    ([40], 1), ([40, 52], 1), ([40, 52, 59], 1),          # tek nota, oktav, harmonikler
    ([40, 47], 2), ([40, 47, 52], 2), ([45, 50], 2),       # power chord (kvint / kvart)
    ([40, 44, 47], 3), ([43, 47, 50, 55], 3),              # uclu akorlar
])
def test_chord_size(pitches, size):
    from gh.autochart.guitar import chord_size
    assert chord_size(pitches) == size


def test_ladder_frets_monotone_and_consistent():
    from gh.autochart.guitar import ladder_frets
    vals = [40, 43, 45, 43, 40, 52]
    low = ladder_frets(vals, 0.0)
    high = ladder_frets(vals, 1.0)
    for fr in (low, high):
        assert all(0 <= f <= 4 for f in fr)
        m = dict(zip(vals, fr))
        assert all(m[v] == f for v, f in zip(vals, fr))                  # ayni perde = ayni tus
        assert m[40] < m[43] < m[45] < m[52]                              # yukari = yukari
    assert min(low) == 0 and max(high) == 4                               # register ortalamasi
    with pytest.raises(ValueError):
        ladder_frets([40, 41, 42, 43, 44, 45], 0.5)


def _fake_lead_input(transcribed_lead: bool):
    """30 s: 10-25 s arasi 8 nota/s yuksek perdeli (E minor) lead onset tepeleri + surekli alcak chug notalari.
    transcribed_lead=True ise lead notalari basic-pitch notasi olarak da vardir (zayif lead degil)."""
    from types import SimpleNamespace as NS

    from gh.autochart.guitar import GuitarInput
    fps = 86.0
    times = np.arange(int(30 * fps)) / fps
    onset = np.zeros((times.size, 88), np.float32)
    note = np.zeros_like(onset)
    notes = [NS(start=t, end=t + 0.1, pitch=40, amplitude=0.6, onset=True) for t in np.arange(0.5625, 30, 0.125)]
    scale = [76, 79, 81, 83, 81, 79, 74, 76]
    lead = [(t, scale[k % len(scale)]) for k, t in enumerate(np.arange(10.0, 25.0, 0.125))]
    for t, p in lead:
        i = int(round(t * fps))
        onset[i, p - 21] = 0.45
        note[i:i + 8, p - 21] = 0.2                              # esigin (0.3) altinda: basic-pitch nota yazmaz
        if transcribed_lead:
            notes.append(NS(start=t, end=t + 0.1, pitch=p, amplitude=0.5, onset=True))
    gi = GuitarInput(audio=np.zeros(22050 * 30, np.float32), sr=22050, mix=np.zeros(22050 * 30, np.float32),
                     notes=sorted(notes, key=lambda n: n.start), note_post=note, onset_post=onset, post_times=times)
    return gi, lead


def test_weak_lead_region_and_line():
    from gh.autochart.guitar import apply_lead, weak_lead_regions
    gi, lead = _fake_lead_input(False)
    regions = weak_lead_regions(gi)
    assert len(regions) == 1
    a, b = regions[0]
    assert 9.5 < a < 10.5 and 24.5 < b < 25.5
    chugs = [_ev(t, 40) for t in np.arange(0.5, 30, 0.125)]
    out = apply_lead(gi, chugs, regions, lambda t: True)
    inside = [e for e in out if a <= e.time <= b]
    assert inside and all(e.root >= 70 for e in inside)            # bolgede chug yok, lead var
    assert len(inside) >= 0.9 * len(lead)
    it = np.array([e.time for e in inside])
    ok = sum(inside[int(np.argmin(np.abs(it - t)))].root == p and np.min(np.abs(it - t)) < 0.012 for t, p in lead)
    assert ok >= 0.9 * len(lead)
    assert [e for e in out if e.time < a and e.root == 40]            # bolge disinda ritim kalir
    # transkribe edilmis lead zayif degildir
    gi2, _ = _fake_lead_input(True)
    assert weak_lead_regions(gi2) == []


def test_drop_pitch_spikes():
    from gh.autochart.guitar import _drop_pitch_spikes
    line = [(i * 0.1, p, 0.5) for i, p in enumerate([76, 79, 81, 55, 79, 76, 103, 79, 81, 88])]
    out = [p for _t, p, _v in _drop_pitch_spikes(line)]
    assert out == [76, 79, 81, 79, 79, 76, 79, 79, 81, 88]           # oktav hatalari komsulara tasinir
    line = [(i * 0.1, p, 0.5) for i, p in enumerate([76, 79, 81, 76, 79, 97, 81, 79, 76])]
    assert 97 not in [p for _t, p, _v in _drop_pitch_spikes(line)]   # oktavla da yaklasmayan sicrama atilir


def _ev(t, p):
    from gh.autochart.guitar import GuitarEvent
    return GuitarEvent(time=float(t), strength=0.6, pitches=[p], root=float(p), size=1, end=float(t) + 0.1)


# --------------------------------------------------------------------------- boru hatti (ayristirma atlanir)

@pytest.fixture(scope="module")
def realmix():
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    from realistic_mix import make_mix
    return make_mix()


def _expert(text):
    return parse_chart(text).tracks["expert"].notes


@needs_ai
def test_guitar_chart_from_true_stem(realmix):
    from gh.ai import pipeline
    m = realmix
    out = pipeline.chart_with_guitar(m.mix, m.sr, title="Synth Rock", artist="RIFF", stems=(m.guitar, m.backing))
    assert out.mode == "guitar" and out.stats.present, out.stats
    notes = _expert(out.result.text)
    ev_t = np.array([e[0] for e in m.events])
    times = np.array([n.time for n in notes])
    hit = sum(np.min(np.abs(times - t)) <= 0.05 for t in ev_t)
    prec = sum(np.min(np.abs(ev_t - t)) <= 0.05 for t in times) / max(len(times), 1)
    assert hit / len(ev_t) > 0.6 and prec > 0.8, (hit / len(ev_t), prec)
    for s0, s1 in m.silent:                                             # gitarsiz arada nota yok
        assert not [n for n in notes if s0 + 0.2 <= n.time <= s1 - 0.1]
    assert any(n.is_chord for n in notes) and any(not n.is_chord for n in notes)
    assert any(n.has_sustain for n in notes)                            # uzun power chord'lar
    assert out.result.validation and all(ok for ok, _m in out.result.validation.values())


@needs_ai
def test_no_guitar_falls_back_to_mix(realmix):
    from gh.ai import pipeline
    m = realmix
    silent = np.zeros_like(m.guitar)
    out = pipeline.chart_with_guitar(m.backing, m.sr, stems=(silent, m.backing))
    assert out.mode == "mix" and out.notice == "imp.no_guitar" and out.guitar is None
    assert not out.stats.present and out.stats.reason
    assert len(_expert(out.result.text)) > 20


# --------------------------------------------------------------------------- uctan uca ice aktarma

@pytest.fixture()
def mixer():
    pygame = pytest.importorskip("pygame")
    os.environ["SDL_AUDIODRIVER"] = "dummy"
    if not pygame.mixer.get_init():
        pygame.mixer.init(44100, -16, 2, 1024)
    return pygame


@needs_ai
def test_import_and_rechart_in_guitar_mode(tmp_path, realmix, mixer):
    from gh.importer import import_audio, rechart_song
    src = tmp_path / "Synth Band - Distorted.wav"
    write_wav(str(src), _as_wav(realmix))
    info: dict = {}
    folder = import_audio(str(src), str(tmp_path / "Songs"), info=info)
    assert info["mode"] == "guitar", info
    names = set(os.listdir(folder))
    assert {"guitar.ogg", "song.ogg", "notes.chart", "song.ini", "album.png"} <= names
    assert not any(n.endswith(".wav") for n in names)                    # miks kopyalanmaz: stem toplami = miks
    ini = open(os.path.join(folder, "song.ini"), encoding="utf-8").read()
    assert "auto_chart_mode = guitar" in ini and "auto_chart_version = 2" in ini
    song = load_song(folder)
    assert song.info.stems["guitar"].endswith("guitar.ogg") and song.info.stems["song"].endswith("song.ogg")
    assert set(song.tracks) == {"easy", "medium", "hard", "expert"}
    # yeniden chart: mevcut stem'ler kullanilir (ayristirma yok)
    info2: dict = {}
    rechart_song(folder, info=info2)
    assert info2["mode"] == "guitar" and info2["timings"]["separation"] < 1.0
    assert os.path.exists(os.path.join(folder, "notes.chart.bak"))
    assert len(load_song(folder).tracks["expert"].notes) > 50


@needs_ai
def test_import_cancel_leaves_nothing(tmp_path, realmix, mixer):
    from gh.ai import Cancelled
    from gh.importer import import_audio
    src = tmp_path / "Band - Cancelled.wav"
    write_wav(str(src), _as_wav(realmix))
    ev = threading.Event()

    def prog(f, _t):
        if f > 0.05:
            ev.set()
    songs = tmp_path / "Songs"
    with pytest.raises(Cancelled):
        import_audio(str(src), str(songs), prog, cancel=ev)
    assert not songs.exists() or os.listdir(songs) == []


def _as_wav(m):
    """audio_synth.write_wav mono SynthSong bekler: stereo miksin ortalamasi (Demucs mono girdiyi de isler)."""
    from audio_synth import SynthSong
    return SynthSong(samples=m.mix.mean(axis=0), sr=m.sr, beats=np.array([]), drum_onsets=np.array([]), melody=[])
