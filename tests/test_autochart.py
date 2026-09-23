"""Otomatik chart uretici: sentetik muzikte tempo / vurus / onset dogrulugu, chart kurallari, bot full combo,
determinizm. (Gercek muzik olcumu: tools/benchmark_autochart.py)"""
from __future__ import annotations

import os
import subprocess
import sys

import numpy as np
import pytest

from audio_synth import render_song
from gh.autochart import analyze, estimate_difficulty, generate, pick_preview_start
from gh.autochart import charter
from gh.chart import parse_chart
from gh.config import EngineConfig
from gh.engine import GuitarEngine, autoplay_inputs

TEMPOS = (96.0, 128.0, 174.0)


def match(est, ref, tol=0.05) -> int:
    """Acgozlu birebir eslesme sayisi."""
    est = np.sort(np.asarray(est))
    used = np.zeros(est.size, bool)
    hit = 0
    for r in np.sort(np.asarray(ref)):
        d = np.abs(est - r)
        d[used] = np.inf
        i = int(np.argmin(d)) if d.size else -1
        if i >= 0 and d[i] <= tol:
            used[i] = True
            hit += 1
    return hit


_cache: dict = {}


def song_and_result(bpm, end_bpm=None, bars=16):
    key = (bpm, end_bpm, bars)
    if key not in _cache:
        s = render_song(bpm, bars, 22050, end_bpm=end_bpm)
        an = analyze(s.samples, s.sr)
        res = generate(s.samples, s.sr, title="Synth", artist="Test", analysis=an)
        _cache[key] = (s, an, res)
    return _cache[key]


@pytest.mark.parametrize("bpm", TEMPOS)
def test_tempo_and_beats(bpm):
    s, an, _res = song_and_result(bpm)
    assert abs(an.tempo - bpm) / bpm < 0.01, (an.tempo, an.tempo_candidates)   # oktav hatasi yok
    inside = s.beats[(s.beats >= an.beats[0] - 0.03) & (s.beats <= an.beats[-1] + 0.03)]
    assert inside.size >= 0.9 * s.beats.size
    err = np.array([np.min(np.abs(an.beats - t)) for t in inside])
    assert err.max() < 0.020, err.max()


def test_tempo_drift_is_followed():
    s, an, res = song_and_result(110.0, end_bpm=130.0)
    err = np.array([np.min(np.abs(an.beats - t)) for t in s.beats])
    assert err.max() < 0.020, err.max()
    tm = parse_chart(res.text).tempo_map
    assert tm.bpm_at(s.beats[4]) < 116 and tm.bpm_at(s.beats[-4]) > 124


@pytest.mark.parametrize("bpm", TEMPOS)
def test_onset_precision_recall(bpm):
    s, an, _res = song_and_result(bpm)
    ot = [o.time for o in an.onsets]
    ref = s.all_onsets
    hit = match(ot, ref)
    assert hit / len(ot) >= 0.9 and hit / len(ref) >= 0.9, (hit, len(ot), len(ref))


def _bot_full_combo(chart, diff) -> tuple[bool, str]:
    tr = chart.tracks[diff]
    cfg = EngineConfig()
    eng = GuitarEngine(chart, tr, cfg)
    for ev in autoplay_inputs(tr, cfg):
        eng.push(ev)
    eng.update(chart.end_time + 5)
    ok = eng.notes_hit == eng.total_notes and eng.overstrums == 0 and eng.notes_missed == 0
    return ok, f"{diff}: hit {eng.notes_hit}/{eng.total_notes} over {eng.overstrums}"


@pytest.mark.parametrize("bpm", TEMPOS)
def test_chart_rules_and_bot_full_combo(bpm):
    s, an, res = song_and_result(bpm)
    chart = parse_chart(res.text)
    counts = {}
    for diff in ("easy", "medium", "hard", "expert"):
        assert diff in chart.tracks
        notes = chart.tracks[diff].notes
        counts[diff] = len(notes)
        ok, msg = _bot_full_combo(chart, diff)
        assert ok, msg
        ticks = [n.tick for n in notes]
        assert len(set(ticks)) == len(ticks) and ticks == sorted(ticks)
        assert notes[0].time >= 1.5                              # sayim suresi
        for n in notes:
            assert n.mask != 0                                   # acik nota uretilmez
            assert n.length_ticks == 0 or n.length_ticks >= 96   # sifira yakin sustain yok
        for a, b in zip(notes, notes[1:]):                       # sustain sonraki notadan once biter
            if a.length_ticks:
                assert a.tick + a.length_ticks <= b.tick - 24
        if diff == "easy":
            assert all(n.mask < 8 and not n.is_chord for n in notes)     # yalniz G/R/Y, tek nota
        if diff == "medium":
            assert all(n.mask < 16 for n in notes)                       # turuncu yok
            assert all(bin(n.mask).count("1") <= 2 for n in notes)
        if diff == "hard":
            assert all(bin(n.mask).count("1") <= 2 for n in notes)
        phrases = chart.tracks[diff].sp_phrases
        assert 1 <= len(phrases) <= 8
        for p in phrases:
            assert 4 <= p.last_note - p.first_note + 1 <= 8
    assert counts["easy"] < counts["medium"] < counts["hard"] < counts["expert"]
    assert 0.2 <= counts["easy"] / counts["expert"] <= 0.4
    assert 0.4 <= counts["medium"] / counts["expert"] <= 0.6
    assert 0.6 <= counts["hard"] / counts["expert"] <= 0.8
    assert all(ok for ok, _m in res.validation.values())


