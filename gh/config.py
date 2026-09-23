"""Tum oyun sabitleri tek yerde.

Degerler Levo-Researches/reports/oyun/...gitar-ritim-oyunu ek-01 arastirmasindan (Clone Hero / YARG
kaynak kodu ve CHOpt) alindi. Bolum referanslari yorumlarda.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

GAME_TITLE = "RIFF"  # R14: "Guitar Hero" adi kullanilmaz

# --- Yollar -----------------------------------------------------------------

def resource_root() -> str:
    """Salt-okunur kaynaklar: PyInstaller icinde _MEIPASS, normalde proje koku."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def user_root() -> str:
    """Yazilabilir klasor: exe'nin yani veya proje koku (settings.json, ekstra Songs/)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --- Perdeler ---------------------------------------------------------------

NUM_FRETS = 5
FRET_NAMES = ("green", "red", "yellow", "blue", "orange")
FRET_COLORS = (
    (40, 200, 60),
    (230, 40, 40),
    (245, 220, 40),
    (40, 110, 240),
    (250, 140, 20),
)
OPEN_COLOR = (200, 60, 220)
SP_COLOR = (90, 220, 255)

DIFFICULTIES = ("easy", "medium", "hard", "expert")


# --- Motor (mekanik) --------------------------------------------------------

@dataclass
class EngineConfig:
    # §1.7 Hit window: Clone Hero/YARG varsayilani +-70 ms simetrik.
    hit_window: float = 0.140            # toplam pencere (saniye)
    front_to_back_ratio: float = 1.0     # <1: erken taraf dar
    window_scale: float = 1.0            # sarki hizi carpani (practice)

    # §1.7 YARG gitar leniency parametreleri
    hopo_leniency: float = 0.080         # HOPO/tap vurulduktan sonra strum overstrum sayilmaz
    strum_leniency: float = 0.050        # strum, nota penceresine girmeden once bu kadar erken atilabilir
    strum_leniency_small: float = 0.025  # strum + fret siralama toleransi (strum sonra fret)
    sustain_drop_leniency: float = 0.025 # sustain'de perde bu kadar sure birakilabilir
    whammy_buffer: float = 0.250         # whammy hareketinden sonra "whammy yapiliyor" sayilan sure
    anti_ghosting: bool = True           # yanlis perde basilirsa HOPO/tap devre disi
    infinite_front_end: bool = False     # HOPO/tap pencereden once fretlenebilir

    # §5.4 Puan (Clone Hero modeli)
    points_per_gem: int = 50             # akorda 50 x gem sayisi
    sustain_points_per_beat: int = 25    # akorlar sustain'i CARPMAZ
    streak_per_multiplier: int = 10      # carpan = min(combo//10 + 1, 4)
    max_multiplier: int = 4
    sp_multiplier: int = 2

    # §1.8 Star Power (bar 0..1)
    sp_phrase_gain: float = 0.25
    sp_activation_min: float = 0.5
    sp_full_bar_measures: float = 8.0    # tam bar 8 olcu surer (olcu cinsinden, saniye degil)
    sp_whammy_gain_per_beat: float = 1.0 / 30.0

    # §5.5 Rock metre (YARG FailMeter varsayilan preset)
    rock_start: float = 0.833
    rock_miss_loss: float = 1.0 / 42.0
    rock_hit_gain: float = (1.0 / 42.0) / 4.0
    rock_overstrum_mult: float = 0.333   # overstrum hasari = miss hasari x bu
    rock_sp_hit_mult: float = 5.0        # SP aktifken isabet kazanci x bu
    no_fail: bool = True                 # R13: No Fail varsayilan acik

    # §5.4 Yildiz esikleri: FC + tum sustain'ler + SP'siz taban skorun katlari (1..5 yildiz, altin)
    star_thresholds: tuple = (0.06, 0.12, 0.20, 0.47, 0.78, 1.15)

    @property
    def window_front(self) -> float:
        """Notadan ONCE vurulabilecek sure (pozitif saniye)."""
        return abs(self.hit_window / 2.0) * self.front_to_back_ratio * self.window_scale

    @property
    def window_back(self) -> float:
        """Notadan SONRA vurulabilecek sure (pozitif saniye)."""
        return abs(self.hit_window / 2.0) * (2.0 - self.front_to_back_ratio) * self.window_scale


# --- Chart okuma ------------------------------------------------------------

@dataclass
class ChartConfig:
    # §2.1 .chart HOPO esigi: floor(65/192 * res) tick (480'de 162)
    chart_hopo_ratio: float = 65.0 / 192.0
    # §2.2 .mid HOPO esigi: floor(res/3) + 1 tick (480'de 161); song.ini hopo_frequency ezer
    # §1.8 .mid sustain cutoff: floor(res/3)+1 tick'ten kisa sustain -> normal nota; .chart'ta kesilmez
    pass


# --- Goruntu / ses ----------------------------------------------------------

@dataclass
class VideoConfig:
    width: int = 1280
    height: int = 720
    fullscreen: bool = False
    fps_limit: int = 0               # 0 = monitor hizi (vsync)
    vsync: bool = True
    note_speed: float = 1.0          # "hyperspeed" carpani
    highway_length: float = 1.0      # gorunen sure carpani
    video_offset_ms: int = 0         # R04: goruntu offseti
    show_debug: bool = False


@dataclass
class AudioConfig:
    sample_rate: int = 44100
    buffer: int = 512
    audio_offset_ms: int = 0         # R04: ses offseti (kalibrasyon ile)
    master_volume: float = 0.9
    sfx_volume: float = 0.6


@dataclass
class KeyConfig:
    # Kullanici tercihi: perdeler 1-5, Space = strum (vurus). pygame.key.key_code isimleri.
    # Acik notalar normal strum ile (hic perde basmadan) calinir; ayri acik-strum tusu opsiyonel.
    frets: tuple = (("1",), ("2",), ("3",), ("4",), ("5",))
    strum_up: tuple = ("space", "up")
    strum_down: tuple = ("down",)
    open_strum: tuple = ()
    star_power: tuple = ("h", "right shift")
    whammy: tuple = (";", "'")
    start: tuple = ("return",)
    pause: tuple = ("escape",)


@dataclass
class Settings:
    engine: EngineConfig = field(default_factory=EngineConfig)
    chart: ChartConfig = field(default_factory=ChartConfig)
    video: VideoConfig = field(default_factory=VideoConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    keys: KeyConfig = field(default_factory=KeyConfig)
