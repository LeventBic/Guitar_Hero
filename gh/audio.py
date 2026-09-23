"""Ses: mixer kurulumu, efekt sesleri ve Conductor (tek sarki saati, R03/D04).

Conductor tasarimi
------------------
- Saat `time.perf_counter` tabanli ve monotondur; her frame yeniden hesaplanir (biriktirilmez).
- Ana stem (song.ogg, yoksa ilk stem) `pygame.mixer.music` ile, diger stem'ler (guitar, rhythm, ...)
  ayrilmis kanallarda `Sound` olarak calar. Hepsi AYNI cagrida, sarki saati 0'i gectiginde baslatilir
  (SDL_mixer hepsini ayni ses callback'inde karistirmaya baslar).
- `music.get_pos()` ses callback'ine bagli gercek bir "ses saati" verir. Ondan (perf_counter - pos) ile
  cikarilan baslangic tahmininin medyani hedef alinir; saat ona yavasca (frame dt'nin %5'i) kaydirilir.
  Boylece "Sound.play bir sonraki buffer'da baslar" kaynakli 0..buffer ms'lik rastgele faz yok olur ve
  sapma (drift) olculup gosterilebilir. Buyuk sapmada (takilma) saat hedefe atlar.
- SongTime (yargi)  = ses_pozisyonu - chart.offset - audio_offset
  VisualTime (cizim) = SongTime + video_offset
- `sim=True`: ses calinmaz, saat `advance(dt)` ile ilerler (headless smoke / ekran goruntusu).
"""
from __future__ import annotations

import io
import math
import statistics
import time
import wave
from collections import deque

import numpy as np
import pygame

try:  # Ajan C'nin efekt sentezleyicisi; yoksa basit yedekler kullanilir
    from . import sfx as _sfx_mod
except Exception:  # pragma: no cover - modul henuz yoksa
    _sfx_mod = None

NUM_CHANNELS = 32
STEM_CHANNELS = 10
GUITAR_FADE_OUT = 0.045   # s: miss/overstrum'da gitar kisilmasi
GUITAR_FADE_IN = 0.020


# --------------------------------------------------------------------------- yardimcilar

def _fallback_sfx(sr: int) -> dict[str, np.ndarray]:
    """gh.sfx yoksa kullanilan basit sentez sesler (ayni isimler)."""
    def tone(freqs, dur, vol=0.4, decay=8.0, noise=0.0, sweep=0.0):
        n = int(sr * dur)
        t = np.arange(n) / sr
        sig = np.zeros(n)
        for f in freqs:
            ph = 2 * np.pi * (f * t + 0.5 * sweep * t * t)
            sig += np.sin(ph)
        sig /= max(1, len(freqs))
        if noise:
            sig = sig * (1 - noise) + noise * np.random.default_rng(1).uniform(-1, 1, n)
        env = np.exp(-decay * t) * np.minimum(1.0, t * 400)
        s = (sig * env * vol * 32767).astype(np.int16)
        return np.ascontiguousarray(np.stack([s, s], axis=1))

    return {
        "miss_buzz": tone([90, 93], 0.22, 0.45, 12, noise=0.35),
        "sp_ready": tone([880, 1320], 0.35, 0.3, 6),
        "sp_activate": tone([440, 660, 990], 0.8, 0.35, 3, sweep=400),
        "sp_phrase_complete": tone([1046, 1568], 0.3, 0.3, 8),
        "sp_deactivate": tone([660, 440], 0.4, 0.3, 6, sweep=-300),
        "menu_move": tone([1200], 0.05, 0.2, 60),
        "menu_select": tone([880, 1320], 0.14, 0.3, 20),
        "menu_back": tone([500], 0.1, 0.25, 30),
        "crowd_cheer": tone([300], 1.5, 0.25, 1.5, noise=0.95),
        "fail_sound": tone([220, 207], 1.2, 0.4, 2, sweep=-80),
        "countdown_tick": tone([1500], 0.06, 0.35, 50),
        "metronome_hi": tone([1760], 0.05, 0.5, 70),
        "metronome_lo": tone([1320], 0.05, 0.45, 70),
    }


def to_mixer_array(arr: np.ndarray, channels: int) -> np.ndarray:
    """int16 (n,2) diziyi mixer kanal sayisina uyarla."""
    a = np.asarray(arr)
    if a.dtype != np.int16:
        if np.issubdtype(a.dtype, np.floating):
            a = np.clip(a * 32767.0, -32768, 32767).astype(np.int16)
        else:
            a = a.astype(np.int16)
    if a.ndim == 1:
        a = a[:, None]
    if a.shape[1] != channels:
        if channels == 1:
            a = a.mean(axis=1, keepdims=True).astype(np.int16)
        else:
            a = np.repeat(a[:, :1], channels, axis=1)
    return np.ascontiguousarray(a)


