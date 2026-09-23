"""Tempo haritasi: tick <-> saniye, beat ve olcu konumu.

Tum zamanlar "chart saniyesi"dir (0 = tick 0). Sarki gecikmesi (song.ini delay / .chart Offset)
Chart.offset ile ayrica tutulur; ses saati tarafinda uygulanir.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass


@dataclass
class TempoChange:
    tick: int
    bpm: float
    time: float = 0.0  # TempoMap tarafindan doldurulur


@dataclass
class TimeSignature:
    tick: int
    numerator: int = 4
    denominator: int = 4  # gercek payda (4 = ceyrek nota), ussu degil
    time: float = 0.0
    measure: float = 0.0  # bu TS'nin basladigi olcu sayisi (TempoMap doldurur)


@dataclass
class BeatLine:
    time: float
    kind: int  # 0 = olcu cizgisi, 1 = beat, 2 = yarim beat


class TempoMap:
    def __init__(self, resolution: int, tempos: list[TempoChange], timesigs: list[TimeSignature] | None = None):
        self.resolution = max(1, int(resolution))
        # gecersiz (<=0) tempo degerleri sifira bolmeye yol acar -> atla
        tempos = sorted((t for t in tempos if t.bpm > 0), key=lambda t: t.tick)
        if not tempos or tempos[0].tick != 0:
            tempos.insert(0, TempoChange(0, tempos[0].bpm if tempos else 120.0))
        # ayni tick'te birden fazla tempo varsa sonuncusu gecerli
        dedup: list[TempoChange] = []
        for t in tempos:
            if dedup and dedup[-1].tick == t.tick:
                dedup[-1] = t
            else:
                dedup.append(t)
        self.tempos = dedup
        t = 0.0
        for i, tc in enumerate(self.tempos):
            if i > 0:
                prev = self.tempos[i - 1]
                t += (tc.tick - prev.tick) / self.resolution * 60.0 / prev.bpm
            tc.time = t
        self._tempo_ticks = [tc.tick for tc in self.tempos]
        self._tempo_times = [tc.time for tc in self.tempos]

        ts = sorted((s for s in (timesigs or []) if s.numerator > 0 and s.denominator > 0),
                    key=lambda s: s.tick)
        if not ts or ts[0].tick != 0:
            ts.insert(0, TimeSignature(0, 4, 4))
        dts: list[TimeSignature] = []
        for s in ts:
            if dts and dts[-1].tick == s.tick:
                dts[-1] = s
            else:
                dts.append(s)
        self.timesigs = dts
        measure = 0.0
        for i, s in enumerate(self.timesigs):
            if i > 0:
                p = self.timesigs[i - 1]
                measure += (s.tick - p.tick) / self._ticks_per_measure(p)
            s.measure = measure
            s.time = self.tick_to_time(s.tick)
        self._ts_ticks = [s.tick for s in self.timesigs]

    # --- temel donusumler ---------------------------------------------------

    def _ticks_per_beat(self, ts: TimeSignature) -> float:
        """Bir 'beat' (TS paydasi) kac tick. 4/4 -> resolution, 6/8 -> resolution/2."""
        return self.resolution * 4.0 / ts.denominator

    def _ticks_per_measure(self, ts: TimeSignature) -> float:
        return self._ticks_per_beat(ts) * ts.numerator

    def tick_to_time(self, tick: float) -> float:
        i = bisect.bisect_right(self._tempo_ticks, tick) - 1
        i = max(i, 0)
        tc = self.tempos[i]
        return tc.time + (tick - tc.tick) / self.resolution * 60.0 / tc.bpm

    def time_to_tick(self, time: float) -> float:
        i = bisect.bisect_right(self._tempo_times, time) - 1
        i = max(i, 0)
        tc = self.tempos[i]
        return tc.tick + (time - tc.time) * tc.bpm / 60.0 * self.resolution

    def bpm_at(self, time: float) -> float:
        i = max(bisect.bisect_right(self._tempo_times, time) - 1, 0)
        return self.tempos[i].bpm

    # --- beat / olcu konumu -------------------------------------------------

    def beat_position(self, time: float) -> float:
        """Ceyrek nota (resolution tick) cinsinden kesirli konum. Sustain puani ve whammy icin."""
        return self.time_to_tick(time) / self.resolution

    def measure_position(self, time: float) -> float:
        """Kesirli olcu sayisi (TS degisimlerini hesaba katar). Star Power bosalmasi icin."""
        tick = self.time_to_tick(time)
        i = max(bisect.bisect_right(self._ts_ticks, tick) - 1, 0)
        s = self.timesigs[i]
        return s.measure + (tick - s.tick) / self._ticks_per_measure(s)

    def timesig_at_tick(self, tick: float) -> TimeSignature:
        i = max(bisect.bisect_right(self._ts_ticks, tick) - 1, 0)
        return self.timesigs[i]

    # --- cizgiler -----------------------------------------------------------

    def beat_lines(self, end_time: float) -> list[BeatLine]:
        """0'dan end_time'a kadar (dahil) olcu/beat/yarim-beat cizgileri (sirali).

        Her TS degisimi yeni bir olcu baslatir (olcu cizgisi TS tick'inde).
        """
        lines: list[BeatLine] = []
        end_tick = self.time_to_tick(end_time) + 1e-6
        for i, s in enumerate(self.timesigs):
            if s.tick > end_tick:
                break
            seg_end = self.timesigs[i + 1].tick if i + 1 < len(self.timesigs) else float("inf")
            tpb = self._ticks_per_beat(s)
            k = 0
            while True:
                tick = s.tick + k * tpb / 2.0
                if tick >= seg_end or tick > end_tick:
                    break
                if k % 2 == 1:
                    kind = 2
                elif (k // 2) % s.numerator == 0:
                    kind = 0
                else:
                    kind = 1
                lines.append(BeatLine(self.tick_to_time(tick), kind))
                k += 1
        return lines
