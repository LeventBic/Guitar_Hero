"""Kendi sarkini ekle: ses dosyasi -> Clone Hero sarki klasoru (otomatik chart ile).

import_audio(path, songs_root, progress=None) -> yeni sarki klasoru
rechart_song(folder, progress=None)              -> otomatik chart'i yeniden uret
import_song_folder(path, songs_root)             -> hazir CH klasorunu (notes.chart/mid) kopyala
collect_audio_files(paths) / inbox_dir() / inbox_files()

Arka plan is parcaciginda calismaya uygundur: ekran cagrisi yok; ses cozme pygame.mixer.Sound ile
(mixer acik degilse kapali 'dummy' surucusuyle acilir), yazi tipi kullanilmaz. Ilerleme: progress(0..1, metin).
Herhangi bir hatada yarim klasor silinir ve ImportFailed firlatilir.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import threading
import wave

import numpy as np

from .audio_meta import AudioMeta, meta_from_filename, read_metadata

AUDIO_EXTS = (".mp3", ".ogg", ".wav", ".flac", ".opus")
INBOX_NAME = "_Import"
MIN_SECONDS = 10.0
MAX_SECONDS = 15 * 60.0
AUTO_CHART_VERSION = 1

_decode_lock = threading.Lock()


class ImportFailed(Exception):
    """Kullaniciya gosterilebilir hata mesaji. `key` + `params`: arayuzun cevirebilmesi icin (gh.i18n)."""

    def __init__(self, message: str, key: str = "", **params):
        super().__init__(message)
        self.key = key
        self.params = params


def _progress(cb, frac: float, text: str) -> None:
    if cb is not None:
        try:
            cb(max(0.0, min(1.0, float(frac))), text)
        except Exception:
            pass


# --------------------------------------------------------------------------- yollar

def songs_dir() -> str:
    from .config import user_root
    return os.path.join(user_root(), "Songs")


def inbox_dir(create: bool = True) -> str:
    p = os.path.join(songs_dir(), INBOX_NAME)
    if create:
        try:
            os.makedirs(p, exist_ok=True)
        except OSError:
            pass
    return p


def is_audio_file(path: str) -> bool:
    return os.path.isfile(path) and path.lower().endswith(AUDIO_EXTS)


def is_song_folder(path: str) -> bool:
    if not os.path.isdir(path):
        return False
    try:
        names = {n.lower() for n in os.listdir(path)}
    except OSError:
        return False
    return bool(names & {"notes.chart", "notes.mid"})


def collect_audio_files(paths, max_files: int = 500) -> list[str]:
    """Dosya/klasor listesi -> ses dosyalari + hazir sarki klasorleri (klasorler ozyinelemeli, sirali)."""
    out: list[str] = []
    seen: set[str] = set()

    def add(p):
        k = os.path.normcase(os.path.abspath(p))
        if k not in seen:
            seen.add(k)
            out.append(p)

    for p in paths:
        p = os.fspath(p)
        if is_song_folder(p):
            add(p)
        elif os.path.isdir(p):
            for dirpath, dirnames, filenames in os.walk(p):
                dirnames.sort()
                if is_song_folder(dirpath):
                    add(dirpath)
                    dirnames[:] = []
                    continue
                for fn in sorted(filenames):
                    fp = os.path.join(dirpath, fn)
                    if fn.lower().endswith(AUDIO_EXTS):
                        add(fp)
        elif is_audio_file(p):
            add(p)
        if len(out) >= max_files:
            break
    return out[:max_files]


def inbox_files() -> list[str]:
    d = inbox_dir(create=False)
    if not os.path.isdir(d):
        return []
    return collect_audio_files([os.path.join(d, n) for n in sorted(os.listdir(d))])


# --------------------------------------------------------------------------- ses cozme

def _ensure_mixer() -> None:
    import pygame
    if pygame.mixer.get_init():
        return
    try:
        pygame.mixer.init(44100, -16, 2, 1024)
    except pygame.error:
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.mixer.init(44100, -16, 2, 1024)


def _decode_wav(path: str) -> tuple[np.ndarray, int]:
    with wave.open(path, "rb") as w:
        ch, sw, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if sw == 2:
        a = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif sw == 1:
        a = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sw == 4:
        a = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    elif sw == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        v = np.where(v >= 1 << 23, v - (1 << 24), v)
        a = v.astype(np.float32) / float(1 << 23)
    else:
        raise ImportFailed(f"unsupported WAV sample width ({sw * 8} bit)", "imp.err_decode",
                           err=f"WAV {sw * 8} bit")
    return a.reshape(-1, ch).mean(axis=1), sr


def decode_audio(path: str) -> tuple[np.ndarray, int]:
    """Dosyayi mono float32'ye coz. (ornekler, sr)."""
    err = None
    try:
        import pygame
        with _decode_lock:
            _ensure_mixer()
            snd = pygame.mixer.Sound(path)
            arr = pygame.sndarray.array(snd)
            freq, fmt, _ch = pygame.mixer.get_init()
        del snd
        a = np.asarray(arr)
        if a.ndim == 1:
            a = a[:, None]
        if np.issubdtype(a.dtype, np.integer):
            scale = float(max(abs(np.iinfo(a.dtype).min), np.iinfo(a.dtype).max))
            if a.dtype == np.uint8:
                mono = (a.astype(np.float32).mean(axis=1) - 128.0) / 128.0
            else:
                mono = a.astype(np.float32).mean(axis=1) / scale
        else:
            mono = a.astype(np.float32).mean(axis=1)
        return mono, int(freq)
    except Exception as exc:  # pygame yok / ses aygiti yok / bicim desteklenmiyor
        err = exc
    if path.lower().endswith(".wav"):
        try:
            return _decode_wav(path)
        except ImportFailed:
            raise
        except Exception:
            pass
    raise ImportFailed(f"cannot decode audio ({type(err).__name__}: {err})", "imp.err_decode", err=str(err))


