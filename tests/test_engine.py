"""GuitarEngine mekanik testleri (Clone Hero semantigi, YARG leniency). 120 BPM: 1 beat = 0.5 s; beat 4 = 2.0 s."""
from __future__ import annotations

import pytest

from gh.config import EngineConfig
from gh.engine import EvType, GuitarEngine, InputEvent, InputKind, autoplay_inputs
from gh.models import Solo
from gh.timing import TimeSignature

from engine_testkit import (B, G, H, O, OPEN, R, S, T, Y, down, engine, hold, make_chart, of, open_strum,
                            release, run, sp, strum, up, whammy)


# ---------------------------------------------------------------- hit window

def test_on_time_hit():
    e = engine([(4, G)])
    ev = run(e, [down(1.9, 0), strum(2.0)], 3.0)
    hits = of(ev, EvType.HIT)
    assert len(hits) == 1 and hits[0].note == 0 and hits[0].offset == pytest.approx(0.0)
    assert e.score == 50 and e.combo == 1 and e.note_state == [1]
    assert e.overstrums == 0 and e.notes_missed == 0


def test_late_69ms_hits():
    e = engine([(4, G)])
    ev = run(e, [down(1.9, 0), strum(2.069)], 3.0)
    assert of(ev, EvType.HIT)[0].offset == pytest.approx(0.069)
    assert e.hit_offsets == [pytest.approx(0.069)]


def test_late_71ms_misses_then_overstrum():
    e = engine([(4, G)])
    ev = run(e, [down(1.9, 0), strum(2.071)], 3.0)
    assert e.note_state == [2] and e.notes_missed == 1 and e.notes_hit == 0
    kinds = [x.type for x in ev if x.type in (EvType.MISS, EvType.OVERSTRUM)]
    assert kinds == [EvType.MISS, EvType.OVERSTRUM]
    assert e.score == 0


def test_early_69ms_hits():
    e = engine([(4, G)])
    ev = run(e, [down(1.8, 0), strum(1.931)], 3.0)
    assert of(ev, EvType.HIT)[0].offset == pytest.approx(-0.069)


def test_early_71ms_not_hit_at_strum_time_but_strum_leniency_hits_on_window_entry():
    e = engine([(4, G)])
    for x in [down(1.8, 0), strum(1.929)]:
        e.push(x)
    e.update(1.9295)
    assert e.note_state == [0]          # strum aninda pencere disinda: vurus yok
    ev = e.pop_events()
    assert not of(ev, EvType.HIT)
    e.update(3.0)
    ev = e.pop_events()
    hits = of(ev, EvType.HIT)
    assert len(hits) == 1 and hits[0].offset == pytest.approx(-0.070, abs=1e-6)
    assert e.overstrums == 0


def test_early_71ms_wrong_frets_overstrums_after_leniency():
    e = engine([(4, G)])
    ev = run(e, [strum(1.929)], 1.99)   # perde yok: pencereye girince eslesmiyor
    assert e.note_state == [0] and e.overstrums == 1
    assert of(ev, EvType.OVERSTRUM)[0].time == pytest.approx(1.979)
    ev = run(e, [down(2.0, 0), strum(2.01)], 3.0)   # nota hala vurulabilir
    assert e.note_state == [1]


def test_strum_far_too_early_overstrums_and_note_still_hittable():
    e = engine([(4, G)])
    ev = run(e, [down(1.8, 0), strum(1.87)], 1.95)
    assert e.overstrums == 1 and e.note_state == [0]
    run(e, [strum(2.0)], 3.0)
    assert e.note_state == [1]


def test_strum_then_fret_within_small_leniency_hits():
    e = engine([(4, G)])
    ev = run(e, [strum(2.0), down(2.02, 0)], 3.0)
    assert e.note_state == [1] and e.overstrums == 0
    assert of(ev, EvType.HIT)[0].offset == pytest.approx(0.02)


def test_strum_then_fret_after_small_leniency_overstrums():
    e = engine([(4, G)])
    ev = run(e, [strum(2.0), down(2.03, 0)], 3.0)
    assert e.overstrums == 1 and e.note_state == [2]


