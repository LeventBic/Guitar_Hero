"""Arka plan videosu (PyAV / FFmpeg): ayri is parcaciginda cozme + olcekleme, ana is parcaciginda Surface.

- Sarkinin kendi videosu (Clone Hero: klasorde video.mp4 / .webm / ...): sarki saatine kilitli oynar;
  song.ini `video_start_time` (ms) = sarkinin 0. saniyesinde videonun neresinde olunacagi.
- Yoksa assets/videos/ altindaki hazir gitarist kliplerinden biri (sarki adina gore sabit secim) donguyle oynar.
- PyAV yoksa / dosya acilamazsa None doner, sahne eski (cizili) arka plana duser.

Zaman modeli: cozucu monoton zaman uretir (dongude: pts + tur * sure), ana is parcacigi frame(t) ile t'ye kadar
gelmis en son kareyi alir; t kareden cok uzaklasirsa (atlama / yeniden baslatma) arama (seek) istenir.
"""
from __future__ import annotations

import glob
import hashlib
import os
import threading
from collections import deque
from fractions import Fraction

VIDEO_EXTS = (".mp4", ".webm", ".mkv", ".avi", ".mov", ".m4v", ".ogv", ".mpeg", ".mpg", ".vp8")
VIDEO_NAMES = ("video", "background", "bg")
QUEUE = 6
SEEK_BEHIND_S = 0.6          # gosterilen kare istenenden bu kadar geride kalirsa ara
EPS = 1e-3                   # kare zamani karsilastirma toleransi
SEEK_AHEAD_S = 0.5           # kuyruktaki ilk kare istenenden bu kadar ileride ise ara (geri sarma)


def available() -> bool:
    try:
        import av  # noqa: F401
        return True
    except Exception:
        return False


def find_song_video(folder: str) -> str:
    if not folder or not os.path.isdir(folder):
        return ""
    try:
        files = {f.lower(): os.path.join(folder, f) for f in os.listdir(folder)}
    except OSError:
        return ""
    for name in VIDEO_NAMES:
        for ext in VIDEO_EXTS:
            p = files.get(name + ext)
            if p:
                return p
    return ""


def stock_clips() -> list[str]:
    from .config import resource_root
    return sorted(glob.glob(os.path.join(resource_root(), "assets", "videos", "*.mp4")))


def pick_stock(key: str) -> str:
    clips = stock_clips()
    if not clips:
        return ""
    h = int(hashlib.md5((key or "").encode("utf-8")).hexdigest(), 16)
    return clips[h % len(clips)]