def test_tempo_map_tick0_is_audio0_and_beats_on_ticks():
    s, an, res = song_and_result(128.0)
    events, ts, grid, shift = charter.build_tempo_map(an)
    tm = parse_chart(res.text).tempo_map
    assert tm.tick_to_time(0) == 0.0 and events[0][0] == 0
    for i, b in enumerate(an.beats):
        assert abs(tm.tick_to_time((i + shift) * 192) - b) < 0.001
    # olcu cizgileri tespit edilen olcu baslarinda
    bars = [l.time for l in tm.beat_lines(an.duration) if l.kind == 0]
    for t in an.beats[an.downbeat::4][:6]:
        assert min(abs(t - x) for x in bars) < 0.002


def test_chart_has_sections_end_and_metadata():
    _s, an, res = song_and_result(128.0)
    chart = parse_chart(res.text)
    assert chart.sections and all(sec.name for sec in chart.sections)
    assert chart.info.name == "Synth" and chart.info.artist == "Test" and chart.info.charter == "RIFF Auto"
    assert "E \"end\"" in res.text
    assert chart.end_time >= max(n.end_time for n in chart.tracks["expert"].notes)
    assert 0 <= estimate_difficulty(res) <= 6
    assert estimate_difficulty(res.text) == estimate_difficulty(res)
    pv = pick_preview_start(an)
    assert 0 <= pv <= int(an.duration * 1000)


def test_determinism():
    s = render_song(128.0, 12, 22050, seed=7)
    a = generate(s.samples, s.sr, title="Same", artist="Input").text
    b = generate(s.samples.copy(), s.sr, title="Same", artist="Input").text
    assert a == b


def test_resampling_and_stereo_input():
    """44.1 kHz stereo int16 girdi (importer'in pygame'den aldigi bicim) ayni tempoyu verir."""
    s = render_song(128.0, 12, 44100)
    st = np.repeat((s.samples * 32767).astype(np.int16)[:, None], 2, axis=1)
    an = analyze(st, 44100)
    assert abs(an.tempo - 128.0) < 1.28


def test_triplet_quantization():
    from gh.autochart.analysis import Analysis, Onset
    beats = 2.0 + np.arange(40) * 0.5
    # 4 vurus boyunca 8'lik uclemeler, sonra 2 vurus 16'liklar
    onsets = [Onset(time=float(beats[k] + q * 0.5 / 3), strength=0.8, raw=1.0) for k in range(8, 12) for q in (0, 1, 2)]
    onsets += [Onset(time=float(beats[k] + q * 0.125), strength=0.8, raw=1.0) for k in range(14, 16) for q in (0, 1, 2, 3)]
    an = Analysis(duration=25.0, tempo=120.0, beats=beats, downbeat=0, onsets=onsets)
    events, ts, _grid, shift = charter.build_tempo_map(an)
    tm = charter.tempo_map_from(events, ts)
    notes = charter.quantize(an, tm, 0, 10 ** 9)
    rel = sorted({n.tick % 192 for n in notes})
    assert 64 in rel and 128 in rel            # uclemeler
    assert 48 in rel and 96 in rel and 144 in rel   # 16'liklar
    assert all(n.triplet == (n.tick % 192 in (64, 128)) for n in notes)


def test_fret_assignment_follows_contour():
    pitches = [60, 60, 62, 64, 65, 67, 67, 65, 64, 62, 60, 72, 71, 69]
    frets = charter.assign_frets(pitches, 5)
    for (p1, f1), (p2, f2) in zip(zip(pitches, frets), zip(pitches[1:], frets[1:])):
        if p2 == p1:
            assert f2 == f1
        elif abs(p2 - p1) < 7:
            assert np.sign(f2 - f1) in (np.sign(p2 - p1), 0)
    assert min(frets) == 0 and max(frets) >= 3
    assert all(0 <= f <= 2 for f in charter.assign_frets(pitches, 3))


def test_autochart_does_not_import_pygame():
    code = ("import sys; import gh.autochart, gh.autochart.charter; "
            "print('pygame' in sys.modules)")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"