def test_input_before_timeout_is_processed_chronologically():
    # 60 BPM, res 1000: 1 beat = 1 s, tick = ms. Nota0 miss zaman asimi 0.98, nota1 1.05.
    specs = [(0.91, G), (0.98, R)]
    for step in (None, 0.001):
        e = engine(specs, bpm=60.0, res=1000)
        for x in hold(0.95, R) + [strum(1.00)]:
            e.push(x)
        if step is None:
            e.update(5.0)
        else:
            t = 0.0
            while t < 5.0:
                t += step
                e.update(t)
        ev = [x for x in e.pop_events() if x.type in (EvType.HIT, EvType.MISS)]
        assert [(x.type, x.note) for x in ev] == [(EvType.MISS, 0), (EvType.HIT, 1)]
        assert ev[1].offset == pytest.approx(0.02)


def test_oldest_note_is_target_no_skipping():
    e = engine([(4, G), (4.0625, R)])
    ev = run(e, hold(1.9, R) + [strum(2.03125)], 3.0)
    assert e.note_state[0] == 2
    assert not [x for x in of(ev, EvType.HIT) if x.note == 1 and x.time == pytest.approx(2.03125)]


# ------------------------------------------------------------ fret kurallari

def test_anchoring_lower_frets_allowed():
    e = engine([(4, R)])
    run(e, hold(1.9, G | R) + [strum(2.0)], 3.0)
    assert e.note_state == [1]


def test_higher_fret_held_fails_single_note():
    e = engine([(4, R)])
    run(e, hold(1.9, R | Y) + [strum(2.0)], 3.0)
    assert e.note_state == [2] and e.overstrums == 1


def test_chord_exact_match_required():
    e = engine([(4, G | R)])
    run(e, hold(1.9, G | R) + [strum(2.0)], 3.0)
    assert e.note_state == [1] and e.score == 100


@pytest.mark.parametrize("held", [G | R | Y, G, R | Y])
def test_chord_with_extra_or_missing_fret_fails(held):
    e = engine([(4, G | R)])
    run(e, hold(1.9, held) + [strum(2.0)], 3.0)
    assert e.note_state == [2]


def test_open_note_needs_no_frets():
    e = engine([(4, OPEN)])
    run(e, [strum(2.0)], 3.0)
    assert e.note_state == [1]
    e2 = engine([(4, OPEN)])
    run(e2, hold(1.9, G) + [strum(2.0)], 3.0)
    assert e2.note_state == [2]


def test_open_strum_ignores_held_frets():
    e = engine([(4, OPEN), (5, G)])
    run(e, hold(1.9, G) + [open_strum(2.0)], 2.2)
    assert e.note_state[0] == 1
    # OPEN_STRUM perdeli notayi vuramaz
    run(e, [open_strum(2.5)], 3.0)
    assert e.note_state[1] == 2 and e.overstrums == 1


# ------------------------------------------------------------- HOPO / tap

def test_hopo_hammer_on_with_combo():
    e = engine([(4, G), (4.5, R, H)])
    ev = run(e, [down(1.9, 0), strum(2.0), down(2.25, 1)], 3.0)
    assert e.note_state == [1, 1] and e.overstrums == 0
    assert of(ev, EvType.HIT)[1].offset == pytest.approx(0.0)


def test_hopo_with_zero_combo_needs_strum():
    e = engine([(4, R, H)])
    run(e, [down(2.0, 1)], 2.01)
    assert e.note_state == [0]
    run(e, [strum(2.02)], 3.0)
    assert e.note_state == [1]


def test_hopo_after_miss_needs_strum():
    e = engine([(4, G), (5, R, H)])
    run(e, [down(2.49, 1)], 2.52)   # nota0 kacti -> combo 0, HOPO perdeyle vurulamaz
    assert e.note_state == [2, 0]
    run(e, [strum(2.53)], 3.0)
    assert e.note_state == [2, 1]


