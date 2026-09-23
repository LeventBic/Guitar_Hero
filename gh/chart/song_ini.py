"""song.ini okuyucu (ek-01 §2.3).

`read_song_ini(path) -> dict` : anahtarlar kucuk harf, yalniz [song] bolumu (bolum basligi yoksa
dosyanin basindaki anahtarlar da kabul edilir). `fill_song_info(ini, info)` SongInfo alanlarini doldurur.
"""
from __future__ import annotations

import os
import re

from ..models import SongInfo

_RICH_TAG = re.compile(r"</?(?:b|i|u|s|br|color|size|material|quad|sprite|align|alpha|mark|sup|sub)\b[^>]*>", re.I)


def strip_rich_text(s: str) -> str:
    """Clone Hero / Unity zengin metin etiketleri (<b>, <color=#..>, <size=..>, <br> ...) -> duz metin."""
    if "<" not in s:
        return s
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    return re.sub(r"\s+", " ", _RICH_TAG.sub("", s)).strip()


def decode_text(data: bytes) -> str:
    """BOM/kodlama toleransli metin cozme: UTF-16 BOM, utf-8(-sig), cp1252, latin-1."""
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            pass
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def read_text_file(path: str | os.PathLike) -> str:
    with open(path, "rb") as f:
        return decode_text(f.read())


def parse_song_ini_text(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    section: str | None = None
    for raw in text.splitlines():
        line = raw.strip().lstrip("﻿")
        if not line or line[0] in ";#":
            continue
        if line.startswith("[") and "]" in line:
            section = line[1:line.index("]")].strip().lower()
            continue
        if "=" not in line:
            continue
        if section not in (None, "song"):
            continue
        key, value = line.split("=", 1)
        key = key.strip().lower()
        if key:
            result[key] = value.strip()
    return result


def read_song_ini(path: str | os.PathLike) -> dict[str, str]:
    """song.ini'yi oku. Anahtarlar kucuk harfli; degerler bosluklari kirpilmis string."""
    return parse_song_ini_text(read_text_file(path))


# --- SongInfo doldurma --------------------------------------------------------

def _int(value: str | None, default: int | None) -> int | None:
    if value is None:
        return default
    v = value.strip()
    if not v:
        return default
    try:
        return int(v)
    except ValueError:
        try:
            return int(float(v))
        except ValueError:
            return default


def _bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in ("1", "true", "yes", "on")


def fill_song_info(ini: dict[str, str], info: SongInfo | None = None) -> SongInfo:
    """ini sozlugundeki bilinen etiketleri SongInfo'ya yaz (olmayan alanlar degismez)."""
    info = info if info is not None else SongInfo()
    for key, attr in (("name", "name"), ("artist", "artist"), ("album", "album"),
                      ("genre", "genre"), ("year", "year")):
        v = strip_rich_text(ini.get(key) or "")
        if v:
            setattr(info, attr, v)
    charter = strip_rich_text(ini.get("charter") or ini.get("frets") or "")
    if charter:
        info.charter = charter
    info.song_length_ms = _int(ini.get("song_length"), info.song_length_ms)
    info.preview_start_ms = _int(ini.get("preview_start_time"), info.preview_start_ms)
    info.delay_ms = _int(ini.get("delay"), info.delay_ms)
    hf = _int(ini.get("hopo_frequency"), None)
    if hf is not None and hf > 0:
        info.hopo_frequency = hf
    sc = _int(ini.get("sustain_cutoff_threshold"), None)
    if sc is not None and sc >= 0:
        info.sustain_cutoff_threshold = sc
    info.diff_guitar = _int(ini.get("diff_guitar"), info.diff_guitar)
    if "eighthnote_hopo" in ini:
        info.eighthnote_hopo = _bool(ini.get("eighthnote_hopo"))
    if "auto_chart" in ini:
        info.auto_chart = _bool(ini.get("auto_chart"))
    if ini.get("auto_chart_mode"):
        info.auto_chart_mode = ini["auto_chart_mode"].strip().lower()
    mn = _int(ini.get("multiplier_note"), None)
    if mn in (103, 116):
        info.multiplier_note = mn
    return info


def load_song_info(path: str | os.PathLike, info: SongInfo | None = None) -> SongInfo:
    return fill_song_info(read_song_ini(path), info)
