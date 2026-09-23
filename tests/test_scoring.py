"""Taban skor, yildizlar ve autoplay (bot) testleri."""
from __future__ import annotations

import pytest

from gh.config import EngineConfig
from gh.engine import EvType, GuitarEngine, autoplay_inputs, base_score, star_thresholds, stars
from gh.engine.rules import sustain_ends

from engine_testkit import B, G, H, O, OPEN, R, S, T, Y, make_chart, of, random_chart


def _play(chart, track, cfg=None, **kw):
    cfg = cfg or EngineConfig()
    e = GuitarEngine(chart, track, cfg)
    for x in autoplay_inputs(track, cfg, **kw):
        e.push(x)
    e.update(chart.end_time + 5.0)
    return e, e.pop_events()


MIXED = [
    (4, G), (4.5, R, H), (5, Y, H), (5.25, R, H), (6, G | R, S, 2, 0), (8, B, S, 0, 0), (9, OPEN),
    (9.5, OPEN, H), (10, O, T), (10.25, O, T), (10.5, Y, T), (11, G, S, 4), (12, R), (13, Y, H),
    (14, B, S, 1, 1), (14.5, R), (15, R | Y | B, S, 2, 1), (17, G, S, 1.33), (18, OPEN, S, 2, 2),
    (19, G), (20, R, S, 0.5), (20.25, R), (21, G | Y), (21.5, G | Y, T), (22, Y, S, 8, 3), (24, B), (26, O),
] + [(28 + k * 0.5, [G, R, Y, B, O][k % 5], H if k % 5 else S, 0.75 if k % 7 == 0 else 0, 4 if 10 <= k < 14 else -1)
     for k in range(40)]


def test_base_score_30_notes():
    chart, track = make_chart([(4 + k, G) for k in range(30)])
    assert base_score(track, chart.tempo_map, EngineConfig()) == 3000


def test_base_score_sustains():
    chart, track = make_chart([(4, G, S, 2)])
    assert base_score(track, chart.tempo_map) == 100
    chart, track = make_chart([(4, G | R | Y, S, 2)])
    assert base_score(track, chart.tempo_map) == 150 + 50


def test_base_score_sustain_uses_multiplier_after_hit():
    # 10. nota sustain'li: nota 1x, sustain'i 2x (combo 10 oldu)
    chart, track = make_chart([(4 + k, G, S, 2 if k == 9 else 0) for k in range(10)])
    assert base_score(track, chart.tempo_map) == 10 * 50 + 2 * 50


def test_sustain_cut_by_conflicting_note():
    chart, track = make_chart([(4, R, S, 4), (5, G), (6, Y, S, 4), (7, B)])
    ends, cuts = sustain_ends(track.notes)
    assert cuts[0] == 1 and ends[0] == pytest.approx(2.5)     # G, R'den alcak: catisir
    assert cuts[2] == -1 and ends[2] == pytest.approx(5.0)    # B, Y'den yuksek: extended


def test_autoplay_full_combo_score_equals_base_without_sp():
    chart, track = make_chart(MIXED)
    e, ev = _play(chart, track, use_star_power=False)
    assert e.notes_hit == e.total_notes == len(MIXED)
    assert e.overstrums == 0 and e.notes_missed == 0 and e.max_combo == len(MIXED)
    assert all(x.value == 1.0 for x in of(ev, EvType.SUSTAIN_END))
    assert e.score == e.base_score
    assert all(abs(o) < 1e-9 for o in e.hit_offsets)


@pytest.mark.parametrize("seed", range(8))
def test_autoplay_random_charts(seed):
    chart, track = random_chart(seed)
    e, ev = _play(chart, track, use_star_power=False)
    assert e.overstrums == 0 and e.notes_missed == 0
    assert e.notes_hit == e.total_notes and e.max_combo == e.total_notes
    assert all(x.value == 1.0 for x in of(ev, EvType.SUSTAIN_END))
    assert e.score == e.base_score
    e2, ev2 = _play(chart, track, use_star_power=True)
    assert e2.overstrums == 0 and e2.notes_missed == 0 and e2.notes_hit == e2.total_notes
    if of(ev2, EvType.SP_ACTIVATED):
        assert e2.score > e2.base_score


def test_autoplay_with_star_power():
    chart, track = make_chart(MIXED)
    e, ev = _play(chart, track, use_star_power=True)
    assert e.notes_hit == e.total_notes and e.overstrums == 0
    assert of(ev, EvType.SP_ACTIVATED)
    assert all(e.sp_phrase_ok)
    assert e.score > e.base_score


def test_autoplay_whammy_gains_sp():
    chart, track = make_chart([(4, G, S, 8, 0)])
    e, _ = _play(chart, track, use_star_power=False)
    assert e.sp_meter == pytest.approx(0.25 + 8 / 30, abs=1e-3)


def test_star_thresholds_and_fraction():
    base = 10000
    assert star_thresholds(base) == [600, 1200, 2000, 4700, 7800, 11500]
    assert stars(0, base) == 0.0
    assert stars(300, base) == pytest.approx(0.5)
    assert stars(600, base) == pytest.approx(1.0)
    assert stars(1200, base) == pytest.approx(2.0)
    assert stars(1600, base) == pytest.approx(2.5)
    assert stars(7800, base) == pytest.approx(5.0)
    assert stars(11499, base) < 6.0
    assert stars(11500, base) == 6.0 and stars(50000, base) == 6.0
    assert stars(100, 0) == 0.0


def test_engine_stars_after_perfect_run():
    chart, track = make_chart(MIXED)
    e, _ = _play(chart, track, use_star_power=False)
    assert e.stars() == pytest.approx(5 + (1.0 - 0.78) / (1.15 - 0.78), abs=1e-3)