def test_pull_off_by_release():
    e = engine([(4, R), (4.5, G, H)])
    ev = run(e, hold(1.9, G | R) + [strum(2.0), up(2.25, 1)], 3.0)
    assert e.note_state == [1, 1] and e.overstrums == 0


def test_strum_after_fretted_hopo_within_leniency_is_swallowed():
    e = engine([(4, G), (4.5, R, H)])
    run(e, [down(1.9, 0), strum(2.0), down(2.25, 1), strum(2.30)], 3.0)
    assert e.note_state == [1, 1] and e.overstrums == 0 and e.combo == 2


def test_strum_after_hopo_leniency_expired_overstrums():
    e = engine([(4, G), (4.5, R, H)])
    run(e, [down(1.9, 0), strum(2.0), down(2.25, 1), strum(2.35)], 3.0)
    assert e.note_state == [1, 1] and e.overstrums == 1 and e.combo == 0


def test_strum_can_hit_hopo_normally():
    e = engine([(4, G), (4.5, R, H)])
    run(e, [down(1.9, 0), strum(2.0), down(2.2, 1)], 2.21)
    assert e.note_state == [1, 1]   # 2.2 pencerede: perdeyle vuruldu
    e2 = engine([(4, G), (4.5, R, H)])
    run(e2, [down(1.9, 0), strum(2.0), up(2.1, 0), down(2.1, 1), strum(2.25)], 3.0)
    assert e2.note_state == [1, 1] and e2.overstrums == 0   # pencere oncesi perde, strum ile vurus


def test_tap_without_combo():
    e = engine([(4, Y, T)])
    run(e, [down(2.0, 2)], 3.0)
    assert e.note_state == [1] and e.overstrums == 0


def test_anti_ghosting_blocks_hopo_after_wrong_fret():
    specs = [(4, G), (4.5, Y, H)]
    inputs = [down(1.9, 0), strum(2.0), down(2.24, 3), down(2.245, 2), up(2.25, 3)]
    e = engine(specs)
    run(e, inputs, 3.0)
    assert e.note_state == [1, 2]
    e2 = engine(specs, EngineConfig(anti_ghosting=False))
    run(e2, inputs, 3.0)
    assert e2.note_state == [1, 1]


def test_ghost_flag_cleared_by_strum():
    e = engine([(4, G), (4.5, Y, H)])
    run(e, [down(1.9, 0), strum(2.0), down(2.24, 3), down(2.245, 2), up(2.25, 3), strum(2.26)], 3.0)
    assert e.note_state == [1, 1]


def test_lower_fret_press_is_not_ghosting():
    e = engine([(4, O), (4.5, Y, H)])
    run(e, [down(1.9, 4), strum(2.0), up(2.2, 4), down(2.21, 0), down(2.25, 2)], 3.0)
    assert e.note_state == [1, 1]


def test_infinite_front_end():
    specs = [(4, G), (4.5, R, H)]
    inputs = [down(1.9, 0), strum(2.0), down(2.1, 1)]   # pencere 2.18'de acilir
    e = engine(specs, EngineConfig(infinite_front_end=True))
    ev = run(e, inputs, 3.0)
    assert e.note_state == [1, 1]
    assert of(ev, EvType.HIT)[1].offset == pytest.approx(-0.07, abs=1e-6)
    e2 = engine(specs)
    run(e2, inputs, 3.0)
    assert e2.note_state == [1, 2]


# -------------------------------------------------------------- carpan/puan

def _stream(n, step=0.5, start=4.0, mask=G):
    return [(start + k * step, mask) for k in range(n)]


def _strum_all(eng, extra=()):
    ins = hold(0.5, eng.notes[0].mask) + [strum(n.time) for n in eng.notes] + list(extra)
    return ins