# --------------------------------------------------------------------------- klasor adi / ini

_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}


def sanitize_name(name: str, max_len: int = 90) -> str:
    s = _BAD.sub("", name).strip().strip(".").strip()
    s = re.sub(r"\s+", " ", s)[:max_len].rstrip(" .")
    if not s:
        s = "Song"
    if s.lower() in _RESERVED:
        s += "_"
    return s


def unique_folder(root: str, name: str) -> str:
    base = os.path.join(root, name)
    p = base
    k = 2
    while os.path.exists(p):
        p = f"{base} ({k})"
        k += 1
    return p


def resolve_meta(path: str) -> AudioMeta:
    meta = read_metadata(path)
    f_artist, f_title = meta_from_filename(path)
    if not meta.title:
        meta.title = f_title
        if not meta.artist:
            meta.artist = f_artist
    elif not meta.artist:
        meta.artist = f_artist
    meta.title = meta.title or "Unknown Song"
    return meta


def _ini_escape(v: str) -> str:
    return str(v).replace("\r", " ").replace("\n", " ").strip()


def write_song_ini(path: str, meta: AudioMeta, *, length_ms: int, preview_ms: int, diff: int,
                   source: str = "", extra: dict | None = None) -> None:
    lines = ["[song]", f"name = {_ini_escape(meta.title)}", f"artist = {_ini_escape(meta.artist or 'Unknown Artist')}",
             f"album = {_ini_escape(meta.album)}", f"genre = {_ini_escape(meta.genre)}",
             f"year = {_ini_escape(meta.year)}", "charter = RIFF Auto", f"song_length = {int(length_ms)}",
             f"preview_start_time = {int(preview_ms)}", f"diff_guitar = {int(diff)}", "delay = 0",
             "auto_chart = 1", f"auto_chart_version = {AUTO_CHART_VERSION}",
             "loading_phrase = Auto-charted by RIFF: the notes follow the whole mix."]
    if source:
        lines.append(f"auto_chart_source = {_ini_escape(source)}")
    for k, v in (extra or {}).items():
        lines.append(f"{k} = {_ini_escape(v)}")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