def wav_bytes(arr: np.ndarray, sr: int) -> io.BytesIO:
    """int16 (n,ch) diziyi bellek ici WAV dosyasina yaz (music.load icin)."""
    a = np.ascontiguousarray(arr.astype(np.int16))
    if a.ndim == 1:
        a = a[:, None]
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(a.shape[1])
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(a.tobytes())
    buf.seek(0)
    return buf


# --------------------------------------------------------------------------- AudioSystem

class AudioSystem:
    """Mixer + efekt sesleri + menu onizleme muzigi."""

    def __init__(self, settings, enabled: bool = True):
        self.settings = settings
        self.ok = False
        self.sr = settings.audio.sample_rate
        self.channels = 2
        self.sfx: dict[str, pygame.mixer.Sound] = {}
        self.error = ""
        self.preview_path = ""
        if enabled:
            self._init_mixer()

    def _init_mixer(self) -> None:
        a = self.settings.audio
        try:
            if pygame.mixer.get_init():
                pygame.mixer.quit()
            pygame.mixer.pre_init(a.sample_rate, -16, 2, a.buffer)
            pygame.mixer.init(a.sample_rate, -16, 2, a.buffer)
            init = pygame.mixer.get_init()
            if not init:
                raise pygame.error("mixer init failed")
            self.sr, _fmt, self.channels = init
            pygame.mixer.set_num_channels(NUM_CHANNELS)
            pygame.mixer.set_reserved(STEM_CHANNELS)
            self.ok = True
        except Exception as exc:  # ses aygiti yoksa oyun sessiz calisir
            self.ok = False
            self.error = f"{type(exc).__name__}: {exc}"
            return
        self._build_sfx()

    def _build_sfx(self) -> None:
        arrays: dict[str, np.ndarray] = {}
        if _sfx_mod is not None and hasattr(_sfx_mod, "build_all"):
            try:
                arrays = dict(_sfx_mod.build_all(self.sr))
                aliases = {"miss": "miss_buzz", "fail": "fail_sound", "metronome_accent": "metronome_hi",
                           "metronome": "metronome_lo"}
                for src, dst in aliases.items():
                    if src in arrays and dst not in arrays:
                        arrays[dst] = arrays[src]
                if "metronome_hi" not in arrays and hasattr(_sfx_mod, "metronome"):
                    arrays["metronome_hi"] = _sfx_mod.metronome(self.sr, True)
                    arrays["metronome_lo"] = _sfx_mod.metronome(self.sr, False)
            except Exception as exc:
                self.error = f"sfx: {type(exc).__name__}: {exc}"
                arrays = {}
        fb = _fallback_sfx(self.sr)
        for k, v in fb.items():
            arrays.setdefault(k, v)
        for name, arr in arrays.items():
            try:
                self.sfx[name] = pygame.sndarray.make_sound(to_mixer_array(arr, self.channels))
            except Exception:
                continue

    def sfx_array(self, name: str) -> np.ndarray | None:
        """Ham efekt dizisi (kalibrasyon tiklama izi icin)."""
        s = self.sfx.get(name)
        if s is None:
            return None
        try:
            return pygame.sndarray.array(s)
        except Exception:
            return None

    def play_sfx(self, name: str, volume: float = 1.0) -> None:
        if not self.ok:
            return
        s = self.sfx.get(name)
        if s is None:
            return
        a = self.settings.audio
        try:
            ch = s.play()
            if ch is not None:
                ch.set_volume(max(0.0, min(1.0, volume * a.sfx_volume * a.master_volume)))
        except Exception:
            pass

    # ---- menu onizleme (mixer.music)
    def play_preview(self, path: str, start_s: float = 0.0) -> None:
        if not self.ok or not path:
            return
        if path == self.preview_path and pygame.mixer.music.get_busy():
            return
        try:
            pygame.mixer.music.stop()
            pygame.mixer.music.load(path)
            pygame.mixer.music.set_volume(0.55 * self.settings.audio.master_volume)
            pygame.mixer.music.play(loops=-1, start=max(0.0, start_s), fade_ms=900)
            self.preview_path = path
        except Exception:
            self.preview_path = ""

    def stop_preview(self, fade_ms: int = 300) -> None:
        if not self.ok:
            return
        self.preview_path = ""
        try:
            if fade_ms > 0 and pygame.mixer.music.get_busy():
                pygame.mixer.music.fadeout(fade_ms)
            else:
                pygame.mixer.music.stop()
        except Exception:
            pass

    def stop_all(self) -> None:
        if not self.ok:
            return
        self.preview_path = ""
        try:
            pygame.mixer.music.stop()
            pygame.mixer.stop()
        except Exception:
            pass

    def reinit(self) -> None:
        """Buffer / sample rate degisince mixer'i yeniden kur."""
        self.stop_all()
        self.sfx.clear()
        self._init_mixer()