def test_multiplier_progression():
    e = engine(_stream(45, step=0.25))
    ev = run(e, _strum_all(e), 30.0)
    vals = {x.note: x.value for x in of(ev, EvType.HIT)}
    assert vals[9] == 50 and vals[10] == 100 and vals[19] == 100 and vals[20] == 150
    assert vals[30] == 200 and vals[40] == 200
    assert [x.value for x in of(ev, EvType.MULTIPLIER_CHANGED)] == [2, 3, 4]
    assert e.multiplier == 4


def test_score_of_30_notes_exact():
    e = engine(_stream(30))
    run(e, _strum_all(e), 30.0)
    assert e.score == 10 * 50 + 10 * 100 + 10 * 150 == 3000
    assert e.base_score == 3000 and e.max_combo == 30


def test_star_power_doubles_to_8x():
    specs = [(4 + k * 0.25, G, S, 0, (0 if k == 0 else 1 if k == 1 else -1)) for k in range(40)]
    e = engine(specs)
    ev = run(e, _strum_all(e, [sp(2.13)]), 30.0)
    assert of(ev, EvType.SP_ACTIVATED)
    vals = {x.note: x.value for x in of(ev, EvType.HIT)}
    assert vals[2] == 100 and vals[10] == 200 and vals[30] == 400 and vals[39] == 400
    assert 8.0 in [x.value for x in of(ev, EvType.MULTIPLIER_CHANGED)]


def test_miss_breaks_combo():
    e = engine(_stream(3))
    ev = run(e, hold(1, G) + [strum(2.0), strum(2.25)], 5.0)
    assert e.combo == 0 and e.max_combo == 2 and e.notes_missed == 1
    assert of(ev, EvType.COMBO_BROKEN)[0].value == 2


# ----------------------------------------------------------------- sustain

def test_sustain_full_hold():
    e = engine([(4, G, S, 2)])   # 2 beat = 1 s
    ev = run(e, [down(1.9, 0), strum(2.0), up(3.2, 0)], 4.0)
    assert e.score == 50 + 50
    assert [x.value for x in of(ev, EvType.SUSTAIN_END)] == [1.0]
    assert of(ev, EvType.SUSTAIN_START)[0].note == 0


def test_sustain_score_grows_while_held():
    e = engine([(4, G, S, 2)])
    run(e, [down(1.9, 0), strum(2.0)], 2.5)
    assert e.score == 75 and e.sustaining == {0: 2.0}


def test_sustain_early_release():
    e = engine([(4, G, S, 2)])
    ev = run(e, [down(1.9, 0), strum(2.0), up(2.5, 0)], 4.0)
    assert e.score == 50 + 25
    assert [x.value for x in of(ev, EvType.SUSTAIN_END)] == [0.0]


def test_chord_sustain_not_multiplied_by_gem_count():
    e = engine([(4, G | R, S, 2)])
    run(e, hold(1.9, G | R) + [strum(2.0)], 4.0)
    assert e.score == 100 + 50


def test_chord_sustain_needs_all_frets():
    e = engine([(4, G | R, S, 2)])
    ev = run(e, hold(1.9, G | R) + [strum(2.0), up(2.5, 0)], 4.0)
    assert e.score == 100 + 25


def test_sustain_anchoring_higher_fret_released_ok():
    e = engine([(4, R, S, 2)])
    run(e, hold(1.9, G | R) + [strum(2.0), up(2.5, 0)], 4.0)
    assert e.score == 100


def test_sustain_drop_leniency():
    e = engine([(4, G, S, 2)])
    run(e, [down(1.9, 0), strum(2.0), up(2.5, 0), down(2.52, 0)], 4.0)
    assert e.score == 100
    e2 = engine([(4, G, S, 2)])
    ev = run(e2, [down(1.9, 0), strum(2.0), up(2.5, 0), down(2.53, 0)], 4.0)
    assert e2.score == 75 and of(ev, EvType.SUSTAIN_END)[0].time == pytest.approx(2.525)


def test_sustain_release_near_end_counts_complete():
    e = engine([(4, G, S, 2)])
    ev = run(e, [down(1.9, 0), strum(2.0), up(2.99, 0)], 4.0)
    assert e.score == 100 and of(ev, EvType.SUSTAIN_END)[0].value == 1.0


