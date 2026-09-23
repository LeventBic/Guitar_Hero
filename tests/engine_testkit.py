"""Motor testleri icin ortak chart/girdi yardimcilari (parser kullanmadan gh.models ile chart kurar)."""
from __future__ import annotations

import random

from gh.config import EngineConfig
from gh.engine import GuitarEngine, InputEvent, InputKind
from gh.models import Chart, Note, NoteType, Solo, SPPhrase, Track
from gh.timing import TempoChange, TempoMap, TimeSignature

G, R, Y, B, O = 1, 2, 4, 8, 16
OPEN = 0
S, H, T = NoteType.STRUM, NoteType.HOPO, NoteType.TAP
RES = 480


def make_chart(specs, bpm: float = 120.0, res: int = RES, tempos=None, timesigs=None, solos=()):
    """specs: (beat, mask[, type[, sustain_beats[, sp_phrase]]])."""
    tm = TempoMap(res, list(tempos) if tempos else [TempoChange(0, bpm)], list(timesigs) if timesigs else None)
    notes = []
    for idx, s in enumerate(specs):
        beat, mask = s[0], s[1]
        typ = s[2] if len(s) > 2 else S
        length = s[3] if len(s) > 3 else 0
        phrase = s[4] if len(s) > 4 else -1
        tick = int(round(beat * res))
        lt = int(round(length * res))
        notes.append(Note(tick=tick, time=tm.tick_to_time(tick), mask=mask, type=typ, length_ticks=lt,
                          end_time=tm.tick_to_time(tick + lt), sp_phrase=phrase, index=idx))
    ids = sorted({n.sp_phrase for n in notes if n.sp_phrase >= 0})
    phrases = []
    for p in range(ids[-1] + 1 if ids else 0):
        idxs = [n.index for n in notes if n.sp_phrase == p]
        first, last = idxs[0], idxs[-1]
        notes[last].sp_phrase_end = True
        phrases.append(SPPhrase(tick=notes[first].tick, length_ticks=notes[last].tick - notes[first].tick + 1,
                                start_time=notes[first].time, end_time=notes[last].time,
                                first_note=first, last_note=last))
    track = Track("expert", notes, phrases, list(solos))
    end = max([n.end_time for n in notes] + [n.time for n in notes] + [0.0])
    chart = Chart(res, tm, tracks={"expert": track}, end_time=end)
    return chart, track


def engine(specs, cfg: EngineConfig | None = None, **kw) -> GuitarEngine:
    chart, track = make_chart(specs, **kw)
    return GuitarEngine(chart, track, cfg or EngineConfig())


def down(t, f):
    return InputEvent(t, InputKind.FRET_DOWN, f)


def up(t, f):
    return InputEvent(t, InputKind.FRET_UP, f)


def strum(t):
    return InputEvent(t, InputKind.STRUM)


def open_strum(t):
    return InputEvent(t, InputKind.OPEN_STRUM)


def whammy(t, v):
    return InputEvent(t, InputKind.WHAMMY, value=v)


def sp(t):
    return InputEvent(t, InputKind.STAR_POWER)


def hold(t, mask):
    return [down(t, f) for f in range(5) if mask >> f & 1]


def release(t, mask):
    return [up(t, f) for f in range(5) if mask >> f & 1]


def run(eng: GuitarEngine, inputs, until: float):
    for e in sorted(inputs, key=lambda e: e.time):
        eng.push(e)
    eng.update(until)
    return eng.pop_events()


def of(events, typ):
    return [e for e in events if e.type == typ]


def random_chart(seed: int, n_notes: int = 220):
    rnd = random.Random(seed)
    tempos = [TempoChange(0, rnd.choice([95.0, 120.0, 150.0, 185.0]))]
    tick = RES * 2
    specs = []
    prev_mask = -1
    phrase = -1
    phrase_left = 0
    next_phrase_at = rnd.randint(5, 15)
    for i in range(n_notes):
        gap = rnd.choice([40, 60, 80, 120, 160, 160, 240, 240, 480, 960])
        tick += gap
        if rnd.random() < 0.02:
            tempos.append(TempoChange(tick, rnd.choice([90.0, 130.0, 170.0, 210.0])))
        r = rnd.random()
        if r < 0.1:
            mask = OPEN
        elif r < 0.3:
            frets = rnd.sample(range(5), rnd.choice([2, 2, 3]))
            mask = sum(1 << f for f in frets)
        else:
            mask = 1 << rnd.randrange(5)
        typ = S
        rt = rnd.random()
        if mask and not mask & (mask - 1) and prev_mask != mask and gap <= 160 and rt < 0.6:
            typ = H
        elif rt < 0.08:
            typ = T
        elif rt < 0.12:
            typ = H
        length = 0
        if rnd.random() < 0.25:
            length = rnd.choice([60, 120, 240, 480, 960, 1500])
        p = -1
        if phrase_left > 0:
            p = phrase
            phrase_left -= 1
        elif i >= next_phrase_at:
            phrase += 1
            p = phrase
            phrase_left = rnd.randint(2, 6) - 1
            next_phrase_at = i + rnd.randint(8, 20)
        specs.append((tick / RES, mask, typ, length / RES, p))
        prev_mask = mask
    timesigs = [TimeSignature(0, 4, 4), TimeSignature(RES * 4 * 6, 3, 4), TimeSignature(RES * 4 * 30, 7, 8)]
    return make_chart(specs, tempos=tempos, timesigs=timesigs)