# --------------------------------------------------------------------------- Conductor

class _Stem:
    __slots__ = ("name", "sound", "channel", "is_music")

    def __init__(self, name, sound=None, channel=None, is_music=False):
        self.name = name
        self.sound = sound
        self.channel = channel
        self.is_music = is_music


class Conductor:
    LEADIN, PLAYING, ENDED = 0, 1, 2

    def __init__(self, audio: AudioSystem | None, stems: dict[str, str] | None = None, *,
                 chart_offset: float = 0.0, audio_offset: float = 0.0, video_offset: float = 0.0,
                 lead_in: float = 2.7, sim: bool = False, music_file=None, length: float = 0.0):
        self.audio = audio if (audio is not None and audio.ok) else None
        self.sim = sim                      # saat advance() ile ilerler
        self.live = (not sim) and self.audio is not None   # gercekten ses caliniyor mu
        self.stem_paths = dict(stems or {})
        self.music_file = music_file          # BytesIO (kalibrasyon tiklama izi) veya None
        self.chart_offset = chart_offset
        self.audio_offset = audio_offset
        self.video_offset = video_offset
        self.lead_in = lead_in
        self.length = length
        self.stems: list[_Stem] = []
        self.music: _Stem | None = None
        self.guitar: _Stem | None = None
        self.state = self.LEADIN
        self.paused = False
        self._start_pc = 0.0
        self._pause_pos = 0.0
        self._sim_pos = -lead_in
        self._last_frame_time = -math.inf
        self._last_pc = time.perf_counter()
        self._anchor = deque(maxlen=120)
        self._next_anchor_pc = 0.0
        self.drift = 0.0                    # s: saatimiz - ses saati (debug)
        self.anchored = False
        self.guitar_gain = 1.0
        self.guitar_target = 1.0
        self.volume = 1.0
        self.load_errors: list[str] = []
        self.frame_time = -lead_in - chart_offset - audio_offset

    # ---- yukleme
    def load(self) -> None:
        if self.audio is None:
            return
        paths = self.stem_paths
        music_name = None
        if self.music_file is None:
            if "song" in paths:
                music_name = "song"
            else:
                others = [k for k in paths if k not in ("guitar", "preview", "crowd")]
                music_name = others[0] if others else ("guitar" if "guitar" in paths else None)
        ch_i = 0
        try:
            if self.music_file is not None:
                pygame.mixer.music.load(self.music_file, "wav")
                self.music = _Stem("music", is_music=True)
            elif music_name:
                pygame.mixer.music.load(paths[music_name])
                self.music = _Stem(music_name, is_music=True)
        except Exception as exc:
            self.load_errors.append(f"{music_name}: {exc}")
            self.music = None
        if self.music is not None:
            self.stems.append(self.music)
            if self.music.name == "guitar":
                self.guitar = self.music
        for name, path in paths.items():
            if name in ("preview",) or (self.music is not None and name == self.music.name):
                continue
            if ch_i >= STEM_CHANNELS:
                break
            try:
                snd = pygame.mixer.Sound(path)
            except Exception as exc:
                self.load_errors.append(f"{name}: {exc}")
                continue
            st = _Stem(name, snd, pygame.mixer.Channel(ch_i))
            ch_i += 1
            self.stems.append(st)
            if name == "guitar":
                self.guitar = st
            if not self.length:
                try:
                    self.length = max(self.length, snd.get_length())
                except Exception:
                    pass
        self._apply_volumes()

    # ---- saat
    def start(self) -> None:
        self.state = self.LEADIN
        self.paused = False
        if self.sim:
            self._sim_pos = -self.lead_in
        else:
            self._start_pc = time.perf_counter() + self.lead_in
        self._last_frame_time = -math.inf
        self.frame_time = self.song_time()

    def audio_pos(self, pc: float | None = None) -> float:
        if self.sim:
            return self._sim_pos
        if self.paused:
            return self._pause_pos
        return (time.perf_counter() if pc is None else pc) - self._start_pc

    def song_time(self, pc: float | None = None) -> float:
        return self.audio_pos(pc) - self.chart_offset - self.audio_offset

    def visual_time(self) -> float:
        return self.frame_time + self.video_offset

    def song_to_audio_pos(self, t: float) -> float:
        return t + self.chart_offset + self.audio_offset

    def advance(self, dt: float) -> None:
        """sim modu: saati ilerlet."""
        if self.sim and not self.paused:
            self._sim_pos += dt

    def update(self) -> float:
        """Frame basina bir kez. Oynatmayi baslatir, saati ses saatine hizalar, gitar sesini yumusatir.
        Monoton frame zamanini (SongTime) dondurur."""
        pc = time.perf_counter()
        dt = max(0.0, pc - self._last_pc)
        self._last_pc = pc
        if not self.paused:
            pos = self.audio_pos(pc)
            if self.state == self.LEADIN and pos >= 0.0:
                self._begin_playback()
            elif self.state == self.PLAYING and self.live:
                self._track_anchor(pc, dt)
        t = self.song_time()
        if t < self._last_frame_time:
            t = self._last_frame_time
        self._last_frame_time = t
        self.frame_time = t
        self._update_gain(dt if not self.sim else 1.0 / 60.0)
        return t

    def _begin_playback(self) -> None:
        self.state = self.PLAYING
        if not self.live:
            return
        pc = time.perf_counter()
        try:
            if self.music is not None:
                pygame.mixer.music.play()
            for st in self.stems:
                if not st.is_music and st.channel is not None:
                    st.channel.play(st.sound)
        except Exception as exc:
            self.load_errors.append(f"play: {exc}")
        # ses konumu 0 = play cagrisi (gec kaldiysak saat birkac ms geri alinir; frame saati monoton)
        self._start_pc = pc
        self._anchor.clear()
        self._apply_volumes()

    def _track_anchor(self, pc: float, dt: float) -> None:
        if self.music is None or pc < self._next_anchor_pc:
            return
        self._next_anchor_pc = pc + 0.004
        try:
            if not pygame.mixer.music.get_busy():
                return
            pos_ms = pygame.mixer.music.get_pos()
        except Exception:
            return
        if pos_ms <= 0:
            return
        self._anchor.append(pc - pos_ms / 1000.0)
        if len(self._anchor) < 12:
            return
        target = statistics.median(self._anchor)
        diff = target - self._start_pc
        self.drift = diff
        self.anchored = True
        if abs(diff) > 0.060:
            self._start_pc = target          # takilma / buffer underrun: dogrudan hizala
            self._anchor.clear()
        else:
            step = 0.05 * max(dt, 0.0005)
            self._start_pc += max(-step, min(step, diff))

    # ---- duraklatma
    def pause(self) -> None:
        if self.paused:
            return
        self._pause_pos = self.audio_pos()
        self.paused = True
        if not self.live:
            return
        try:
            if self.music is not None:
                pygame.mixer.music.pause()
            for st in self.stems:
                if st.channel is not None:
                    st.channel.pause()
        except Exception:
            pass

    def resume(self) -> None:
        if not self.paused:
            return
        self.paused = False
        if self.sim:
            return
        self._start_pc = time.perf_counter() - self._pause_pos
        self._anchor.clear()
        if not self.live:
            return
        try:
            if self.state == self.PLAYING:
                if self.music is not None:
                    pygame.mixer.music.unpause()
                for st in self.stems:
                    if st.channel is not None:
                        st.channel.unpause()
        except Exception:
            pass

    def stop(self) -> None:
        self.state = self.ENDED
        if not self.live:
            return
        try:
            if self.music is not None:
                pygame.mixer.music.stop()
            for st in self.stems:
                if st.channel is not None:
                    st.channel.stop()
        except Exception:
            pass

    def fadeout(self, ms: int) -> None:
        if not self.live:
            return
        try:
            if self.music is not None:
                pygame.mixer.music.fadeout(ms)
            for st in self.stems:
                if st.channel is not None:
                    st.channel.fadeout(ms)
        except Exception:
            pass

    @property
    def music_busy(self) -> bool:
        if not self.live or self.music is None:
            return self.state == self.PLAYING
        try:
            return pygame.mixer.music.get_busy()
        except Exception:
            return False

    # ---- ses seviyeleri
    def set_volume(self, v: float) -> None:
        self.volume = max(0.0, min(1.0, v))
        self._apply_volumes()

    def set_guitar_muted(self, muted: bool) -> None:
        self.guitar_target = 0.0 if muted else 1.0

    def _update_gain(self, dt: float) -> None:
        g, tgt = self.guitar_gain, self.guitar_target
        if g == tgt:
            return
        if tgt < g:
            g = max(tgt, g - dt / GUITAR_FADE_OUT)
        else:
            g = min(tgt, g + dt / GUITAR_FADE_IN)
        self.guitar_gain = g
        if self.guitar is not None and self.live:
            self._set_stem_volume(self.guitar, self.volume * g)

    def _set_stem_volume(self, st: _Stem, v: float) -> None:
        try:
            if st.is_music:
                pygame.mixer.music.set_volume(v)
            elif st.channel is not None:
                st.channel.set_volume(v)
        except Exception:
            pass

    def _apply_volumes(self) -> None:
        if not self.live:
            return
        for st in self.stems:
            v = self.volume * (self.guitar_gain if st is self.guitar else 1.0)
            self._set_stem_volume(st, v)