def test_sustain_rounds_up():
    e = engine([(4, G, S, 0.3)])   # 7.5 puan -> 8
    run(e, [down(1.9, 0), strum(2.0)], 4.0)
    assert e.score == 58 and e.base_score == 58


def test_extended_sustain_continues_over_higher_notes():
    e = engine([(4, G, S, 4), (5, R), (5.5, Y)])
    ev = run(e, hold(1.9, G) + [strum(2.0), down(2.45, 1), strum(2.5), down(2.7, 2), strum(2.75)], 5.0)
    assert e.note_state == [1, 1, 1]
    assert [x.value for x in of(ev, EvType.SUSTAIN_END)] == [1.0]
    assert e.score == 150 + 100 == e.base_score


def test_open_sustain_completes():
    e = engine([(4, OPEN, S, 2)])
    run(e, [strum(2.0), down(2.3, 0)], 4.0)
    assert e.score == 100


# ------------------------------------------------------------- star power

def test_sp_phrase_complete():
    e = engine([(4, G, S, 0, 0), (5, G, S, 0, 0)])
    ev = run(e, _strum_all(e), 4.0)
    assert of(ev, EvType.SP_PHRASE_COMPLETE)[0].note == 1
    assert e.sp_meter == pytest.approx(0.25) and e.sp_phrase_ok == [True]


def test_sp_phrase_failed_by_miss():
    e = engine([(4, G, S, 0, 0), (5, G, S, 0, 0)])
    ev = run(e, hold(1, G) + [strum(2.5)], 4.0)
    assert of(ev, EvType.SP_PHRASE_FAILED) and e.sp_phrase_ok == [False]
    assert e.sp_meter == 0.0 and not of(ev, EvType.SP_PHRASE_COMPLETE)


def test_sp_phrase_failed_by_overstrum():
    e = engine([(4, G, S, 0, 0), (5, G, S, 0, 0)])
    ev = run(e, hold(1, G) + [strum(2.0), strum(2.2), strum(2.5)], 4.0)
    assert e.overstrums == 1 and e.note_state == [1, 1]
    assert e.sp_phrase_ok == [False] and e.sp_meter == 0.0


def test_overstrum_long_before_phrase_does_not_fail_it():
    e = engine([(4, G), (8, G, S, 0, 0)])
    run(e, hold(1, G) + [strum(2.0), strum(2.5), strum(4.0)], 5.0)
    assert e.overstrums == 1 and e.sp_phrase_ok == [True] and e.sp_meter == pytest.approx(0.25)


def test_sp_activation_threshold():
    e = engine([(4, G, S, 0, 0), (6, G, S, 0, 1), (8, G)])
    run(e, _strum_all(e), 2.5)
    assert e.sp_meter == pytest.approx(0.25)
    assert e.activate_star_power(2.6) is False and not e.sp_active
    e.update(3.5)
    assert e.sp_meter == pytest.approx(0.5)
    assert e.activate_star_power(3.6) is True and e.sp_active
    ev = e.pop_events()
    assert of(ev, EvType.SP_ACTIVATED) and e.multiplier == 2
    assert e.activate_star_power(3.7) is False   # zaten aktif


def _four_phrases(**kw):
    return engine([(4 + k, G, S, 0, k) for k in range(4)], **kw)


def test_sp_drains_in_8_measures_4_4():
    e = _four_phrases()   # 120 BPM 4/4: olcu = 2 s, tam bar = 16 s
    ev = run(e, _strum_all(e, [sp(5.0)]), 13.0)
    assert e.sp_active and e.sp_meter == pytest.approx(0.5)   # 4 olcu sonra yarisi
    e.update(40.0)
    ev += e.pop_events()
    ends = of(ev, EvType.SP_ENDED)
    assert len(ends) == 1 and ends[0].time == pytest.approx(21.0)
    assert not e.sp_active and e.sp_meter == 0.0 and e.multiplier == 1


