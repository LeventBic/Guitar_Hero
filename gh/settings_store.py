"""settings.json oku/yaz (user_root()/settings.json).

Eksik / eski / hatali anahtarlara toleransli: yalnizca bilinen alanlar, tip uyumluysa okunur; kalanlar
varsayilan kalir. Motorun ic mekanik degerleri (hit window vb.) kaydedilmez, yalnizca kullanici ayarlari.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields

from .config import AudioConfig, KeyConfig, Settings, VideoConfig, user_root

SETTINGS_FILE = "settings.json"
VERSION = 2  # 2: varsayilan tuslar 1-5 + Space strum; eski dosyalarin tuslari yok sayilir

# on yuz ekstra tercihleri (config dataclass'larinda olmayanlar)
DEFAULT_EXTRA = {
    "autoplay": False,
    "last_song": "",
    "last_difficulty": "expert",
    "calibrated": False,
    "joy_deadzone": 0.35,
    "tilt_threshold": 0.55,
    "show_timing": True,
}


@dataclass
class AppSettings(Settings):
    extra: dict = field(default_factory=lambda: dict(DEFAULT_EXTRA))


def settings_path() -> str:
    return os.path.join(user_root(), SETTINGS_FILE)


def default_settings() -> AppSettings:
    s = AppSettings()
    # on yuz varsayilanlari: vsync kapali (girdi olcumu icin dongu yuksek hizda doner), 240 fps sinir
    s.video.vsync = False
    s.video.fps_limit = 240
    return s


def _coerce(value, default):
    """value'yu default'un tipine cevir; olmazsa ValueError."""
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        raise ValueError
    if isinstance(default, int):
        if isinstance(value, bool):
            raise ValueError
        return int(round(float(value)))
    if isinstance(default, float):
        if isinstance(value, bool):
            raise ValueError
        return float(value)
    if isinstance(default, str):
        if not isinstance(value, str):
            raise ValueError
        return value
    if isinstance(default, tuple):
        if not isinstance(value, (list, tuple)):
            raise ValueError
        if default and isinstance(default[0], tuple):
            out = []
            for item in value:
                if isinstance(item, str):
                    out.append((item,))
                elif isinstance(item, (list, tuple)):
                    out.append(tuple(str(x) for x in item))
            if len(out) != len(default):
                raise ValueError
            return tuple(out)
        return tuple(str(x) for x in value)
    return value


def _apply(obj, data: dict) -> None:
    if not isinstance(data, dict):
        return
    for f in fields(obj):
        if f.name not in data:
            continue
        default = getattr(obj, f.name)
        try:
            setattr(obj, f.name, _coerce(data[f.name], default))
        except (ValueError, TypeError):
            pass


def _to_dict(obj) -> dict:
    out = {}
    for f in fields(obj):
        v = getattr(obj, f.name)
        if isinstance(v, tuple):
            v = [list(x) if isinstance(x, tuple) else x for x in v]
        out[f.name] = v
    return out


def clamp_settings(s: AppSettings) -> None:
    v = s.video
    v.note_speed = min(3.0, max(0.5, v.note_speed))
    v.highway_length = min(1.5, max(0.6, v.highway_length))
    v.video_offset_ms = int(min(500, max(-500, v.video_offset_ms)))
    v.fps_limit = int(min(1000, max(0, v.fps_limit)))
    a = s.audio
    a.audio_offset_ms = int(min(500, max(-500, a.audio_offset_ms)))
    a.master_volume = min(1.0, max(0.0, a.master_volume))
    a.sfx_volume = min(1.0, max(0.0, a.sfx_volume))
    if a.buffer not in (256, 512, 1024, 2048):
        a.buffer = 512
    if a.sample_rate not in (22050, 44100, 48000):
        a.sample_rate = 44100


def load_settings(path: str | None = None) -> AppSettings:
    s = default_settings()
    path = path or settings_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return s
    if not isinstance(data, dict):
        return s
    _apply(s.video, data.get("video", {}))
    _apply(s.audio, data.get("audio", {}))
    if isinstance(data.get("version"), int) and data["version"] >= 2:
        _apply(s.keys, data.get("keys", {}))
    eng = data.get("engine", {})
    if isinstance(eng, dict) and isinstance(eng.get("no_fail"), bool):
        s.engine.no_fail = eng["no_fail"]
    extra = data.get("extra", {})
    if isinstance(extra, dict):
        for k, dv in DEFAULT_EXTRA.items():
            if k in extra:
                try:
                    s.extra[k] = _coerce(extra[k], dv)
                except (ValueError, TypeError):
                    pass
    clamp_settings(s)
    return s


_READONLY = False


def set_readonly(flag: bool) -> None:
    """Headless calismalar (smoke, ekran goruntusu, testler) kullanicinin settings.json'ina yazmasin."""
    global _READONLY
    _READONLY = bool(flag)


def save_settings(s: AppSettings, path: str | None = None) -> bool:
    if _READONLY and path is None:
        return False
    path = path or settings_path()
    data = {
        "version": VERSION,
        "engine": {"no_fail": bool(s.engine.no_fail)},
        "video": _to_dict(s.video),
        "audio": _to_dict(s.audio),
        "keys": _to_dict(s.keys),
        "extra": dict(s.extra),
    }
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def default_keys() -> KeyConfig:
    return KeyConfig()


__all__ = ["AppSettings", "load_settings", "save_settings", "default_settings", "settings_path",
           "default_keys", "clamp_settings", "VideoConfig", "AudioConfig"]
