"""Ayarlar: tus atama (cokme regresyonu: t("set.bound", key=...) -> TypeError) ve cakisan tusun tasinmasi."""
from __future__ import annotations

import pytest

pygame = pytest.importorskip("pygame")


@pytest.fixture()
def settings_scene():
    from gh import headless
    from gh.scenes.settings import SettingsScene
    app = headless.make_app()
    sc = SettingsScene(app)
    app.stack = [sc]
    yield app, sc
    app.stack = []


def press(sc, action: str, key: int) -> None:
    sc.binding = action
    sc.capture_keys = True
    sc.on_key(pygame.event.Event(pygame.KEYDOWN, key=key, mod=0, unicode="", scancode=0))


def test_rebind_fret_key(settings_scene):
    app, sc = settings_scene
    press(sc, "fret:0", pygame.K_q)
    assert app.settings.keys.frets[0][0] == "q"
    assert sc.binding is None and not sc.capture_keys


def test_rebind_to_key_of_other_fret_moves_it(settings_scene):
    app, sc = settings_scene
    k = app.settings.keys
    other = k.frets[1][0]                         # 2. perdenin tusu (varsayilan "2")
    press(sc, "fret:0", pygame.key.key_code(other))
    assert k.frets[0][0] == other
    assert other not in k.frets[1]                 # ayni tus iki perdede olmaz


def test_translation_format_named_key():
    from gh.i18n import t
    assert "F" in t("set.bound", key="F")          # bicim adi 'key' parametreyle cakismaz


def test_f3_is_bindable_and_not_a_global_hotkey(settings_scene):
    """F3 artik debug kisayolu degil: perde tusu olarak atanabilir, basinca debug katmani degismez."""
    app, sc = settings_scene
    press(sc, "fret:0", pygame.K_F3)
    assert app.settings.keys.frets[0][0] == "f3"
    before = app.settings.video.show_debug
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F3, mod=0, unicode="", scancode=0))
    app.poll()
    assert app.settings.video.show_debug == before
