"""Motorun on yuze bildirdigi oyun olaylari (efekt, ses, HUD)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class EvType(IntEnum):
    HIT = 0
    MISS = 1
    OVERSTRUM = 2
    SUSTAIN_START = 3
    SUSTAIN_END = 4
    SP_PHRASE_COMPLETE = 5
    SP_PHRASE_FAILED = 6
    SP_ACTIVATED = 7
    SP_ENDED = 8
    MULTIPLIER_CHANGED = 9
    COMBO_BROKEN = 10
    FAILED = 11
    SOLO_START = 12
    SOLO_END = 13


@dataclass
class GameEvent:
    type: EvType
    time: float
    note: int = -1         # not indeksi
    mask: int = 0
    offset: float = 0.0    # HIT: vurus - nota zamani (negatif = erken)
    value: float = 0.0     # MULTIPLIER_CHANGED: yeni carpan; SUSTAIN_END: 1/0; SOLO_END: yuzde;
                           # SP_PHRASE_*: cumle indeksi; COMBO_BROKEN: kirilan combo
