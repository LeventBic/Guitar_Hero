"""Headless calistirma: duman testi (simule saat, bot) ve ekran goruntuleri. main.py ve testler kullanir."""
from __future__ import annotations

import os
import time

import pygame

from .settings_store import AppSettings, default_settings


def setup_env() -> None:
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    os.environ["SDL_AUDIODRIVER"] = "dummy"


def make_app(settings: AppSettings | None = None, audio: bool = True):
    """Headless App (dummy video/ses surucusu). Ayar dosyasina yazilmaz."""
    from .settings_store import set_readonly
    set_readonly(True)
    setup_env()
    if not pygame.get_init():
        pygame.init()
    if not pygame.display.get_init():
        pygame.display.init()
    if not pygame.font.get_init():
        pygame.font.init()
    from .app import App
    return App(settings or default_settings(), headless=True, audio=audio)


def run_smoke(app, info, diff: str, fps: float = 30.0, draw: bool = True) -> dict:
    """Bot ile simule saatte sarkinin tamamini oynat. ok = full combo ve cokme yok."""
    from .scenes.gameplay import LEAD_IN, GameplayScene
    t0 = time.perf_counter()
    scene = GameplayScene(app, info, diff, autoplay=True, sim=True)
    app.stack = [scene]
    scene.enter()
    dt = 1.0 / fps
    max_steps = int((scene.end_trigger + LEAD_IN + 30) * fps)
    frames = 0
    for _ in range(max_steps):
        scene.update(dt)
        if draw:
            scene.draw(app.screen)
        frames += 1
        if scene.done:
            break
    eng = scene.engine
    res = scene.result or scene.stats()
    ok = (scene.done and not res["failed"] and eng.notes_hit == eng.total_notes and eng.notes_missed == 0
          and eng.overstrums == 0 and eng.max_combo == eng.total_notes)
    app.stack = []
    return {
        "ok": ok, "song": info.name, "diff": diff, "score": eng.score, "stars": eng.stars(),
        "hit": eng.notes_hit, "total": eng.total_notes, "missed": eng.notes_missed, "overstrums": eng.overstrums,
        "max_combo": eng.max_combo, "frames": frames, "seconds": time.perf_counter() - t0,
        "load_errors": list(scene.conductor.load_errors), "result": res,
    }


def smoke_all(app, song: str | None = None, diff: str | None = None, fps: float = 30.0) -> list[dict]:
    lib = app.library
    lib.scan()
    if song:
        info = lib.find(song)
        if info is None:
            raise SystemExit(f"song not found: {song}")
        songs = [info]
    else:
        songs = lib.songs
    out = []
    from .library import available_difficulties
    for info in songs:
        chart = lib.chart(info.folder)
        diffs = available_difficulties(chart)
        if diff:
            diffs = [d for d in diffs if d == diff]
        for d in diffs:
            out.append(run_smoke(app, info, d, fps))
    return out


def import_files(app, paths: list[str], timeout: float = 600.0) -> list[dict]:
    """Ice aktarma sahnesini (arka plan is parcacigi dahil) headless calistir. [{name, ok, folder, message}]"""
    from .scenes.importer import ImportScene
    scene = ImportScene(app, paths)
    app.stack = [scene]
    scene.enter()
    scene.wait(timeout)
    out = [{"name": j.name, "ok": j.status == "ok", "folder": j.result, "message": j.message} for j in scene.jobs]
    app.stack = []
    return out


def _save(surf: pygame.Surface, path: str, scale: float = 1.0) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    if scale != 1.0:
        surf = pygame.transform.smoothscale(surf, (int(surf.get_width() * scale), int(surf.get_height() * scale)))
    pygame.image.save(surf, path)


def screenshot_gameplay(app, info, diff: str, at: float, path: str, scale: float = 1.0, autoplay: bool = True) -> None:
    from .scenes.gameplay import GameplayScene
    scene = GameplayScene(app, info, diff, autoplay=autoplay, sim=True)
    app.stack = [scene]
    scene.enter()
    dt = 1.0 / 60.0
    while scene.visual_time < at - 0.6 and not scene.done:
        scene.update(dt)
    while scene.visual_time < at and not scene.done:
        scene.update(dt)
        scene.draw(app.screen)
    scene.draw(app.screen)
    _save(app.screen, path, scale)
    app.stack = []


def _run_scene(app, scene, seconds: float, dt: float = 1 / 60) -> None:
    app.stack.append(scene)
    scene.enter()
    t = 0.0
    while t < seconds:
        scene.update(dt)
        t += dt
    app.draw(app.screen)


def screenshot_menus(app, path: str, scale: float = 1.0) -> list[str]:
    """path = baslik ekrani; ayrica <ad>_songs, _difficulty, _settings, _calibration, _results."""
    from .scenes import (CalibrationScene, DifficultyScene, ResultsScene, SettingsScene, SongListScene,
                         TitleScene)
    base, ext = os.path.splitext(path)
    ext = ext or ".png"
    written = []

    def save(name):
        p = path if name == "" else f"{base}_{name}{ext}"
        _save(app.screen, p, scale)
        written.append(p)

    app.stack = []
    title = TitleScene(app)
    _run_scene(app, title, 1.3)
    save("")
    sl = SongListScene(app)
    _run_scene(app, sl, 0.6)
    save("songs")
    if sl.songs:
        sl._load_selected()
        _run_scene(app, DifficultyScene(app, sl), 0.4)
        save("difficulty")
        app.stack.pop()
    app.stack = [title]
    _run_scene(app, SettingsScene(app), 0.4)
    save("settings")
    app.stack = [title]
    _run_scene(app, CalibrationScene(app), 0.4)
    save("calibration")
    # sarki ekleme: birakma alani, ilerleme paneli, sonuc (sahte is durumlariyla, is parcacigi yok)
    from .scenes.importer import ImportScene, Job
    app.stack = [title]
    imp = ImportScene(app)
    _run_scene(app, imp, 0.5)
    save("import")
    demo = [("audio", "Artist - First Song.mp3", "ok", "", 1.0), ("audio", "Artist - Second Song.flac", "running",
            "Finding notes", 0.62), ("audio", "Third Song.ogg", "queued", "", 0.0),
            ("audio", "broken file.wav", "error", "cannot decode audio (unsupported format)", 0.0)]
    imp.jobs = []
    for kind, name, status, stage, prog in demo:
        j = Job(kind, name)
        j.status, j.stage, j.progress = status, stage, prog
        if status == "ok":
            j.result = os.path.join("Songs", "Artist - First Song")
        if status == "error":
            j.message, j.msg_key, j.msg_params = stage, "imp.err_decode", {"err": "unsupported format"}
        imp.jobs.append(j)
    imp.mode = "work"
    app.draw(app.screen)
    save("import_progress")
    for j in imp.jobs:
        if j.status in ("running", "queued"):
            j.status, j.result = "ok", os.path.join("Songs", j.name)
    imp.mode, imp.sel = "done", 0
    app.draw(app.screen)
    save("import_done")
    if sl.songs:
        info = sl.songs[0]
        from .library import available_difficulties
        diffs = available_difficulties(app.library.chart(info.folder))
        r = run_smoke(app, info, diffs[-1], fps=20, draw=False)
        app.stack = []
        _run_scene(app, ResultsScene(app, r["result"]), 3.0)
        save("results")
    app.stack = []
    return written
