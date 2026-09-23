"""Sarki kutuphanesi: user_root()/Songs ve resource_root()/Songs taranir, tekrarlar ayiklanir, chart'lar
istek uzerine yuklenip onbelleklenir."""
from __future__ import annotations

import os

from .chart import load_song, scan_songs
from .config import DIFFICULTIES, resource_root, user_root
from .models import Chart, SongInfo


def song_roots() -> list[str]:
    roots = []
    for r in (os.path.join(user_root(), "Songs"), os.path.join(resource_root(), "Songs")):
        key = os.path.normcase(os.path.realpath(r))
        if key not in [os.path.normcase(os.path.realpath(x)) for x in roots]:
            roots.append(r)
    return roots


def setlist_of(root: str, folder: str) -> str:
    """Sarki klasorunun Songs kokune gore ilk alt klasoru (setlist / oyun adi); dogrudan kokteyse ""."""
    try:
        rel = os.path.relpath(os.path.dirname(os.path.abspath(folder)), os.path.abspath(root))
    except ValueError:
        return ""
    if rel in (".", "") or rel.startswith(".."):
        return ""
    return rel.replace("\\", "/").split("/")[0]


class SongLibrary:
    def __init__(self):
        self.songs: list[SongInfo] = []
        self.errors: list[tuple[str, str]] = []
        self._charts: dict[str, Chart] = {}
        self._chart_errors: dict[str, str] = {}

    def scan(self) -> list[SongInfo]:
        seen = set()
        out: list[SongInfo] = []
        self.errors = []
        for root in song_roots():
            for info in scan_songs(root, self.errors):
                key = os.path.normcase(os.path.realpath(info.folder))
                if key in seen:
                    continue
                seen.add(key)
                info.setlist = setlist_of(root, info.folder)
                out.append(info)
        # setlist'lere gore (kokteki sarkilar = "Sarkilarim" once), setlist icinde ada gore
        out.sort(key=lambda i: (i.setlist != "", i.setlist.lower(), i.name.lower(), i.artist.lower()))
        self.songs = out
        return out

    def chart(self, folder: str) -> Chart | None:
        key = os.path.normcase(os.path.realpath(folder))
        c = self._charts.get(key)
        if c is None and key not in self._chart_errors:
            try:
                c = load_song(folder)
                self._charts[key] = c
            except Exception as exc:
                self._chart_errors[key] = f"{type(exc).__name__}: {exc}"
        return c

    def invalidate(self, folder: str) -> None:
        """Onbellekteki chart'i unut (yeniden chart'lama / ice aktarma sonrasi)."""
        key = os.path.normcase(os.path.realpath(folder))
        self._charts.pop(key, None)
        self._chart_errors.pop(key, None)

    def chart_error(self, folder: str) -> str:
        return self._chart_errors.get(os.path.normcase(os.path.realpath(folder)), "")

    def find(self, query: str) -> SongInfo | None:
        """Klasor yolu, klasor adi veya sarki adi ile ara."""
        if not self.songs:
            self.scan()
        if query and os.path.isdir(query):
            key = os.path.normcase(os.path.realpath(query))
            for s in self.songs:
                if os.path.normcase(os.path.realpath(s.folder)) == key:
                    return s
            # kutuphanede olmayan klasor: dogrudan yukle
            try:
                c = load_song(query)
                self._charts[key] = c
                return c.info
            except Exception:
                return None
        q = (query or "").lower()
        for s in self.songs:
            if q in (os.path.basename(s.folder).lower(), s.name.lower()):
                return s
        for s in self.songs:
            if q and (q in os.path.basename(s.folder).lower() or q in s.name.lower()):
                return s
        return None


def available_difficulties(chart: Chart | None) -> list[str]:
    if chart is None:
        return []
    return [d for d in DIFFICULTIES if d in chart.tracks and chart.tracks[d].notes]


def fmt_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"
