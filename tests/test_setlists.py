"""Sarki listesi setlist'leri: Songs altindaki klasorlere gore gruplama, siralama ve sol / sag atlama."""
from __future__ import annotations

import os
from types import SimpleNamespace as NS

from gh.library import setlist_of


def test_setlist_of(tmp_path):
    root = str(tmp_path)
    assert setlist_of(root, os.path.join(root, "Guitar Hero III", "Slayer - Raining Blood")) == "Guitar Hero III"
    assert setlist_of(root, os.path.join(root, "Pack", "Sub", "Song")) == "Pack"
    assert setlist_of(root, os.path.join(root, "My Song")) == ""


def test_scan_sorts_by_setlist(tmp_path, monkeypatch):
    from gh import library
    for rel, name in (("B Game/x - Zed", "Zed"), ("A Game/y - Alpha", "Alpha"), ("mine", "Mine"), ("B Game/z - Beta", "Beta")):
        d = tmp_path / rel
        d.mkdir(parents=True)
        (d / "notes.chart").write_text("[Song]\n{\n  Resolution = 192\n}\n[SyncTrack]\n{\n  0 = B 120000\n}\n"
                                       "[ExpertSingle]\n{\n  768 = N 0 0\n}\n", encoding="utf-8")
        (d / "song.ini").write_text(f"[song]\nname = {name}\nartist = A\n", encoding="utf-8")
    monkeypatch.setattr(library, "song_roots", lambda: [str(tmp_path)])
    songs = library.SongLibrary().scan()
    assert [(s.setlist, s.name) for s in songs] == [("", "Mine"), ("A Game", "Alpha"), ("B Game", "Beta"),
                                                    ("B Game", "Zed")]


def test_setlist_jump():
    from gh.scenes.songlist import SongListScene
    songs = [NS(setlist=g) for g in ("", "", "A", "A", "A", "B", "B")]
    sc = NS(songs=songs, index=0)
    jump = lambda d: SongListScene._setlist_jump(sc, d)        # noqa: E731
    sc._setlist_start = lambda i: SongListScene._setlist_start(sc, i)
    assert jump(1) == 2                      # sonraki setlist'in basi
    sc.index = 3
    assert jump(1) == 5 and jump(-1) == 2    # ortadan: sola once kendi basina
    sc.index = 2
    assert jump(-1) == 0                     # bastan: onceki setlist'in basi
    sc.index = 6
    assert jump(1) == 0                      # sondan basa sarar
    sc.index = 0
    assert jump(-1) == 5                     # bastan sona sarar: son setlist'in basi
