"""Kusursuz calan bot: bir Track icin zaman damgali InputEvent listesi uretir (demo / "bot" modu, testler).

- Strum notalari: perdeler notadan biraz once (en fazla 20 ms, iki nota arasinin yarisi) ayarlanir,
  strum tam nota aninda.
- HOPO (combo > 0) ve tap: strum yok; perde degisimi tam nota aninda. Esleme hep son degisimle olur ve
  yalnizca hedefte "yasal" perdelere basilir (anti-ghosting'e takilmaz).
- Sustain'ler etkin bitislerine kadar tutulur; uyumlu sonraki notalarda (extended sustain) birakilmaz.
- SP cumlesindeki sustain'lerde whammy sallanir; use_star_power ise her cumle tamamlaninca SP denenir
  (motor bar yetersizse / SP zaten aktifse yok sayar, ceza yok).
"""
from __future__ import annotations

from ..config import EngineConfig
from ..models import NoteType, Track
from .input_event import InputEvent, InputKind
from .rules import sustain_ends

FRET_LEAD = 0.020
WHAMMY_PERIOD = 0.100


def autoplay_inputs(track: Track, cfg: EngineConfig | None = None, *, use_star_power: bool = True,
                    whammy: bool = True) -> list[InputEvent]:
    cfg = cfg or EngineConfig()
    notes = track.notes
    ends, _cuts = sustain_ends(notes)
    out: list[tuple[float, int, InputEvent]] = []
    seq = 0

    def emit(t: float, kind: InputKind, fret: int = -1, value: float = 0.0) -> None:
        nonlocal seq
        out.append((t, seq, InputEvent(t, kind, fret, value)))
        seq += 1

    held = 0
    active: list[tuple[float, int]] = []   # (etkin bitis, maske) tutulan sustain'ler

    def set_mask(t: float, desired: int, note_mask: int) -> None:
        """Mevcut -> istenen perde gecisi. Sira: istenmeyen alt perdeleri birak, eksikleri (artan) bas,
        istenmeyen ust perdeleri (azalan) birak. Esleme yalnizca son adimda olusur."""
        nonlocal held
        top = note_mask.bit_length()  # tek nota: nota perdesi + 1
        rel = held & ~desired
        press = desired & ~held
        for f in range(5):
            if rel >> f & 1 and f + 1 < top:
                emit(t, InputKind.FRET_UP, f)
        for f in range(5):
            if press >> f & 1:
                emit(t, InputKind.FRET_DOWN, f)
        for f in range(4, -1, -1):
            if rel >> f & 1 and not f + 1 < top:
                emit(t, InputKind.FRET_UP, f)
        held = desired

    phrase_last: dict[int, int] = {}
    for i, n in enumerate(notes):
        if n.sp_phrase >= 0:
            phrase_last[n.sp_phrase] = max(phrase_last.get(n.sp_phrase, -1), i)

    for i, n in enumerate(notes):
        t = n.time
        keep = 0
        for e, m in active:
            if e > t:
                keep |= m
        if n.mask == 0:
            desired = 0
        elif n.mask & (n.mask - 1):
            desired = n.mask | keep
        else:
            desired = n.mask | keep
        fret_hit = n.type == NoteType.TAP or (n.type == NoteType.HOPO and i > 0)
        if fret_hit and desired == held:
            if desired == 0:
                fret_hit = False            # tekrar eden acik HOPO/tap: strum ile vur
            else:
                hb = desired.bit_length() - 1   # yeniden bas
                emit(t, InputKind.FRET_UP, hb)
                emit(t, InputKind.FRET_DOWN, hb)
        if fret_hit:
            if desired != held:
                set_mask(t, desired, n.mask)
        else:
            if desired != held:
                gap = t - notes[i - 1].time if i > 0 else 1.0
                tt = t - min(FRET_LEAD, gap / 2.0)
                rel = held & ~desired
                for e, m in active:
                    if m & rel and e > tt:
                        tt = e
                set_mask(min(tt, t), desired, n.mask)
            emit(t, InputKind.STRUM)
        active = [(e, m) for (e, m) in active if e > t]
        if n.has_sustain and ends[i] > t:
            active.append((ends[i], n.mask))
            if whammy and n.sp_phrase >= 0:
                wt = t
                v = 1.0
                while wt < ends[i]:
                    emit(wt, InputKind.WHAMMY, value=v)
                    v = 0.0 if v else 1.0
                    wt += WHAMMY_PERIOD
        if use_star_power and n.sp_phrase >= 0 and phrase_last.get(n.sp_phrase) == i:
            emit(t, InputKind.STAR_POWER)

    if held:
        t_end = max([n.time for n in notes] + [e for e in ends]) + 0.05
        for f in range(5):
            if held >> f & 1:
                emit(t_end, InputKind.FRET_UP, f)
    out.sort(key=lambda x: (x[0], x[1]))
    return [ev for _t, _s, ev in out]
