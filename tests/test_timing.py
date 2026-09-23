import pytest

from gh.timing import TempoChange, TempoMap, TimeSignature


def make_map(res=192):
    # 120 BPM, tick 4*res'te (1. olcu sonu) 150 BPM; 4/4 -> 3/4 ayni yerde
    return TempoMap(res, [TempoChange(0, 120.0), TempoChange(4 * res, 150.0)],
                    [TimeSignature(0, 4, 4), TimeSignature(4 * res, 3, 4)])


@pytest.mark.parametrize("res", [192, 480])
def test_tick_to_time_with_tempo_change(res):
    tm = make_map(res)
    assert tm.tick_to_time(0) == pytest.approx(0.0)
    assert tm.tick_to_time(res) == pytest.approx(0.5)
    assert tm.tick_to_time(4 * res) == pytest.approx(2.0)
    assert tm.tick_to_time(5 * res) == pytest.approx(2.4)
    assert tm.tick_to_time(8 * res) == pytest.approx(3.6)
    assert tm.bpm_at(1.0) == 120.0
    assert tm.bpm_at(2.5) == 150.0


@pytest.mark.parametrize("res", [192, 480])
def test_time_tick_round_trip(res):
    tm = make_map(res)
    for tick in (0, 1, res // 2, 4 * res - 1, 4 * res, 4 * res + 7, 13 * res + 5):
        assert tm.time_to_tick(tm.tick_to_time(tick)) == pytest.approx(tick)
    for t in (0.0, 0.3, 1.999, 2.0, 2.001, 7.25):
        assert tm.tick_to_time(tm.time_to_tick(t)) == pytest.approx(t)


def test_measure_position_with_timesig_change():
    res = 192
    tm = make_map(res)
    assert tm.measure_position(0.0) == pytest.approx(0.0)
    assert tm.measure_position(tm.tick_to_time(2 * res)) == pytest.approx(0.5)
    assert tm.measure_position(tm.tick_to_time(4 * res)) == pytest.approx(1.0)
    # 3/4: olcu = 3 beat
    assert tm.measure_position(tm.tick_to_time(7 * res)) == pytest.approx(2.0)
    assert tm.measure_position(tm.tick_to_time(8 * res)) == pytest.approx(2.0 + 1 / 3)
    assert tm.timesigs[1].measure == pytest.approx(1.0)
    assert tm.timesigs[1].time == pytest.approx(2.0)


def test_beat_lines_follow_timesig():
    res = 192
    tm = make_map(res)
    lines = tm.beat_lines(tm.tick_to_time(10 * res))
    full = [(round(tm.time_to_tick(l.time)), l.kind) for l in lines if l.kind != 2]
    measures = [t for t, k in full if k == 0]
    beats = [t for t, k in full if k == 1]
    assert measures == [0, 4 * res, 7 * res, 10 * res]   # end_time dahil
    assert beats == [res, 2 * res, 3 * res, 5 * res, 6 * res, 8 * res, 9 * res]
    halves = [l for l in lines if l.kind == 2]
    assert len(halves) == 10
    times = [l.time for l in lines]
    assert times == sorted(times)


def test_tempo_map_defaults_and_invalid_values():
    tm = TempoMap(480, [TempoChange(960, 100.0), TempoChange(1920, 0.0)], [TimeSignature(0, 0, 4)])
    assert tm.tempos[0].tick == 0 and tm.tempos[0].bpm == 100.0
    assert len(tm.tempos) == 2           # 0 BPM atlanir
    assert tm.timesigs[0].numerator == 4  # gecersiz TS -> varsayilan 4/4
    assert tm.tick_to_time(480) == pytest.approx(0.6)