def test_sp_drain_respects_3_4_time_signature():
    e = _four_phrases(timesigs=[TimeSignature(0, 3, 4)])   # olcu = 1.5 s -> 12 s
    ev = run(e, _strum_all(e, [sp(5.0)]), 40.0)
    assert of(ev, EvType.SP_ENDED)[0].time == pytest.approx(17.0)


def test_sp_gain_while_active_extends():
    specs = [(4, G, S, 0, 0), (5, G, S, 0, 1), (20, G, S, 0, 2)]   # 10 s'de 3. cumle
    e = engine(specs)
    ev = run(e, _strum_all(e, [sp(3.0)]), 40.0)
    # 0.5 bar: 3.0'dan 10.0'a 3.5 olcu -> 0.0625 kalir, +0.25 = 0.3125 -> 2.5 olcu = 5 s
    assert of(ev, EvType.SP_ENDED)[0].time == pytest.approx(15.0)


def test_whammy_gain_on_sp_sustain():
    specs = [(4, G, S, 4, 0)]   # 4 beat SP sustain (2.0 -> 4.0)
    wh = [whammy(2.0 + k * 0.1, float((k + 1) % 2)) for k in range(20)]
    e = engine(specs)
    run(e, [down(1.9, 0), strum(2.0)] + wh, 5.0)
    assert e.sp_meter == pytest.approx(0.25 + 4 / 30, abs=1e-6)
    e2 = engine(specs)
    run(e2, [down(1.9, 0), strum(2.0)], 5.0)
    assert e2.sp_meter == pytest.approx(0.25)


def test_whammy_needs_movement_within_buffer():
    specs = [(4, G, S, 4, 0)]
    e = engine(specs)
    run(e, [down(1.9, 0), strum(2.0), whammy(2.0, 1.0)], 5.0)   # tek hareket: 250 ms = 0.5 beat
    assert e.sp_meter == pytest.approx(0.25 + 0.5 / 30, abs=1e-6)
    assert not e.whammy_active


def test_whammy_no_gain_outside_phrase():
    e = engine([(4, G, S, 4)])
    run(e, [down(1.9, 0), strum(2.0)] + [whammy(2.0 + k * 0.1, float((k + 1) % 2)) for k in range(20)], 5.0)
    assert e.sp_meter == 0.0


# --------------------------------------------------------------- rock metre

def test_rock_meter_hit_and_overstrum():
    cfg = EngineConfig()
    e = engine([(4, G)], cfg)
    run(e, hold(1, G) + [strum(1.0), strum(2.0)], 3.0)
    expected = cfg.rock_start - cfg.rock_miss_loss * cfg.rock_overstrum_mult + cfg.rock_hit_gain
    assert e.rock_meter == pytest.approx(expected)


def test_rock_meter_fail_when_no_fail_off():
    cfg = EngineConfig(no_fail=False, rock_start=0.05)
    e = engine(_stream(6), cfg)
    ev = run(e, [], 10.0)
    assert e.failed and len(of(ev, EvType.FAILED)) == 1 and e.notes_missed == 3
    e2 = engine(_stream(6), EngineConfig(no_fail=True, rock_start=0.05))
    run(e2, [], 10.0)
    assert not e2.failed and e2.notes_missed == 6 and e2.rock_meter == 0.0


# -------------------------------------------------------------------- solo

def test_solo_events():
    chart, track = make_chart(_stream(4), solos=[Solo(start_time=2.4, end_time=3.1)])
    e = GuitarEngine(chart, track, EngineConfig())
    ev = run(e, hold(1, G) + [strum(2.0), strum(2.5)], 5.0)
    assert of(ev, EvType.SOLO_START)[0].time == pytest.approx(2.4)
    end = of(ev, EvType.SOLO_END)
    assert len(end) == 1 and end[0].value == pytest.approx(50.0)


# --------------------------------------------------- frame-rate bagimsizligi