def _update_ini(path: str, updates: dict[str, str]) -> None:
    """song.ini'deki anahtarlari guncelle (digerleri korunur)."""
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        lines = ["[song]"]
    done = set()
    for i, line in enumerate(lines):
        if "=" in line:
            k = line.split("=", 1)[0].strip().lower()
            if k in updates:
                lines[i] = f"{k} = {_ini_escape(updates[k])}"
                done.add(k)
    for k, v in updates.items():
        if k not in done:
            lines.append(f"{k} = {_ini_escape(v)}")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


# --------------------------------------------------------------------------- kapak

def write_cover(folder: str, meta: AudioMeta) -> str:
    """Gomulu kapak (varsa) ya da uretilmis kapak -> album.png. Yolu dondurur ('' = yazilamadi)."""
    import pygame
    out = os.path.join(folder, "album.png")
    if meta.cover:
        try:
            hint = "cover.png" if "png" in meta.cover_mime else "cover.jpg"
            img = pygame.image.load(io.BytesIO(meta.cover), hint)
            w, h = img.get_size()
            side = min(w, h)
            if side >= 16:
                sq = pygame.Surface((side, side), pygame.SRCALPHA, 32)   # paletli PNG'ler icin 32 bit
                sq.blit(img, (0, 0), pygame.Rect((w - side) // 2, (h - side) // 2, side, side))
                img = pygame.transform.smoothscale(sq, (512, 512))
                pygame.image.save(img, out)
                return out
        except Exception:
            pass
    try:
        from .album_art import draw_cover
        pygame.image.save(draw_cover(meta.title, meta.artist, text=False), out)
        return out
    except Exception:
        return ""


# --------------------------------------------------------------------------- ana islemler

def _chart_audio(samples, sr, meta: AudioMeta, stream: str, progress, lo=0.15, hi=0.9):
    from .autochart import generate

    def sub(f, t):
        _progress(progress, lo + (hi - lo) * f, t)

    return generate(samples, sr, title=meta.title, artist=meta.artist or "Unknown Artist", album=meta.album,
                    year=meta.year, genre=meta.genre, music_stream=stream, progress=sub)


def import_audio(path: str, songs_root: str, progress=None) -> str:
    """Ses dosyasini ice aktar; yeni sarki klasorunun yolunu dondur."""
    path = os.fspath(path)
    if not os.path.isfile(path):
        raise ImportFailed("file not found", "imp.err_not_found")
    ext = os.path.splitext(path)[1].lower()
    if ext not in AUDIO_EXTS:
        raise ImportFailed(f"unsupported file type '{ext or '?'}' (use MP3, OGG, WAV, FLAC or OPUS)", "imp.err_type",
                           ext=ext or "?")
    _progress(progress, 0.01, "Reading tags")
    meta = resolve_meta(path)
    _progress(progress, 0.04, "Decoding audio")
    samples, sr = decode_audio(path)
    dur = samples.size / float(sr or 1)
    if dur < MIN_SECONDS:
        raise ImportFailed(f"audio is too short ({dur:.1f} s, need at least {MIN_SECONDS:.0f} s)", "imp.err_short",
                           dur=f"{dur:.1f}", min=f"{MIN_SECONDS:.0f}")
    if dur > MAX_SECONDS:
        raise ImportFailed(f"audio is too long ({dur / 60:.1f} min, max {MAX_SECONDS / 60:.0f} min)", "imp.err_long",
                           dur=f"{dur / 60:.1f}", max=f"{MAX_SECONDS / 60:.0f}")
    if not np.isfinite(samples).all() or float(np.abs(samples).max()) < 1e-4:
        raise ImportFailed("audio is silent", "imp.err_silent")
    stream = "song" + ext
    try:
        res = _chart_audio(samples, sr, meta, stream, progress)
    except ImportFailed:
        raise
    except Exception as exc:
        raise ImportFailed(f"auto-charting failed: {exc}", "imp.err_chart", err=str(exc)) from exc
    _progress(progress, 0.92, "Writing song files")
    os.makedirs(songs_root, exist_ok=True)
    name = sanitize_name(f"{meta.artist} - {meta.title}" if meta.artist else meta.title)
    folder = unique_folder(songs_root, name)
    try:
        os.makedirs(folder)
        shutil.copyfile(path, os.path.join(folder, stream))
        with open(os.path.join(folder, "notes.chart"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(res.text)
        write_song_ini(os.path.join(folder, "song.ini"), meta, length_ms=int(round(dur * 1000)),
                       preview_ms=res.preview_ms, diff=res.difficulty, source=os.path.basename(path))
        _progress(progress, 0.96, "Drawing album art")
        write_cover(folder, meta)
    except Exception as exc:
        shutil.rmtree(folder, ignore_errors=True)
        raise ImportFailed(f"cannot write song folder: {exc}", "imp.err_write", err=str(exc)) from exc
    _progress(progress, 1.0, "Done")
    return folder


def find_song_audio(folder: str) -> str:
    from .chart.loader import find_stems
    stems = find_stems(folder)
    return stems.get("song") or stems.get("guitar") or next(iter(stems.values()), "")


def rechart_song(folder: str, progress=None) -> str:
    """Klasordeki ses dosyasindan notes.chart'i yeniden uret (eski dosya .bak olarak saklanir)."""
    from .chart.song_ini import read_song_ini
    audio = find_song_audio(folder)
    if not audio:
        raise ImportFailed("no audio file in this song folder", "imp.err_no_audio")
    ini_path = os.path.join(folder, "song.ini")
    ini = read_song_ini(ini_path) if os.path.exists(ini_path) else {}
    meta = AudioMeta(title=ini.get("name", "") or os.path.basename(folder), artist=ini.get("artist", ""),
                     album=ini.get("album", ""), year=ini.get("year", ""), genre=ini.get("genre", ""))
    _progress(progress, 0.04, "Decoding audio")
    samples, sr = decode_audio(audio)
    try:
        res = _chart_audio(samples, sr, meta, os.path.basename(audio), progress)
    except Exception as exc:
        raise ImportFailed(f"auto-charting failed: {exc}", "imp.err_chart", err=str(exc)) from exc
    _progress(progress, 0.94, "Writing chart")
    chart_path = os.path.join(folder, "notes.chart")
    tmp = chart_path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(res.text)
        if os.path.exists(chart_path):
            shutil.copyfile(chart_path, chart_path + ".bak")
        os.replace(tmp, chart_path)
        _update_ini(ini_path, {"diff_guitar": str(res.difficulty), "preview_start_time": str(res.preview_ms),
                               "song_length": str(int(round(samples.size / sr * 1000))), "auto_chart": "1",
                               "charter": "RIFF Auto", "auto_chart_version": str(AUTO_CHART_VERSION)})
    except Exception as exc:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise ImportFailed(f"cannot write chart: {exc}", "imp.err_write", err=str(exc)) from exc
    _progress(progress, 1.0, "Done")
    return folder


def import_song_folder(path: str, songs_root: str, progress=None) -> str:
    """Hazir Clone Hero klasorunu (notes.chart / notes.mid) Songs altina kopyala."""
    if not is_song_folder(path):
        raise ImportFailed("not a song folder (no notes.chart / notes.mid)", "imp.err_not_song")
    src = os.path.normcase(os.path.abspath(path))
    root = os.path.normcase(os.path.abspath(songs_root))
    if src.startswith(root + os.sep) or src == root:
        raise ImportFailed("this song is already in the Songs folder", "imp.err_already")
    _progress(progress, 0.2, "Copying song folder")
    dest = unique_folder(songs_root, sanitize_name(os.path.basename(os.path.normpath(path))))
    try:
        shutil.copytree(path, dest)
    except Exception as exc:
        shutil.rmtree(dest, ignore_errors=True)
        raise ImportFailed(f"cannot copy folder: {exc}", "imp.err_write", err=str(exc)) from exc
    _progress(progress, 1.0, "Done")
    return dest
