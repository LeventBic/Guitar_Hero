"""5 perdeli gitar motoru: Clone Hero semantigi + YARG leniency parametreleri (ek-01 §1.7, §1.8, §5.4, §5.5).

Tasarim:
- Motor saf ve deterministiktir (pygame yok). Girdiler `push` ile kuyruga girer; `update(song_time)` kuyruktaki
  girdileri ve ic zaman asimlarini (miss, strum leniency, sustain sonu/birakma, whammy tamponu, SP bitisi,
  solo) song_time'a kadar KRONOLOJIK sirada isler.
- Kalici ("committed") durum yalnizca olay anlarinda ilerletilir; update sinirlarinda asla. Bu yuzden sonuc
  update'in ne siklikla cagrildigindan bagimsizdir (frame-rate bagimsizligi). Surekli buyuyen degerler
  (sustain puani, SP bari) icin public `score` / `sp_meter` bir "gorunum"dur: kalici durumdan song_time'a
  kadar hesaplanir ama kalici duruma yazilmaz.
- Esit zamanda: sustain bitisi < girdiler < diger zaman asimlari (miss, strum leniency...). Boylece tam
  pencere sinirindaki girdi vurur, sustain bitisi ile ayni andaki birakma sustain'i dusurmez.
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, replace

from ..config import EngineConfig
from ..models import Chart, NoteType, Track
from .events import EvType, GameEvent
from .input_event import InputEvent, InputKind
from .rules import is_ghost_press, matches, multiplier_for_combo, sustain_ends
from .scoring import base_score as _base_score
from .scoring import stars as _stars
from .scoring import sustain_round_up

EPS = 1e-9
INF = float("inf")

NOTE_PENDING = 0
NOTE_HIT = 1
NOTE_MISSED = 2

# zamanlayici turleri: (oncelik, sira). oncelik: 0 = girdilerden once, 2 = girdilerden sonra (girdi = 1)
_T_SUS_END = (0, 0)
_T_ENTRY = (2, 1)
_T_MISS = (2, 2)
_T_STRUM = (2, 3)
_T_SUS_DROP = (2, 4)
_T_WHAMMY = (2, 5)
_T_SP_END = (2, 6)
_T_SOLO_START = (2, 7)
_T_SOLO_END = (2, 8)
_INPUT_PRIO = 1


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


@dataclass
class _Sustain:
    idx: int
    req: int              # tutulmasi gereken perdeler (0 = acik nota, her zaman tamam)
    start: float          # vurus zamani
    end: float            # etkin bitis zamani
    b0: float             # nota baslangici (beat)
    b1: float             # etkin bitis (beat)
    units_total: float    # 25 x beat
    phrase: int
    acc: float = 0.0      # carpanli birikmis puan (kesirli)
    u_done: float = 0.0   # carpansiz birikmis birim
    released_at: float | None = None
    snap_acc: float = 0.0


@dataclass
class _Solo:
    start: float
    end: float
    notes: list[int]
    hits: int = 0
    state: int = 0        # 0 baslamadi, 1 aktif, 2 bitti


class GuitarEngine:
    def __init__(self, chart: Chart, track: Track, cfg: EngineConfig | None = None):
        self.chart = chart
        self.track = track
        self.cfg = cfg or EngineConfig()
        self.tempo_map = chart.tempo_map
        notes = track.notes
        self.notes = notes
        self._n = len(notes)
        self._times = [n.time for n in notes]
        self._masks = [n.mask for n in notes]
        self._types = [n.type for n in notes]
        self._sus_end, self._sus_cut = sustain_ends(notes)

        # SP cumleleri
        n_phr = len(track.sp_phrases)
        for n in notes:
            if n.sp_phrase + 1 > n_phr:
                n_phr = n.sp_phrase + 1
        self._n_phrases = n_phr
        self._phrase_last = [-1] * n_phr
        self._phrase_first_time = [INF] * n_phr
        for i, n in enumerate(notes):
            p = n.sp_phrase
            if p >= 0:
                self._phrase_last[p] = max(self._phrase_last[p], i)
                self._phrase_first_time[p] = min(self._phrase_first_time[p], n.time)

        # solo notalari
        self._solo_defs: list[tuple[float, float, list[int]]] = []
        for so in sorted(track.solos, key=lambda s: s.start_time):
            if so.first_note >= 0 and so.last_note >= so.first_note:
                idxs = list(range(so.first_note, min(so.last_note, self._n - 1) + 1))
            else:
                idxs = [i for i, n in enumerate(notes) if so.start_time <= n.time <= so.end_time]
            self._solo_defs.append((so.start_time, so.end_time, idxs))
        self._note_solo = [-1] * self._n
        for si, (_s, _e, idxs) in enumerate(self._solo_defs):
            for i in idxs:
                self._note_solo[i] = si

        self.total_notes = self._n
        self.base_score = _base_score(track, self.tempo_map, self.cfg)
        self.reset()

    # ------------------------------------------------------------------ durum

    def reset(self) -> None:
        cfg = self.cfg
        self._queue: list[InputEvent] = []
        self._qi = 0
        self._events: list[GameEvent] = []
        self._t = -INF
        self._b = 0.0
        self._m = 0.0
        self._cur = 0
        self._score = 0
        self.score = 0
        self.combo = 0
        self.max_combo = 0
        self._sp_meter = 0.0
        self.sp_meter = 0.0
        self._sp_active = False
        self.sp_active = False
        self.rock_meter = cfg.rock_start
        self.failed = False
        self.held_mask = 0
        self._whammy_on = False
        self.whammy_active = False
        self._whammy_val = 0.0
        self._whammy_last = -INF
        self.note_state = [NOTE_PENDING] * self._n
        self.sustaining: dict[int, float] = {}
        self._sus: list[_Sustain] = []
        self.sp_phrase_ok = [True] * self._n_phrases
        self.notes_hit = 0
        self.notes_missed = 0
        self.overstrums = 0
        self.hit_offsets: list[float] = []
        self._pstrum: tuple[float, float, bool] | None = None   # (strum zamani, son tarih, open_strum)
        self._fret_hit_t: float | None = None                   # HOPO/tap perdeyle vuruldugu an
        self._ghosted = False
        self._last_fret_change = -INF
        self._last_resolve = -INF
        self._last_mult = 1
        self._sp_result = False
        self._solos = [_Solo(s, e, idxs) for (s, e, idxs) in self._solo_defs]
        self._solo_next = 0

    # ---------------------------------------------------------------- public

    @property
    def base_multiplier(self) -> int:
        return multiplier_for_combo(self.combo, self.cfg)

    @property
    def multiplier(self) -> int:
        return self._mult_eff()

    def push(self, ev: InputEvent) -> None:
        if ev.time < self._t:
            ev = replace(ev, time=self._t)
        bisect.insort_right(self._queue, ev, lo=self._qi, key=lambda e: e.time)

    def update(self, song_time: float) -> None:
        while not self.failed:
            tt, tprio, kind, payload = self._next_timer()
            it = max(self._queue[self._qi].time, self._t) if self._qi < len(self._queue) else INF
            if it <= song_time and (it < tt or (it == tt and _INPUT_PRIO < tprio)):
                ev = self._queue[self._qi]
                self._qi += 1
                self._advance(it)
                self._handle_input(ev, it)
            elif tt <= song_time:
                self._advance(tt)
                self._handle_timer(kind, payload, tt)
            else:
                break
            self._post(self._t)
        if self._qi > 256:
            del self._queue[:self._qi]
            self._qi = 0
        self._refresh_view(song_time)

    def pop_events(self) -> list[GameEvent]:
        ev = self._events
        self._events = []
        return ev

    def stars(self) -> float:
        return _stars(self.score, self.base_score, self.cfg)

    def activate_star_power(self, t: float) -> bool:
        self._sp_result = False
        self.push(InputEvent(t, InputKind.STAR_POWER))
        self.update(max(t, self._t))
        return self._sp_result

    @property
    def song_position(self) -> float:
        """Son islenen olay zamani (debug)."""
        return self._t

    # ------------------------------------------------------------ yardimcilar

    def _emit(self, typ: EvType, t: float, note: int = -1, mask: int = 0, offset: float = 0.0,
              value: float = 0.0) -> None:
        self._events.append(GameEvent(typ, t, note, mask, offset, value))

    def _mult_eff(self) -> int:
        m = multiplier_for_combo(self.combo, self.cfg)
        return m * self.cfg.sp_multiplier if self._sp_active else m

    def _check_mult(self, t: float) -> None:
        m = self._mult_eff()
        if m != self._last_mult:
            self._last_mult = m
            self._emit(EvType.MULTIPLIER_CHANGED, t, value=float(m))

    def _in_window(self, i: int, t: float) -> bool:
        nt = self._times[i]
        return nt - self.cfg.window_front - EPS <= t <= nt + self.cfg.window_back + EPS

    def _before_window(self, i: int, t: float) -> bool:
        return t < self._times[i] - self.cfg.window_front - EPS

    def _fret_hittable(self, i: int) -> bool:
        ty = self._types[i]
        return ty == NoteType.TAP or (ty == NoteType.HOPO and self.combo > 0)

    def _bpos(self, t: float) -> float:
        return self.tempo_map.beat_position(t)

    def _mpos(self, t: float) -> float:
        return self.tempo_map.measure_position(t)

    def _measure_to_time(self, m: float) -> float:
        tm = self.tempo_map
        sigs = tm.timesigs
        i = 0
        for k, s in enumerate(sigs):
            if s.measure <= m:
                i = k
            else:
                break
        s = sigs[i]
        tpm = tm.resolution * 4.0 / s.denominator * s.numerator
        return tm.tick_to_time(s.tick + (m - s.measure) * tpm)

    # ---- surekli durum (sustain puani, SP bari)

    def _units(self, s: _Sustain, b: float) -> float:
        return self.cfg.sustain_points_per_beat * (_clamp(b, s.b0, s.b1) - s.b0)

    def _sp_gain_beats(self, b0: float, b1: float) -> float:
        if not self._whammy_on:
            return 0.0
        best = 0.0
        for s in self._sus:
            if s.phrase >= 0 and s.released_at is None and self.sp_phrase_ok[s.phrase]:
                d = _clamp(b1, s.b0, s.b1) - _clamp(b0, s.b0, s.b1)
                if d > best:
                    best = d
        return best

    def _sp_gaining(self) -> bool:
        if not self._whammy_on:
            return False
        for s in self._sus:
            if s.phrase >= 0 and s.released_at is None and self.sp_phrase_ok[s.phrase] and s.b1 > self._b:
                return True
        return False

    def _sp_after(self, t1: float, b1: float) -> float:
        """Kalici durumdan t1 anindaki SP bari (degistirmeden)."""
        cfg = self.cfg
        m = self._sp_meter + cfg.sp_whammy_gain_per_beat * self._sp_gain_beats(self._b, b1)
        if self._sp_active:
            m -= (self._mpos(t1) - self._m) / cfg.sp_full_bar_measures
        return _clamp(m, 0.0, 1.0)

    def _advance(self, t: float) -> None:
        if t <= self._t:
            return
        if self._t == -INF:
            self._t = t
            self._b = self._bpos(t)
            self._m = self._mpos(t)
            return
        b = self._bpos(t)
        mult = self._mult_eff()
        for s in self._sus:
            u = self._units(s, b)
            s.acc += mult * (u - s.u_done)
            s.u_done = u
        self._sp_meter = self._sp_after(t, b)
        self._t = t
        self._b = b
        self._m = self._mpos(t)

    def _refresh_view(self, t: float) -> None:
        self.sp_active = self._sp_active
        self.whammy_active = self._whammy_on
        extra = 0
        if t > self._t and self._t != -INF:
            b = self._bpos(t)
            mult = self._mult_eff()
            for s in self._sus:
                acc = s.acc + mult * (self._units(s, b) - s.u_done)
                extra += int(math.floor(max(0.0, acc) + 1e-6))
            self.sp_meter = self._sp_after(t, b)
        else:
            for s in self._sus:
                extra += int(math.floor(max(0.0, s.acc) + 1e-6))
            self.sp_meter = self._sp_meter
        self.score = self._score + extra

    # ---- zamanlayicilar

    def _next_timer(self) -> tuple[float, int, tuple[int, int], object]:
        cfg = self.cfg
        best: tuple[float, int, int, tuple[int, int], object] = (INF, 9, 9, (9, 9), None)

        def cand(t: float, kind: tuple[int, int], payload: object = None) -> None:
            nonlocal best
            if t < self._t:
                t = self._t
            key = (t, kind[0], kind[1])
            if key < best[:3]:
                best = (t, kind[0], kind[1], kind, payload)

        cur = self._cur
        if cur < self._n:
            cand(self._times[cur] + cfg.window_back + EPS, _T_MISS, cur)
            entry = self._times[cur] - cfg.window_front - EPS
            if entry > self._t and (self._pstrum is not None or (
                    cfg.infinite_front_end and self._types[cur] != NoteType.STRUM)):
                cand(entry, _T_ENTRY, cur)
        if self._pstrum is not None:
            cand(self._pstrum[1], _T_STRUM)
        for s in self._sus:
            cand(s.end, _T_SUS_END, s)
            if s.released_at is not None:
                cand(s.released_at + cfg.sustain_drop_leniency, _T_SUS_DROP, s)
        if self._whammy_on:
            cand(self._whammy_last + cfg.whammy_buffer, _T_WHAMMY)
        if self._solo_next < len(self._solos):
            cand(self._solos[self._solo_next].start, _T_SOLO_START)
        for so in self._solos:
            if so.state == 1 and (not so.notes or so.notes[-1] < self._cur) and so.end > self._t:
                cand(so.end, _T_SOLO_END, so)
        if self._sp_active:
            if self._sp_meter <= 0.0:
                cand(self._t, _T_SP_END)
            elif not self._sp_gaining():
                target = self._m + self._sp_meter * cfg.sp_full_bar_measures
                cand(self._measure_to_time(target), _T_SP_END)
            else:
                hi = best[0]
                if hi < INF and self._sp_after(hi, self._bpos(hi)) <= 1e-12:
                    lo = self._t
                    for _ in range(100):
                        mid = (lo + hi) / 2.0
                        if self._sp_after(mid, self._bpos(mid)) <= 1e-12:
                            hi = mid
                        else:
                            lo = mid
                    cand(hi, _T_SP_END)
        return best[0], best[1], best[3], best[4]

    def _handle_timer(self, kind: tuple[int, int], payload: object, t: float) -> None:
        if kind == _T_MISS:
            if self._cur == payload and self.note_state[payload] == NOTE_PENDING:
                self._miss(payload, t)
        elif kind == _T_ENTRY:
            self._on_entry(t)
        elif kind == _T_STRUM:
            ps = self._pstrum
            self._pstrum = None
            if ps is not None:
                self._overstrum(t, 0 if ps[2] else self.held_mask)
        elif kind == _T_SUS_END:
            self._end_sustain(payload, t, True)
        elif kind == _T_SUS_DROP:
            self._end_sustain(payload, t, False)
        elif kind == _T_WHAMMY:
            self._whammy_on = False
        elif kind == _T_SP_END:
            self._sp_active = False
            self._sp_meter = 0.0
            self._emit(EvType.SP_ENDED, t)
            self._check_mult(t)
        elif kind == _T_SOLO_START:
            so = self._solos[self._solo_next]
            self._solo_next += 1
            so.state = 1
            self._emit(EvType.SOLO_START, t, note=so.notes[0] if so.notes else -1)
        elif kind == _T_SOLO_END:
            pass  # _post bitirir

    def _post(self, t: float) -> None:
        for so in self._solos:
            if so.state == 1 and t >= so.end - EPS and (not so.notes or so.notes[-1] < self._cur):
                so.state = 2
                pct = 100.0 * so.hits / len(so.notes) if so.notes else 0.0
                self._emit(EvType.SOLO_END, t, note=so.notes[-1] if so.notes else -1, value=pct)

    # ---- girdiler

    def _handle_input(self, ev: InputEvent, t: float) -> None:
        k = ev.kind
        if k == InputKind.FRET_DOWN:
            self._fret(t, ev.fret, True)
        elif k == InputKind.FRET_UP:
            self._fret(t, ev.fret, False)
        elif k == InputKind.STRUM:
            self._strum(t, False)
        elif k == InputKind.OPEN_STRUM:
            self._strum(t, True)
        elif k == InputKind.WHAMMY:
            if abs(ev.value - self._whammy_val) > 1e-9:
                self._whammy_val = ev.value
                self._whammy_last = t
                self._whammy_on = True
        elif k == InputKind.STAR_POWER:
            self._activate(t)

    def _fret(self, t: float, fret: int, down: bool) -> None:
        if not 0 <= fret < 5:
            return
        bit = 1 << fret
        new = (self.held_mask | bit) if down else (self.held_mask & ~bit)
        if new == self.held_mask:
            return
        self.held_mask = new
        self._last_fret_change = t
        if new == 0:
            self._ghosted = False
        # sustain'ler: gerekli perdeler birakildi mi / geri basildi mi
        for s in self._sus:
            ok = s.req == 0 or (new & s.req) == s.req
            if not ok and s.released_at is None:
                s.released_at = t
                s.snap_acc = s.acc
            elif ok and s.released_at is not None:
                s.released_at = None
        cur = self._cur
        if cur >= self._n:
            return
        in_win = self._in_window(cur, t)
        # strum once, perde sonra (strum leniency)
        if self._pstrum is not None and in_win and not self._pstrum[2] and matches(self._masks[cur], new):
            self._hit(cur, t, by_fret=False)
            return
        # HOPO / tap perdeyle vurma
        if self._fret_hittable(cur) and in_win:
            if not self._ghosted and matches(self._masks[cur], new):
                self._hit(cur, t, by_fret=True)
                return
            if down and self.cfg.anti_ghosting and is_ghost_press(self._masks[cur], fret):
                self._ghosted = True

    def _strum(self, t: float, open_strum: bool) -> None:
        self._ghosted = False
        if self._pstrum is not None:
            ps = self._pstrum
            self._pstrum = None
            self._overstrum(t, 0 if ps[2] else self.held_mask)
            if self.failed:
                return
        mask = 0 if open_strum else self.held_mask
        cur = self._cur
        in_win = cur < self._n and self._in_window(cur, t)
        if in_win and matches(self._masks[cur], mask):
            self._hit(cur, t, by_fret=False)
            return
        if self._fret_hit_t is not None and t - self._fret_hit_t <= self.cfg.hopo_leniency + EPS:
            self._fret_hit_t = None   # HOPO/tap sonrasi strum yutulur
            return
        len_ = self.cfg.strum_leniency_small if in_win else self.cfg.strum_leniency
        self._pstrum = (t, t + len_, open_strum)

    def _on_entry(self, t: float) -> None:
        cur = self._cur
        if cur >= self._n:
            return
        if self._pstrum is not None:
            mask = 0 if self._pstrum[2] else self.held_mask
            if matches(self._masks[cur], mask):
                self._hit(cur, t, by_fret=False)
                return
        if (self.cfg.infinite_front_end and self._fret_hittable(cur) and not self._ghosted
                and self._last_fret_change > self._last_resolve and matches(self._masks[cur], self.held_mask)):
            self._hit(cur, t, by_fret=True)

    def _check_pending(self, t: float) -> None:
        """Hedef nota degisti (miss sonrasi): bekleyen strum yeni hedefi vurabilir mi?"""
        cur = self._cur
        if self._pstrum is None or cur >= self._n or not self._in_window(cur, t):
            return
        mask = 0 if self._pstrum[2] else self.held_mask
        if matches(self._masks[cur], mask):
            self._hit(cur, t, by_fret=False)

    def _activate(self, t: float) -> bool:
        if self.failed or self._sp_active or self._sp_meter < self.cfg.sp_activation_min - 1e-9:
            return False
        self._sp_active = True
        self._sp_result = True
        self._emit(EvType.SP_ACTIVATED, t, value=self._sp_meter)
        self._check_mult(t)
        return True

    # ---- yargilar

    def _hit(self, i: int, t: float, by_fret: bool) -> None:
        cfg = self.cfg
        note = self.notes[i]
        # bu notanin kestigi sustain'ler (catisan perdeler) tamamlanmis sayilir
        for s in list(self._sus):
            if self._sus_cut[s.idx] == i:
                self._end_sustain(s, t, True)
        pts = cfg.points_per_gem * note.gem_count * self._mult_eff()
        self._score += pts
        self.combo += 1
        if self.combo > self.max_combo:
            self.max_combo = self.combo
        self.note_state[i] = NOTE_HIT
        self._cur = i + 1
        self.notes_hit += 1
        offset = t - self._times[i]
        self.hit_offsets.append(offset)
        self._ghosted = False
        self._last_resolve = t
        self._pstrum = None
        self._fret_hit_t = t if by_fret else None
        gain = cfg.rock_hit_gain * (cfg.rock_sp_hit_mult if self._sp_active else 1.0)
        self.rock_meter = min(1.0, self.rock_meter + gain)
        self._emit(EvType.HIT, t, note=i, mask=note.mask, offset=offset, value=float(pts))
        self._check_mult(t)
        so = self._note_solo[i]
        if so >= 0:
            self._solos[so].hits += 1
        p = note.sp_phrase
        if p >= 0 and self.sp_phrase_ok[p] and self._phrase_last[p] == i:
            self._sp_meter = min(1.0, self._sp_meter + cfg.sp_phrase_gain)
            self._emit(EvType.SP_PHRASE_COMPLETE, t, note=i, value=float(p))
        end = self._sus_end[i]
        if note.has_sustain and end > note.time:
            b0 = self._bpos(note.time)
            b1 = self._bpos(end)
            s = _Sustain(idx=i, req=note.mask, start=t, end=end, b0=b0, b1=b1,
                         units_total=cfg.sustain_points_per_beat * (b1 - b0), phrase=p)
            u = self._units(s, self._b)
            s.u_done = u
            s.acc = self._mult_eff() * u
            if s.req and (self.held_mask & s.req) != s.req:
                s.released_at = t
            self._sus.append(s)
            self.sustaining[i] = t
            self._emit(EvType.SUSTAIN_START, t, note=i, mask=note.mask)
            if t >= end:
                self._end_sustain(s, t, True)

    def _end_sustain(self, s: _Sustain, t: float, completed: bool) -> None:
        if s not in self._sus:
            return
        self._sus.remove(s)
        self.sustaining.pop(s.idx, None)
        if completed:
            pts = sustain_round_up(s.acc, self._mult_eff(), s.units_total, s.u_done)
        else:
            acc = s.snap_acc if s.released_at is not None else s.acc
            pts = max(0, int(math.floor(acc + 1e-6)))
        self._score += pts
        self._emit(EvType.SUSTAIN_END, t, note=s.idx, mask=s.req, value=1.0 if completed else 0.0)

    def _break_combo(self, t: float) -> None:
        if self.combo > 0:
            self._emit(EvType.COMBO_BROKEN, t, value=float(self.combo))
            self.combo = 0
        self._check_mult(t)

    def _fail_phrase(self, p: int, t: float, note: int) -> None:
        if p >= 0 and self.sp_phrase_ok[p]:
            self.sp_phrase_ok[p] = False
            self._emit(EvType.SP_PHRASE_FAILED, t, note=note, value=float(p))

    def _rock_loss(self, amount: float, t: float) -> None:
        self.rock_meter = max(0.0, self.rock_meter - amount)
        if self.rock_meter <= 0.0 and not self.cfg.no_fail and not self.failed:
            self.failed = True
            self._emit(EvType.FAILED, t)

    def _miss(self, i: int, t: float) -> None:
        note = self.notes[i]
        self.note_state[i] = NOTE_MISSED
        self._cur = i + 1
        self.notes_missed += 1
        self._ghosted = False
        self._last_resolve = t
        self._emit(EvType.MISS, t, note=i, mask=note.mask)
        self._break_combo(t)
        self._fail_phrase(note.sp_phrase, t, i)
        self._rock_loss(self.cfg.rock_miss_loss, t)
        if not self.failed:
            self._check_pending(t)

    def _overstrum(self, t: float, mask: int) -> None:
        self.overstrums += 1
        self._emit(EvType.OVERSTRUM, t, note=self._cur if self._cur < self._n else -1, mask=mask)
        self._break_combo(t)
        cur = self._cur
        if cur < self._n:
            p = self.notes[cur].sp_phrase
            # yalnizca cumle "basladiysa" (ilk notasi pencereye girdiyse) iptal
            if p >= 0 and t >= self._phrase_first_time[p] - self.cfg.window_front - EPS:
                self._fail_phrase(p, t, cur)
        self._rock_loss(self.cfg.rock_miss_loss * self.cfg.rock_overstrum_mult, t)
