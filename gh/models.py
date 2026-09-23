"""Chart veri modelleri. Parser'lar uretir, motor ve render okur. Motorun calisma durumu burada DEGIL
(engine kendi dizilerinde tutar) - boylece ayni Chart birden fazla motorla/yeniden baslatmayla kullanilir.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

from .timing import TempoMap

OPEN_MASK = 0  # acik nota: hic perde yok


class NoteType(IntEnum):
    STRUM = 0
    HOPO = 1
    TAP = 2


def popcount(mask: int) -> int:
    return bin(mask).count("1")


@dataclass
class Note:
    """Ayni tick'teki tum gem'ler tek Note'tur (akor = birden fazla bit)."""
    tick: int
    time: float                 # chart saniyesi
    mask: int                   # bit0 yesil ... bit4 turuncu; 0 = acik nota
    type: NoteType = NoteType.STRUM
    length_ticks: int = 0       # sustain uzunlugu (akordaki en uzun gem)
    end_time: float = 0.0       # sustain bitisi (sustain yoksa == time)
    sp_phrase: int = -1         # ait oldugu Star Power cumlesi indeksi, yoksa -1
    sp_phrase_end: bool = False # cumlenin son notasi mi
    index: int = 0              # track icindeki sira

    @property
    def is_open(self) -> bool:
        return self.mask == OPEN_MASK

    @property
    def is_chord(self) -> bool:
        return popcount(self.mask) >= 2

    @property
    def gem_count(self) -> int:
        return max(1, popcount(self.mask))

    @property
    def has_sustain(self) -> bool:
        return self.length_ticks > 0 and self.end_time > self.time

    @property
    def lowest_fret(self) -> int:
        return (self.mask & -self.mask).bit_length() - 1 if self.mask else -1

    @property
    def highest_fret(self) -> int:
        return self.mask.bit_length() - 1 if self.mask else -1


@dataclass
class SPPhrase:
    tick: int
    length_ticks: int
    start_time: float
    end_time: float
    first_note: int = -1   # track.notes indeksi
    last_note: int = -1


@dataclass
class Solo:
    start_time: float
    end_time: float
    first_note: int = -1
    last_note: int = -1


@dataclass
class Section:
    tick: int
    time: float
    name: str


@dataclass
class Track:
    difficulty: str                       # easy / medium / hard / expert
    notes: list[Note] = field(default_factory=list)
    sp_phrases: list[SPPhrase] = field(default_factory=list)
    solos: list[Solo] = field(default_factory=list)


@dataclass
class SongInfo:
    name: str = "Unknown"
    artist: str = "Unknown"
    album: str = ""
    genre: str = ""
    year: str = ""
    charter: str = ""
    song_length_ms: int = 0
    preview_start_ms: int = 0
    delay_ms: int = 0                     # song.ini delay (+: notalar daha gec)
    hopo_frequency: int | None = None     # song.ini hopo_frequency (tick)
    sustain_cutoff_threshold: int | None = None
    diff_guitar: int = -1
    eighthnote_hopo: bool = False         # song.ini eighthnote_hopo: .mid HOPO esigi res/2+1
    multiplier_note: int = 116            # song.ini multiplier_note: .mid SP nota numarasi (103/116)
    folder: str = ""
    chart_path: str = ""
    album_art: str = ""
    stems: dict[str, str] = field(default_factory=dict)  # "song", "guitar", "rhythm", "bass", ... -> dosya yolu


@dataclass
class Chart:
    resolution: int
    tempo_map: TempoMap
    info: SongInfo = field(default_factory=SongInfo)
    offset: float = 0.0                   # saniye; ses saati - chart saati farki (.chart Offset + delay)
    sections: list[Section] = field(default_factory=list)
    tracks: dict[str, Track] = field(default_factory=dict)   # zorluk -> Track (yalniz 5-fret gitar)
    end_time: float = 0.0                 # son nota/sustain/[end] olayi

    def track(self, difficulty: str) -> Track | None:
        return self.tracks.get(difficulty)
