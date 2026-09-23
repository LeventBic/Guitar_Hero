"""Hazir setlist'ler (assets/setlists.json) ve arka planda sirali indirici (pygame IMPORT ETMEZ).

setlists.json yalniz meta veridir (oyun adi, yil, klasor; sarki basina md5 / sanatci / ad / sure / boyut). Sarkilar
oyuncunun istegiyle Chorus Encore'dan (gh.chorus) oyuncunun kendi Songs\\<setlist klasoru> altina iner.
Downloader: tek is parcacigi, sarkilar arasinda kisa bekleme (servisi yormamak icin), sarki basina 3 deneme,
iptal (yarim klasor kalmaz), kaldigi yerden devam (kurulu md5'ler atlanir).
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field


@dataclass
class SetlistSong:
    md5: str
    artist: str
    name: str
    length_ms: int = 0
    size: int = 0


@dataclass
class Setlist:
    id: str
    name: str
    year: int
    folder: str
    songs: list[SetlistSong] = field(default_factory=list)

    @property
    def size(self) -> int:
        return sum(s.size for s in self.songs)


def setlists_path() -> str:
    from .config import resource_root
    return os.path.join(resource_root(), "assets", "setlists.json")


_CACHE: dict[str, list[Setlist]] = {}


def load_setlists(path: str | None = None) -> list[Setlist]:
    path = path or setlists_path()
    if path in _CACHE:
        return _CACHE[path]
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    out = []
    for s in data.get("setlists", []):
        songs = [SetlistSong(x["md5"], x.get("artist", ""), x.get("name", ""), int(x.get("length_ms", 0)),
                             int(x.get("size", 0))) for x in s.get("songs", [])]
        out.append(Setlist(s["id"], s["name"], int(s.get("year", 0)), s.get("folder") or s["name"], songs))
    out.sort(key=lambda s: (s.year, s.name))
    _CACHE[path] = out
    return out


def setlist_years() -> dict[str, int]:
    """Klasor adi (kucuk harf) -> cikis yili: sarki listesinde setlist'leri kronolojik siralamak icin."""
    return {s.folder.lower(): s.year for s in load_setlists()}


def fmt_size(n: float) -> str:
    if n >= 1e9:
        return f"{n / 1e9:.1f} GB"
    if n >= 1e6:
        return f"{n / 1e6:.0f} MB"
    return f"{max(0.0, n) / 1e3:.0f} KB"


@dataclass
class Job:
    setlist: Setlist
    song: SetlistSong


class Downloader:
    """jobs sirayla indirilir; durum alanlari ana is parcaciginda okunur (yalniz okuma, kilit gerekmez)."""

    def __init__(self, jobs: list[Job], songs_root: str, *, pause_s: float = 0.6, retries: int = 3,
                 download_fn=None):
        from . import chorus
        self.jobs = jobs
        self.root = songs_root
        self.pause_s = pause_s
        self.retries = retries
        self._download = download_fn or chorus.download
        self.cancel_event = threading.Event()
        self.total_bytes = sum(j.song.size for j in jobs)
        self.done_bytes = 0            # tamamlanan sarkilarin boyutu
        self.cur_bytes = 0             # su anki sarkinin indirilen kismi
        self.cur_total = 0
        self.index = 0                 # su anki is (0 tabanli)
        self.ok = 0
        self.failed: list[tuple[Job, str]] = []
        self.current: Job | None = None
        self.started = 0.0
        self.finished = False
        self.cancelled = False
        self._th: threading.Thread | None = None

    # ------------------------------------------------------------ kontrol
    def start(self) -> None:
        self.started = time.perf_counter()
        self._th = threading.Thread(target=self._run, name="setlist-download", daemon=True)
        self._th.start()

    def cancel(self) -> None:
        self.cancel_event.set()

    def join(self, timeout: float | None = None) -> None:
        if self._th is not None:
            self._th.join(timeout)

    # ------------------------------------------------------------ durum
    @property
    def bytes_now(self) -> int:
        return self.done_bytes + self.cur_bytes

    def speed(self) -> float:
        el = time.perf_counter() - self.started if self.started else 0.0
        return self.bytes_now / el if el > 0.5 else 0.0

    def eta(self) -> float:
        sp = self.speed()
        return (self.total_bytes - self.bytes_now) / sp if sp > 0 else 0.0

    # ------------------------------------------------------------ is parcacigi
    def _progress(self, got: int, total: int) -> None:
        self.cur_bytes = got
        self.cur_total = total

    def _run(self) -> None:
        from .chorus import Cancelled
        try:
            for i, job in enumerate(self.jobs):
                if self.cancel_event.is_set():
                    break
                self.index, self.current = i, job
                self.cur_bytes, self.cur_total = 0, job.song.size
                dest_root = os.path.join(self.root, job.setlist.folder)
                err = ""
                for attempt in range(self.retries):
                    try:
                        self._download(job.song.md5, dest_root, (job.song.artist, job.song.name), no_video=True,
                                       progress=self._progress, cancel=self.cancel_event)
                        err = ""
                        break
                    except Cancelled:
                        err = "cancelled"
                        break
                    except Exception as exc:  # ag / sunucu hatasi: bekle, tekrar dene
                        err = f"{type(exc).__name__}: {exc}"
                        if self.cancel_event.wait(1.5 * (attempt + 1)):
                            break
                if err == "cancelled" or self.cancel_event.is_set():
                    break
                if err:
                    self.failed.append((job, err))
                else:
                    self.ok += 1
                self.done_bytes += job.song.size
                self.cur_bytes = 0
                if i + 1 < len(self.jobs) and self.cancel_event.wait(self.pause_s):
                    break
        finally:
            self.cancelled = self.cancel_event.is_set()
            self.current = None
            self.finished = True


def pending_jobs(setlists: list[Setlist], installed: set[str]) -> list[Job]:
    return [Job(s, x) for s in setlists for x in s.songs if x.md5 not in installed]


__all__ = ["Setlist", "SetlistSong", "Job", "Downloader", "load_setlists", "pending_jobs", "fmt_size",
           "setlist_years", "setlists_path"]
