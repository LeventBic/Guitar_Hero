"""Sarki klasoru yukleme ve tarama (ek-01 §2.4, R08).

load_song(folder) -> Chart         : song.ini + notes.mid (varsa, Clone Hero gibi oncelikli) / notes.chart
scan_songs(root, errors=None) -> list[SongInfo]
    Yalniz metadata (notalar parse edilmez). Hatali sarki atlanir; hatalar (klasor, mesaj) olarak
    `errors` listesine (verildiyse) ve modul duzeyindeki `last_scan_errors` listesine yazilir.
"""
from __future__ import annotations

import os

from ..models import Chart, SongInfo
from .chart_parser import _apply_chart_meta, _split_sections, _unquote, parse_chart
from .midi_parser import parse_midi
from .song_ini import fill_song_info, read_song_ini, read_text_file

AUDIO_EXTS = (".ogg", ".opus", ".mp3", ".wav", ".flac")
SKIP_DIRS = ("_import",)   # ice aktarma gelen kutusu (Songs/_Import) sarki olarak taranmaz
STEM_NAMES = ("song", "guitar", "rhythm", "bass", "keys", "vocals", "vocals_1", "vocals_2",
              "drums", "drums_1", "drums_2", "drums_3", "drums_4", "crowd", "preview")
ALBUM_NAMES = ("album.png", "album.jpg", "album.jpeg")
CHART_NAMES = ("notes.mid", "notes.chart")   # oncelik sirasi (Clone Hero: .mid once)

last_scan_errors: list[tuple[str, str]] = []


def _listing(folder: str) -> dict[str, str]:
    """kucuk harfli dosya adi -> gercek tam yol (yalniz dosyalar)."""
    out: dict[str, str] = {}
    try:
        with os.scandir(folder) as it:
            for e in it:
                try:
                    if e.is_file():
                        out.setdefault(e.name.lower(), e.path)
                except OSError:
                    continue
    except OSError:
        pass
    return out


def find_chart_file(folder: str, files: dict[str, str] | None = None) -> str:
    files = files if files is not None else _listing(folder)
    for name in CHART_NAMES:
        if name in files:
            return files[name]
    return ""


def find_stems(folder: str, files: dict[str, str] | None = None) -> dict[str, str]:
    files = files if files is not None else _listing(folder)
    stems: dict[str, str] = {}
    for stem in STEM_NAMES:
        for ext in AUDIO_EXTS:
            p = files.get(stem + ext)
            if p:
                stems[stem] = p
                break
    return stems


def _folder_info(folder: str, files: dict[str, str]) -> SongInfo:
    """song.ini + dosya yollari; notalar okunmaz."""
    info = SongInfo()
    ini = files.get("song.ini")
    if ini:
        fill_song_info(read_song_ini(ini), info)
    info.folder = folder
    info.chart_path = find_chart_file(folder, files)
    info.album_art = next((files[n] for n in ALBUM_NAMES if n in files), "")
    info.stems = find_stems(folder, files)
    return info


def _fallback_names(info: SongInfo, folder: str) -> None:
    """Ad yoksa klasor adindan ('Sanatci - Sarki') cikar."""
    if info.name in ("", "Unknown"):
        base = os.path.basename(os.path.normpath(folder))
        if " - " in base:
            artist, name = base.split(" - ", 1)
            info.name = name.strip() or base
            if info.artist in ("", "Unknown"):
                info.artist = artist.strip() or info.artist
        else:
            info.name = base


def load_song(folder: str | os.PathLike) -> Chart:
    """Sarki klasorunu tamamen yukle. Chart dosyasi yoksa FileNotFoundError."""
    folder = os.fspath(folder)
    files = _listing(folder)
    info = _folder_info(folder, files)
    if not info.chart_path:
        raise FileNotFoundError(f"notes.chart / notes.mid yok: {folder}")
    if info.chart_path.lower().endswith(".mid"):
        chart = parse_midi(info.chart_path, info)
    else:
        chart = parse_chart(info.chart_path, info)
    _fallback_names(chart.info, folder)
    return chart


def _chart_header_meta(path: str, info: SongInfo) -> None:
    """.chart'in yalniz [Song] bolumunu okuyup eksik metadata'yi doldur (hizli)."""
    text = read_text_file(path)
    head_end = text.find("[SyncTrack]")
    if head_end > 0:
        text = text[:head_end]
    meta: dict[str, str] = {}
    for name, lines in _split_sections(text):
        if name.lower() == "song":
            for line in lines:
                if "=" in line:
                    k, v = line.split("=", 1)
                    meta[k.strip().lower()] = _unquote(v)
    _apply_chart_meta(meta, info)


def scan_songs(root: str | os.PathLike, errors: list[tuple[str, str]] | None = None) -> list[SongInfo]:
    """root altindaki tum sarki klasorlerini (notes.chart/notes.mid iceren) ozyinelemeli bul.

    Sarki klasorunun alt klasorlerine inilmez. Sonuc klasor yoluna gore siralidir.
    """
    last_scan_errors.clear()
    result: list[SongInfo] = []
    root = os.fspath(root)
    if not os.path.isdir(root):
        return result
    for dirpath, dirnames, _filenames in os.walk(root):
        # _Import gibi ayrilmis klasorler ve indirme sirasindaki gecici '.<md5>.part' klasorleri sarki degildir
        dirnames[:] = sorted(d for d in dirnames if d.lower() not in SKIP_DIRS and not d.startswith("."))
        files = _listing(dirpath)
        if not any(n in files for n in CHART_NAMES):
            continue
        dirnames[:] = []  # sarki klasoru: iceri inme
        try:
            info = _folder_info(dirpath, files)
            if info.chart_path.lower().endswith(".chart") and (
                    info.name in ("", "Unknown") or info.artist in ("", "Unknown")):
                _chart_header_meta(info.chart_path, info)
            _fallback_names(info, dirpath)
            result.append(info)
        except Exception as exc:  # tek sarki taramayi bozmamali
            err = (dirpath, f"{type(exc).__name__}: {exc}")
            last_scan_errors.append(err)
            if errors is not None:
                errors.append(err)
    result.sort(key=lambda i: i.folder.lower())
    return result
