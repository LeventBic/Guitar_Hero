"""Zaman damgali oyuncu girdisi (R09). On yuz (klavye/joystick) uretir, motor tuketir."""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class InputKind(IntEnum):
    FRET_DOWN = 0
    FRET_UP = 1
    STRUM = 2
    OPEN_STRUM = 3
    WHAMMY = 4
    STAR_POWER = 5


@dataclass
class InputEvent:
    time: float            # SongTime (saniye)
    kind: InputKind
    fret: int = -1         # FRET_DOWN/UP icin 0..4
    value: float = 0.0     # WHAMMY icin 0..1
