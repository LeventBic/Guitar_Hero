"""On yuz duman testleri: headless (dummy SDL) bot ile her demo sarkiyi en kolay ve en zor zorlukta bastan sona
oynatir (simule saat, her frame cizilir) -> full combo ve cokme yok. Ayrica ayar dosyasi ve girdi eslemesi."""
from __future__ import annotations

import json
import os

import pytest

pygame = pytest.importorskip("pygame")

from gh import headless  # noqa: E402
from gh.config import DIFFICULTIES  # noqa: E402
from gh.library import available_difficulties, song_roots  # noqa: E402


def _song_folders() -> list[str]:
    from gh.chart import scan_songs
    seen, out = set(), []
    for root in song_roots():
        for info in scan_songs(root):
            key = os.path.normcase(os.path.realpath(info.folder))
            if key not in seen:
                seen.add(key)
                out.append(info.folder)
    return out


SONGS = _song_folders()


@pytest.fixture(scope="module")
def app():
    a = headless.make_app()
    a.library.scan()
    yield a


def _cases():
    cases = []
    for folder in SONGS:
        for which in ("easiest", "hardest"):
            cases.append(pytest.param(folder, which, id=f"{os.path.basename(folder)}-{which}"))
    return cases


@pytest.mark.skipif(not SONGS, reason="Songs/ bos")
@pytest.mark.parametrize("folder,which", _cases())
def test_smoke_full_combo(app, folder, which):
    info = app.library.find(folder)
    assert info is not None
    diffs = available_difficulties(app.library.chart(info.folder))
    assert diffs, "sarkida oynanabilir zorluk yok"
    diff = diffs[0] if which == "easiest" else diffs[-1]
    r = headless.run_smoke(app, info, diff, fps=15)
    assert r["ok"], r
    assert r["total"] > 0 and r["stars"] >= 5.0


def test_settings_roundtrip_and_tolerance(tmp_path):
    from gh.settings_store import load_settings, save_settings
    p = tmp_path / "settings.json"
    s = load_settings(str(p))                      # dosya yok -> varsayilan
    s.video.note_speed = 1.7
    s.audio.audio_offset_ms = 42
    s.engine.no_fail = False
    s.keys.frets = (("q",), ("w",), ("e",), ("r",), ("t",))
    assert save_settings(s, str(p))
    s2 = load_settings(str(p))
    assert s2.video.note_speed == pytest.approx(1.7)
    assert s2.audio.audio_offset_ms == 42
    assert s2.engine.no_fail is False
    assert s2.keys.frets[2] == ("e",)
    # eski / bozuk anahtarlar: bilinmeyenler ve yanlis tipler yok sayilir
    p.write_text(json.dumps({"video": {"note_speed": "fast", "bogus": 1, "highway_length": 9},
                             "audio": {"audio_offset_ms": 12.6}, "keys": {"frets": [["a"]]}, "extra": 5}))
    s3 = load_settings(str(p))
    assert s3.video.note_speed == 1.0
    assert s3.video.highway_length == 1.5          # sinirlandi
    assert s3.audio.audio_offset_ms == 13
    assert len(s3.keys.frets) == 5
    p.write_text("{not json")
    assert load_settings(str(p)).video.note_speed == 1.0


def _press(app, key, frames=2):
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=key, mod=0, unicode="", scancode=0))
    pygame.event.post(pygame.event.Event(pygame.KEYUP, key=key, mod=0, unicode="", scancode=0))
    app.poll()
    for _ in range(frames):
        app.frame(1 / 60)


@pytest.mark.skipif(not SONGS, reason="Songs/ bos")
def test_menu_navigation_keyboard_only(app):
    """Ana menu -> sarki listesi -> zorluk -> oyun -> duraklat -> sarki listesine don -> ayarlar."""
    from gh.scenes import (DifficultyScene, GameplayScene, PauseScene, SettingsScene, SongListScene,
                           TitleScene)
    pygame.event.clear()
    app.running = True
    app.stack = []
    app.push(TitleScene(app))
    _press(app, pygame.K_RETURN)
    assert isinstance(app.top, SongListScene)
    _press(app, pygame.K_DOWN)
    _press(app, pygame.K_RETURN)
    assert isinstance(app.top, DifficultyScene)
    _press(app, pygame.K_RETURN, frames=30)
    assert isinstance(app.top, GameplayScene)
    _press(app, pygame.K_ESCAPE)
    assert isinstance(app.top, PauseScene)
    _press(app, pygame.K_DOWN)
    _press(app, pygame.K_DOWN)
    _press(app, pygame.K_RETURN)
    assert isinstance(app.top, SongListScene)
    _press(app, pygame.K_ESCAPE)
    assert isinstance(app.top, TitleScene)
    _press(app, pygame.K_DOWN)
    _press(app, pygame.K_DOWN)
    _press(app, pygame.K_RETURN)
    assert isinstance(app.top, SettingsScene)
    _press(app, pygame.K_ESCAPE)
    assert isinstance(app.top, TitleScene)
    app.stack = []


def test_keyboard_mapping(app):
    from gh.engine import InputKind
    from gh.input import InputManager
    im = InputManager(app.settings)
    prev, now = im.begin_poll()
    im.process(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a, mod=0), now)
    im.process(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN, mod=0), now)
    im.process(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SEMICOLON, mod=0), now)
    kinds = [(g.kind, g.fret) for g in im.game]
    assert (InputKind.FRET_DOWN, 0) in kinds
    assert (InputKind.STRUM, -1) in kinds
    assert any(g.kind == InputKind.WHAMMY and g.value == 1.0 for g in im.game)
    assert "CONFIRM" in im.menu and "DOWN" in im.menu
    # whammy basili kalinca salinim uretir
    im.game.clear()
    im.update(now + 0.25)
    assert any(g.kind == InputKind.WHAMMY for g in im.game)
    im.process(pygame.event.Event(pygame.KEYUP, key=pygame.K_SEMICOLON, mod=0), now + 0.3)
    assert im.game[-1].kind == InputKind.WHAMMY and im.game[-1].value == 0.0