class VideoPlayer:
    """Tek video; frame(t) -> pygame.Surface | None. close() ile is parcacigi durur."""

    def __init__(self, path: str, size: tuple[int, int], *, loop: bool, start_offset: float = 0.0):
        import av
        self.path = path
        self.size = (int(size[0]) // 2 * 2, int(size[1]) // 2 * 2)
        self.loop = loop
        self.start_offset = float(start_offset)
        self.container = av.open(path)
        self.stream = self.container.streams.video[0]
        self.stream.thread_type = "AUTO"
        dur = None
        if self.stream.duration and self.stream.time_base:
            dur = float(self.stream.duration * self.stream.time_base)
        elif self.container.duration:
            dur = self.container.duration / 1_000_000
        self.duration = dur if dur and dur > 0.2 else None
        self._q: deque = deque()
        self._cv = threading.Condition()
        self._seek_to: float | None = 0.0
        self._stop = False
        self._cur = None               # (t, surface)
        self._arr = None               # gosterilen karenin tamponu (frombuffer referansi)
        self.error = ""
        self._th = threading.Thread(target=self._run, name="video-decode", daemon=True)
        self._th.start()

    # ------------------------------------------------------------ cozucu is parcacigi
    def _run(self) -> None:
        tb = self.stream.time_base or Fraction(1, 30)          # kesir: 2.4 s tam 2.4 kalsin
        looping = bool(self.loop and self.duration)
        lap = 0
        it = None
        skip_before = None
        try:
            while not self._stop:
                with self._cv:
                    target, self._seek_to = self._seek_to, None
                if target is not None:
                    lap = int(target // self.duration) if looping else 0
                    local = target - lap * self.duration if looping else target
                    self.container.seek(max(0, int(local / float(tb))), stream=self.stream, backward=True)
                    it = self.container.decode(self.stream)
                    skip_before = local - 0.02
                    with self._cv:
                        self._q.clear()
                try:
                    frame = next(it)
                except StopIteration:
                    if looping:                            # dongu: basa sar, monoton zaman bir tur ileri
                        lap += 1
                        self.container.seek(0, stream=self.stream)
                        it = self.container.decode(self.stream)
                        skip_before = None
                        continue
                    with self._cv:                         # sarki videosu bitti: son kare kalir
                        while not self._stop and self._seek_to is None:
                            self._cv.wait(0.1)
                    continue
                t = float(frame.pts * tb) if frame.pts is not None else 0.0
                if skip_before is not None and t < skip_before:
                    continue                               # aramadan sonra hedefe kadar olan kareler
                skip_before = None
                arr = frame.to_ndarray(format="rgb24", width=self.size[0], height=self.size[1])
                mono = t + lap * self.duration if looping else t
                with self._cv:
                    while len(self._q) >= QUEUE and not self._stop and self._seek_to is None:
                        self._cv.wait(0.05)
                    if self._seek_to is None and not self._stop:
                        self._q.append((mono, arr))
        except Exception as exc:  # bozuk dosya / codec: arka plan cizime duser
            self.error = str(exc)

    # ------------------------------------------------------------ ana is parcacigi
    def _request_seek(self, t: float) -> None:
        with self._cv:
            self._seek_to = max(0.0, t)
            self._q.clear()
            self._cv.notify_all()

    def frame(self, song_t: float):
        """Sarki zamani song_t icin gosterilecek kare (Surface) ya da None (video henuz baslamadi / yok)."""
        import pygame
        if self.error:
            return None
        t = song_t + self.start_offset
        if t < 0:
            return None
        newest = None
        with self._cv:
            while self._q and self._q[0][0] <= t + EPS:
                newest = self._q.popleft()
            first = self._q[0][0] if self._q else None
            pending = self._seek_to is not None
            self._cv.notify_all()
        if newest is not None:
            self._arr = newest[1]                          # frombuffer tamponu canli kalsin
            self._cur = (newest[0], pygame.image.frombuffer(self._arr, self.size, "RGB"))
        if not pending:
            shown = self._cur[0] if self._cur else None
            behind = first is None and shown is not None and t - shown > SEEK_BEHIND_S
            rewound = first is not None and first > t + SEEK_AHEAD_S and (shown is None or shown > t)
            if behind or rewound:                          # ileri / geri atlama (yeniden baslatma, seek)
                if not (not self.loop and self.duration and t > self.duration):
                    self._request_seek(t)
        return self._cur[1] if self._cur else None

    def close(self) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify_all()
        self._th.join(timeout=1.0)
        try:
            self.container.close()
        except Exception:
            pass


def open_background(folder: str, key: str, size: tuple[int, int], start_offset_ms: int = 0,
                    allow_stock: bool = True) -> VideoPlayer | None:
    """Sarki videosu varsa onu (sarkiya kilitli), yoksa hazir klip (dongu). Acilamazsa None."""
    if not available():
        return None
    song_video = find_song_video(folder)
    for path, loop, off in ((song_video, False, start_offset_ms / 1000.0),
                            (pick_stock(key) if allow_stock else "", True, 0.0)):
        if not path:
            continue
        try:
            return VideoPlayer(path, size, loop=loop, start_offset=off)
        except Exception:
            continue
    return None


__all__ = ["VideoPlayer", "open_background", "find_song_video", "stock_clips", "pick_stock", "available"]