def _human_run(step):
    specs = [(4, G), (4.5, R, H), (5, Y, H), (6, G | R, S, 2, 0), (8, B, S, 0, 0), (9, R), (9.5, G, H),
             (10, OPEN), (11, O, T), (12, Y, S, 3, 1), (14, R, S, 0, 1), (15, G), (16, R | Y), (17, B)]
    inputs = (
        [down(1.9, 0), strum(2.03),                                   # 0 gec vurus
         down(2.26, 1),                                               # 1 hammer-on
         down(2.49, 2),                                               # 2 hammer-on (erken)
         up(2.8, 2), strum(2.97)]                                     # 3 akor sustain + whammy
        + [whammy(3.0 + k * 0.1, float((k + 1) % 2)) for k in range(10)]
        + [up(3.98, 0), up(3.98, 1), down(3.98, 3), strum(4.01),       # 4 cumle 0 tamam
           strum(4.3),                                                # overstrum
           up(4.4, 3), down(4.4, 1), strum(4.5),                      # 5
           up(4.75, 1), down(4.76, 0),                                # 6 HOPO
           strum(5.0),                                                # 7 acik notada perde basili: miss
           up(5.45, 0), down(5.5, 4),                                 # 8 tap
           up(5.9, 4), down(5.9, 2), strum(6.01)]                     # 9 SP sustain
        + [whammy(6.0 + k * 0.08, float((k + 1) % 2)) for k in range(12)]
        + [down(6.95, 1), up(6.99, 2), strum(7.0),                    # 10 sustain'i keser, cumle 1 tamam
           sp(7.1),
           up(7.45, 1), down(7.45, 0), strum(7.5),                    # 11
           down(7.9, 1), down(7.9, 2), up(7.95, 0), strum(8.0),       # 12 akor
           strum(8.3)]                                                # 13 kacar, overstrum
    )
    e = engine(specs)
    for x in sorted(inputs, key=lambda x: x.time):
        e.push(x)
    if step is None:
        e.update(12.0)
    else:
        t = 0.0
        while t < 12.0:
            t = min(12.0, t + step)
            e.update(t)
    return e, e.pop_events()


def test_frame_rate_independence():
    base_e, base_ev = _human_run(None)
    assert base_e.notes_hit > 5 and base_e.notes_missed > 0 and base_e.overstrums > 0
    assert of(base_ev, EvType.SUSTAIN_END) and of(base_ev, EvType.SP_ACTIVATED)
    for step in (0.001, 0.016, 0.05, 0.37):
        e, ev = _human_run(step)
        assert ev == base_ev
        assert (e.score, e.combo, e.max_combo, e.notes_hit, e.notes_missed, e.overstrums) == \
            (base_e.score, base_e.combo, base_e.max_combo, base_e.notes_hit, base_e.notes_missed,
             base_e.overstrums)
        assert e.sp_meter == base_e.sp_meter and e.rock_meter == base_e.rock_meter
        assert e.hit_offsets == base_e.hit_offsets


def test_frame_rate_independence_incremental_push():
    specs = [(4 + k * 0.5, [G, R, Y, B][k % 4], S, 1 if k % 3 == 0 else 0, k // 4) for k in range(24)]
    chart, track = make_chart(specs)
    inputs = autoplay_inputs(track, EngineConfig())
    results = []
    for step in (0.001, 0.05, None):
        e = GuitarEngine(chart, track, EngineConfig())
        if step is None:
            for x in inputs:
                e.push(x)
            e.update(30.0)
        else:
            i = 0
            t = 0.0
            while t < 30.0:
                t += step
                while i < len(inputs) and inputs[i].time <= t:
                    e.push(inputs[i])
                    i += 1
                e.update(t)
        results.append((e.pop_events(), e.score, e.sp_meter))
    assert results[0] == results[1] == results[2]


def test_reset_restores_initial_state():
    e = engine(_stream(5))
    run(e, _strum_all(e), 10.0)
    assert e.score > 0
    e.reset()
    assert e.score == 0 and e.combo == 0 and e.note_state == [0] * 5 and e.pop_events() == []
    run(e, _strum_all(e), 10.0)
    assert e.notes_hit == 5
