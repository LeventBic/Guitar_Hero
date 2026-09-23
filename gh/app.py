"""Uygulama: pencere, ana dongu, sahne yigini.

Ana dongu
---------
Girdi, frame'lerden bagimsiz olarak ~1 ms aralikla poll edilir (olay zaman damgasi = poll araliginin
ortasi, bkz. gh.input). Cizim `fps_limit` hizinda (0 = sinirsiz) yapilir; frame'ler arasinda kisa uykularla
poll surer. Pencere 1280x720 mantiksal cozunurlukte cizilir, SDL (pygame.SCALED) pencereye olcekler;
F11 tam ekran, pencere yeniden boyutlandirilabilir. Debug katmani Ayarlar'dan (FPS / hata ayiklama).
"""
from __future__ import annotations

import os
import time
from collections import deque

import pygame

from .audio import AudioSystem
from .config import GAME_TITLE, resource_root
from .input import InputManager
from .library import SongLibrary
from .render.assets import Assets, H, W
from .settings_store import AppSettings, save_settings


class App:
    def __init__(self, settings: AppSettings, *, headless: bool = False, audio: bool = True):
        self.settings = settings
        from .render import ui as _ui
        _ui.menu_video_enabled = bool(settings.extra.get("bg_video", True)) and not headless
        self.headless = headless
        from . import i18n
        i18n.set_language(settings.extra.get("language") or i18n.default_language())
        self.running = True
        self.stack: list = []
        self.window = None
        self._init_display()
        self.screen = pygame.Surface((W, H)) if headless else self.window
        self.assets = Assets()
        self.audio = AudioSystem(settings, enabled=audio)
        self.input = InputManager(settings)
        self.library = SongLibrary()
        self.frame_times: deque = deque(maxlen=120)
        self.fps = 0.0
        self.frame_ms = 0.0
        self.pending: list = []
        self.quit_after = 0.0          # >0: bu kadar saniye sonra cik (test)
        self.total_frames = 0
        self.total_render_ms = 0.0
        self.run_start = 0.0
        # surukle-birak / ice aktarma
        self._drop_batch: list[str] = []
        self._drop_open = False
        self.pending_drops: list[str] = []     # oyun sirasinda birakilanlar (menuye donunce islenir)
        self.inbox_failed: set = set()         # bu oturumda basarisiz olan gelen kutusu dosyalari (yol, mtime)
        self.drop_flash = 0.0                  # son birakma ani (perf_counter), gorsel geri bildirim
        try:
            from .importer import inbox_dir
            inbox_dir(create=True)
        except Exception:
            pass

    # ------------------------------------------------------------------ pencere
    def _init_display(self) -> None:
        if self.headless:
            if not pygame.display.get_init():
                pygame.display.init()
            if pygame.display.get_surface() is None:
                pygame.display.set_mode((W, H))
            return
        pygame.display.set_caption(GAME_TITLE)
        try:
            icon = pygame.image.load(os.path.join(resource_root(), "assets", "icon.png"))
            pygame.display.set_icon(icon)
        except Exception:
            pass
        flags = pygame.SCALED | pygame.RESIZABLE
        try:
            self.window = pygame.display.set_mode((W, H), flags, vsync=0)
        except pygame.error:
            self.window = pygame.display.set_mode((W, H))
        if self.settings.video.fullscreen:
            self.toggle_fullscreen(save=False)

    def toggle_fullscreen(self, save: bool = True) -> None:
        if self.headless:
            return
        try:
            pygame.display.toggle_fullscreen()
            self.settings.video.fullscreen = bool(pygame.display.is_fullscreen())
        except Exception:
            pass
        if save:
            save_settings(self.settings)

    # ------------------------------------------------------------------ sahneler
    @property
    def top(self):
        return self.stack[-1] if self.stack else None

    def push(self, scene) -> None:
        self.input.clear_held()
        self.stack.append(scene)
        scene.enter()

    def pop(self):
        self.input.clear_held()
        if not self.stack:
            return None
        s = self.stack.pop()
        s.exit()
        if self.stack:
            self.stack[-1].resume()
        else:
            self.running = False
        return s

    def replace(self, scene) -> None:
        self.input.clear_held()
        if self.stack:
            self.stack.pop().exit()
        self.stack.append(scene)
        scene.enter()

    def pop_to(self, cls) -> None:
        """cls turunde sahne en ustte olana kadar kapat."""
        while self.stack and not isinstance(self.stack[-1], cls):
            self.stack.pop().exit()
        if self.stack:
            self.stack[-1].resume()

    def back_to_songlist(self) -> None:
        """Oyun / sonuc ekranindan sarki listesine don (yigindaki listeye; yoksa ana menunun ustune yenisi)."""
        from .scenes.songlist import SongListScene
        idx = max((i for i, s in enumerate(self.stack) if isinstance(s, SongListScene)), default=-1)
        self.input.clear_held()
        if idx >= 0:
            while len(self.stack) > idx + 1:
                self.stack.pop().exit()
            self.stack[-1].resume()
            return
        while len(self.stack) > 1:
            self.stack.pop().exit()
        self.push(SongListScene(self))

    def open_songlist(self, select_folder: str | None = None):
        """Sarki listesine git (yigindakine; yoksa ana menunun ustune yenisi), kutuphaneyi yenile ve sec."""
        from .scenes.songlist import SongListScene
        idx = max((i for i, s in enumerate(self.stack) if isinstance(s, SongListScene)), default=-1)
        self.input.clear_held()
        if idx >= 0:
            while len(self.stack) > idx + 1:
                self.stack.pop().exit()
            sl = self.stack[-1]
            sl.refresh(select_folder)
            sl.resume()
            return sl
        while len(self.stack) > 1:
            self.stack.pop().exit()
        sl = SongListScene(self, select_folder=select_folder)
        self.push(sl)
        return sl

    # ------------------------------------------------------------------ ice aktarma
    def handle_drop(self, paths: list[str]) -> None:
        """Pencereye dosya/klasor birakildi."""
        import time as _t
        self.drop_flash = _t.perf_counter()
        paths = [p for p in paths if p]
        if not paths:
            return
        top = self.top
        if top is not None and hasattr(top, "on_drop"):
            top.on_drop(paths)
            return
        if top is not None and getattr(top, "blocks_import", False):
            self.pending_drops.extend(paths)       # oyun / kalibrasyon: sonra
            return
        from .scenes.importer import ImportScene
        self.push(ImportScene(self, paths))

    def inbox_pending(self, include_failed: bool = False) -> list[str]:
        try:
            from .importer import inbox_files
            files = inbox_files()
        except Exception:
            return []
        if include_failed:
            return files
        out = []
        for f in files:
            try:
                key = (os.path.normcase(f), os.path.getmtime(f))
            except OSError:
                continue
            if key not in self.inbox_failed:
                out.append(f)
        return out

    def check_inbox(self) -> bool:
        """Songs/_Import'ta yeni ses dosyasi varsa ice aktarma sahnesini ac."""
        files = self.inbox_pending()
        if not files:
            return False
        from .scenes.importer import ImportScene
        self.push(ImportScene(self, files, from_inbox=True))
        return True

    def quit(self) -> None:
        self.running = False

    # ------------------------------------------------------------------ cizim
    def draw(self, surf: pygame.Surface) -> None:
        if not self.stack:
            surf.fill((0, 0, 0))
            return
        start = len(self.stack) - 1
        while start > 0 and not self.stack[start].opaque:
            start -= 1
        for s in self.stack[start:]:
            s.draw(surf)

    # ------------------------------------------------------------------ dongu
    def poll(self) -> None:
        """Olaylari cek, zaman damgala ve ustteki sahneye ilet (frame'den bagimsiz, ~1 kHz)."""
        inp = self.input
        prev, now = inp.begin_poll()
        stamp = inp.stamp(prev, now)
        drops: list[str] | None = None
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                self.running = False
                return
            if ev.type == pygame.DROPBEGIN:
                self._drop_open = True
                self._drop_batch = []
                continue
            if ev.type == pygame.DROPFILE:
                self._drop_batch.append(getattr(ev, "file", "") or "")
                continue
            if ev.type == pygame.DROPCOMPLETE:
                self._drop_open = False
                drops, self._drop_batch = self._drop_batch, []
                continue
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_F11 or (ev.key == pygame.K_RETURN and ev.mod & pygame.KMOD_ALT):
                    self.toggle_fullscreen()
                    continue
            inp.process(ev, stamp)
        inp.update(now)
        if drops is None and self._drop_batch and not self._drop_open:
            drops, self._drop_batch = self._drop_batch, []     # DROPBEGIN/COMPLETE gondermeyen surucu
        top = self.top
        if top is None:
            return
        if top.capture_keys:
            for k in list(inp.raw_keys):
                top.on_key(k)
        else:
            for g in list(inp.game):
                top.on_game(g)
            for m in list(inp.menu):
                if self.top is not top:
                    break
                top.on_menu(m)
            # ekstra kisayollar (ornek: sarki listesinde I / R); oyun tuslarina atanmis tuslar haric
            for k in list(inp.raw_keys):
                if self.top is not top:
                    break
                if k.key not in inp.keymap:
                    top.on_shortcut(k.key)
        if drops:
            self.handle_drop(drops)

    def frame(self, dt: float) -> None:
        t0 = time.perf_counter()
        if self.pending_drops and self.top is not None and not getattr(self.top, "blocks_import", False):
            paths, self.pending_drops = self.pending_drops, []
            self.handle_drop(paths)
        if self.top is not None:
            self.top.update(dt)
        self.draw(self.screen)
        if not self.headless:
            pygame.display.flip()
        self.frame_ms = (time.perf_counter() - t0) * 1000.0
        self.total_frames += 1
        self.total_render_ms += self.frame_ms

    def run(self) -> None:
        last_frame = time.perf_counter()
        next_frame = last_frame
        self.run_start = last_frame
        self.total_frames = 0
        self.total_render_ms = 0.0
        while self.running and self.stack:
            if self.quit_after and last_frame - self.run_start > self.quit_after:
                break
            self.poll()
            if not self.running:
                break
            now = time.perf_counter()
            limit = self.settings.video.fps_limit
            if limit <= 0 or now >= next_frame:
                dt = min(0.1, now - last_frame)
                last_frame = now
                if limit > 0:
                    next_frame = max(next_frame + 1.0 / limit, now - 0.5 / limit)
                self.frame(dt)
                self.frame_times.append(now)
                if len(self.frame_times) >= 2:
                    span = self.frame_times[-1] - self.frame_times[0]
                    if span > 0:
                        self.fps = (len(self.frame_times) - 1) / span
            else:
                remain = next_frame - time.perf_counter()
                if remain > 0.0015:
                    time.sleep(0.001)
                elif remain > 0:
                    time.sleep(0)
        while self.stack:
            self.stack.pop().exit()
        self.audio.stop_all()
        save_settings(self.settings)
