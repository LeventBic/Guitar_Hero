"""Arka plan videosu: karelerin sarki zamanina kilitlenmesi, dongu, ileri / geri atlama, klasor videosu."""
from __future__ import annotations

import os
import time

import numpy as np
import pytest

av = pytest.importorskip("av")
pygame = pytest.importorskip("pygame")

FPS = 10
SECONDS = 3


def make_video(path: str) -> None:
    """Kare k: kirmizi = 8*k (0..232), yesil = 0 -> renkten kare numarasi okunur."""
    out = av.open(path, "w")
    st = out.add_stream("mpeg4", rate=FPS)
    st.width, st.height, st.pix_fmt = 64, 48, "yuv420p"
    st.bit_rate = 2_000_000
    for k in range(FPS * SECONDS):
        img = np.zeros((48, 64, 3), np.uint8)
        img[..., 0] = 8 * k
        for pkt in st.encode(av.VideoFrame.from_ndarray(img, format="rgb24")):
            out.mux(pkt)
    for pkt in st.encode():
        out.mux(pkt)
    out.close()


def frame_index(player, t: float, wait: float = 3.0) -> int:
    """t anindaki kare: gosterilen karenin zamani, t'den onceki son kare zamanina esit olana kadar bekle."""
    want = int((t + player.start_offset) * FPS + 1e-6) / FPS
    if player.loop:
        want = want % SECONDS + (t + player.start_offset) // SECONDS * SECONDS
    end = time.time() + wait
    surf = None
    while time.time() < end:
        surf = player.frame(t)
        if surf is not None and abs(player._cur[0] - want) < 1e-3:
            break
        time.sleep(0.01)
    assert surf is not None and abs(player._cur[0] - want) < 1e-3, (player._cur and player._cur[0], want)
    return round(surf.get_at((32, 24))[0] / 7.7)


@pytest.fixture()
def video(tmp_path):
    p = str(tmp_path / "video.mp4")
    make_video(p)
    return p


def test_player_follows_song_time_and_seeks(video):
    from gh.video import VideoPlayer
    pl = VideoPlayer(video, (64, 48), loop=False)
    try:
        assert pl.frame(-1.0) is None                        # video baslamadan once cizim yok
        assert abs(frame_index(pl, 0.5) - 5) <= 1
        assert abs(frame_index(pl, 1.0) - 10) <= 1
        assert abs(frame_index(pl, 2.4) - 24) <= 1           # ileri atlama
        assert abs(frame_index(pl, 0.3) - 3) <= 1            # geri atlama (yeniden baslatma)
    finally:
        pl.close()


def test_loop_and_start_offset(video):
    from gh.video import VideoPlayer
    pl = VideoPlayer(video, (64, 48), loop=True)
    try:
        assert abs(frame_index(pl, 0.5) - 5) <= 1
        assert abs(frame_index(pl, 3.5) - 5) <= 1            # 3 s'lik klip: 3.5 s = 2. tur 0.5 s
        assert abs(frame_index(pl, 7.2) - 12) <= 1
    finally:
        pl.close()
    off = VideoPlayer(video, (64, 48), loop=False, start_offset=1.0)
    try:
        assert abs(frame_index(off, 0.5) - 15) <= 1          # video_start_time = 1000 ms
    finally:
        off.close()


def test_open_background_prefers_song_video(video, tmp_path, monkeypatch):
    from gh import video as V
    folder = os.path.dirname(video)
    assert V.find_song_video(folder) == video
    monkeypatch.setattr(V, "stock_clips", lambda: [video])
    pl = V.open_background(folder, "x", (64, 48))
    assert pl is not None and not pl.loop
    pl.close()
    empty = tmp_path / "Other Song"
    empty.mkdir()
    st = V.open_background(str(empty), "Other Song", (64, 48))
    assert st is not None and st.loop                        # klasor videosu yok: hazir klip, dongu
    st.close()
    assert V.open_background(str(empty), "x", (64, 48), allow_stock=False) is None


def test_song_video_follows_audio_not_chart_time(tmp_path, monkeypatch):
    """song.ini delay (chart.offset) chart'i sese gore kaydirir; sarki videosu ses konumunu izlemeli."""
    from types import SimpleNamespace as NS

    from gh.scenes.gameplay import GameplayScene
    fake = NS(visual_time=10.0, lead_in=2.7, chart=NS(offset=3.649), video=NS(loop=False))
    assert abs(GameplayScene.video_time(fake) - 13.649) < 1e-9
    fake.video.loop = True
    assert abs(GameplayScene.video_time(fake) - 12.7) < 1e-9
