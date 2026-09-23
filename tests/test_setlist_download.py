"""Setlist indirici: assets/setlists.json, Downloader (yeniden deneme / iptal / devam), chorus.download (gecici
klasor + tek adimda kurulum, iptalde artik yok) ve setlist ekrani."""
from __future__ import annotations

import io
import os
import re
import threading

import pytest

from test_sng import CHART, make_sng


def test_setlists_json_is_metadata_only_and_sorted():
    from gh.setlists import load_setlists
    lists = load_setlists()
    assert len(lists) == 16 and sum(len(s.songs) for s in lists) == 875
    assert [s.year for s in lists] == sorted(s.year for s in lists)
    assert lists[0].name == "Guitar Hero" and lists[-1].name == "Guitar Hero Live"
    for s in lists:
        assert s.folder and s.songs
        for x in s.songs:
            assert re.fullmatch(r"[0-9a-f]{32}", x.md5) and x.name and x.size > 0
    assert os.path.getsize(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                        "assets", "setlists.json")) < 300_000     # yalniz meta veri


def _jobs(n=3):
    from gh.setlists import Job, Setlist, SetlistSong
    sl = Setlist("x", "Test Set", 2005, "Test Set", [SetlistSong(f"{i:032x}", "A", f"S{i}", 1000, 100) for i in range(n)])
    return [Job(sl, s) for s in sl.songs]


def test_downloader_success_retry_and_failure(tmp_path):
    from gh.setlists import Downloader
    calls: dict[str, int] = {}

    def fake(md5, dest_root, hint, no_video, progress, cancel):
        calls[md5] = calls.get(md5, 0) + 1
        progress(50, 100)
        if md5.endswith("1") and calls[md5] < 2:
            raise OSError("temporary")                  # ilk denemede hata, ikincide olur
        if md5.endswith("2"):
            raise OSError("always")                     # hep hata
        os.makedirs(os.path.join(dest_root, md5), exist_ok=True)
        return os.path.join(dest_root, md5)

    d = Downloader(_jobs(3), str(tmp_path), pause_s=0.0, retries=3, download_fn=fake)
    d.cancel_event.wait = lambda t=None: False          # yeniden deneme beklemesi yok
    d._run()
    assert d.finished and not d.cancelled
    assert d.ok == 2 and len(d.failed) == 1 and calls[f"{2:032x}"] == 3
    assert d.bytes_now == d.total_bytes == 300
    assert sorted(os.listdir(tmp_path / "Test Set")) == [f"{0:032x}", f"{1:032x}"]


def test_downloader_cancel_stops_quickly(tmp_path):
    from gh.chorus import Cancelled
    from gh.setlists import Downloader
    started = threading.Event()

    def slow(md5, dest_root, hint, no_video, progress, cancel):
        started.set()
        cancel.wait(5)
        raise Cancelled()

    d = Downloader(_jobs(3), str(tmp_path), pause_s=0.0, download_fn=slow)
    d.start()
    assert started.wait(2)
    d.cancel()
    d.join(2)
    assert d.finished and d.cancelled and d.ok == 0 and not d.failed


class _Resp(io.BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def test_chorus_download_installs_atomically_and_cancel_leaves_nothing(tmp_path, monkeypatch):
    from gh import chorus
    pkg = make_sng({"name": "Song X", "artist": "Band"}, {"notes.chart": CHART.encode(), "song.ogg": b"\0" * 5000})
    urls = []

    def fake_urlopen(req, timeout=0):
        urls.append(req.full_url)
        return _Resp(pkg)

    monkeypatch.setattr(chorus.urllib.request, "urlopen", fake_urlopen)
    md5 = "a" * 32
    seen = []
    dest = chorus.download(md5, str(tmp_path / "Set"), no_video=True, progress=lambda g, t: seen.append((g, t)))
    assert urls[0].endswith(f"/{md5}_novideo.sng")
    assert os.path.basename(dest) == "Band - Song X"
    assert f"chorus_md5 = {md5}" in open(os.path.join(dest, "song.ini"), encoding="utf-8").read()
    assert seen and seen[-1][0] == seen[-1][1] == len(pkg)
    assert os.listdir(tmp_path / "Set") == ["Band - Song X"]              # gecici .part klasoru yok
    assert chorus.installed_md5s(str(tmp_path)) == {md5}
    # iptal: indirme sirasinda iptal -> hicbir klasor / gecici dosya kalmaz
    ev = threading.Event()
    ev.set()
    with pytest.raises(chorus.Cancelled):
        chorus.download("b" * 32, str(tmp_path / "Set"), cancel=ev)
    assert os.listdir(tmp_path / "Set") == ["Band - Song X"]


def test_setlist_scene_draws_and_counts(tmp_path, monkeypatch):
    pygame = pytest.importorskip("pygame")
    from gh import headless, importer
    from gh.scenes.setlists import SetlistScene
    monkeypatch.setattr(importer, "songs_dir", lambda: str(tmp_path))
    app = headless.make_app()
    sc = SetlistScene(app)
    app.stack = [sc]
    have, tot, rem = sc._counts(sc.setlists)
    assert have == 0 and tot == 875 and rem > 5e9
    sc.on_menu("DOWN")
    assert sc.rows()[sc.index].name == "Guitar Hero"
    for _ in range(3):
        sc.update(1 / 60)
    sc.draw(app.screen)
    assert isinstance(app.screen, pygame.Surface)
    app.stack = []
