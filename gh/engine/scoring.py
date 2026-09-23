"""Taban skor ve yildiz hesabi (ek-01 §5.4, YARG modeli).

base_score = full combo + tum sustain'ler tam tutulmus + Star Power kullanilmamis skor. Motorun sustain
puanlamasiyla birebir ayni sekilde hesaplanir (carpan degisimleri extended sustain'in ortasinda da olur),
boylece kusursuz bir SP'siz calis tam olarak base_score verir.
"""
from __future__ import annotations

import math

from ..config import EngineConfig
from ..models import Track
from ..timing import TempoMap
from .rules import multiplier_for_combo, sustain_ends

ROUND_EPS = 1e-6


def sustain_round_up(acc: float, mult: int, units_total: float, units_done: float) -> int:
    """Tamamlanan sustain'in puani: biriken puan + son carpanla 'yukari yuvarlama' payi
    (Clone Hero sustain_rounding = RoundUp; sabit carpanda = carpan x ceil(beat x 25))."""
    full = math.ceil(units_total - ROUND_EPS)
    return max(0, math.ceil(acc + mult * (full - units_done) - ROUND_EPS))


def base_score(track: Track, tempo_map: TempoMap, cfg: EngineConfig | None = None) -> int:
    cfg = cfg or EngineConfig()
    notes = track.notes
    ends, _cuts = sustain_ends(notes)
    spb = cfg.sustain_points_per_beat
    total = 0
    n = len(notes)
    for k, note in enumerate(notes):
        total += cfg.points_per_gem * note.gem_count * multiplier_for_combo(k, cfg)
        if note.has_sustain and ends[k] > note.time:
            b0 = tempo_map.beat_position(note.time)
            b1 = tempo_map.beat_position(ends[k])
            units_total = spb * (b1 - b0)
            m = multiplier_for_combo(k + 1, cfg)
            acc = 0.0
            prev = b0
            j = k + 1
            while j < n and notes[j].time < ends[k]:
                bj = min(max(tempo_map.beat_position(notes[j].time), b0), b1)
                acc += m * spb * (bj - prev)
                prev = bj
                m = multiplier_for_combo(j + 1, cfg)
                j += 1
            acc += m * spb * (b1 - prev)
            total += sustain_round_up(acc, m, units_total, units_total)
    return total


def star_thresholds(base: int, cfg: EngineConfig | None = None) -> list[int]:
    cfg = cfg or EngineConfig()
    return [int(math.floor(base * x)) for x in cfg.star_thresholds]


def stars(score: int, base: int, cfg: EngineConfig | None = None) -> float:
    """0..6 arasi kesirli yildiz (6 = altin). k tam yildiz + bir sonraki esige ilerleme orani."""
    if base <= 0:
        return 0.0
    th = star_thresholds(base, cfg)
    prev = 0
    for k, v in enumerate(th):
        if score < v:
            if v <= prev:
                return float(k)
            return k + max(0.0, (score - prev) / (v - prev))
        prev = v
    return float(len(th))
