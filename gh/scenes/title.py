"""Ana menu: animasyonlu neon arka plan, RIFF logosu, Play / Calibration / Settings / Quit."""
from __future__ import annotations

import random

import pygame

from ..render.assets import NEON_CYAN, TEXT_DIM, W
from ..render.ui import MenuList, SynthBackground, draw_hints, draw_title_logo
from .base import Scene

VERSION = "1.0"


class TitleScene(Scene):
    def __init__(self, app):
        super().__init__(app)
        self.bg = SynthBackground()
        self.menu = MenuList(["PLAY", "CALIBRATION", "SETTINGS", "QUIT"], W // 2, 420, spacing=58, size=36)
        rng = random.Random(1)
        self.gems = [[rng.uniform(0, W), rng.uniform(0, 720), rng.uniform(40, 120), rng.randrange(5),
                      rng.uniform(0.5, 1.0)] for _ in range(18)]

    def enter(self) -> None:
        self.app.audio.stop_preview(400)

    def resume(self) -> None:
        self.app.audio.stop_preview(400)

    def on_menu(self, action: str) -> None:
        if action == "UP":
            self.menu.move(-1)
            self.sfx("menu_move")
        elif action == "DOWN":
            self.menu.move(1)
            self.sfx("menu_move")
        elif action == "CONFIRM":
            self.sfx("menu_select")
            i = self.menu.index
            if i == 0:
                from .songlist import SongListScene
                self.app.push(SongListScene(self.app))
            elif i == 1:
                from .calibration import CalibrationScene
                self.app.push(CalibrationScene(self.app))
            elif i == 2:
                from .settings import SettingsScene
                self.app.push(SettingsScene(self.app))
            else:
                self.app.quit()
        elif action == "BACK":
            if self.menu.index == 3:
                self.app.quit()
            else:
                self.menu.index = 3
                self.sfx("menu_back")

    def update(self, dt: float) -> None:
        super().update(dt)
        self.bg.update(dt)
        self.menu.update(dt)
        for g in self.gems:
            g[1] += g[2] * dt
            if g[1] > 760:
                g[1] = -40
                g[0] = random.uniform(0, W)

    def draw(self, surf: pygame.Surface) -> None:
        pulse = max(0.0, 1 - ((self.t * 2.0) % 1.0) * 3)
        self.bg.draw(surf, pulse)
        gems = self.assets.gems
        for x, y, sp, f, sc in self.gems:
            img, ay = gems.get(f, "strum", "normal", int(40 * sc))
            surf.blit(img, (x, y))
        draw_title_logo(surf, self.assets, (W // 2, 190), 170, self.t)
        tag = self.assets.text.render("5-FRET RHYTHM GAME", 22, NEON_CYAN, "ui", True)
        pill = pygame.Rect(0, 0, tag.get_width() + 40, tag.get_height() + 10)
        pill.center = (W // 2, 318 + tag.get_height() // 2)
        ps = pygame.Surface(pill.size, pygame.SRCALPHA)
        pygame.draw.rect(ps, (8, 4, 24, 210), (0, 0, *pill.size), border_radius=pill.h // 2)
        pygame.draw.rect(ps, NEON_CYAN + (160,), (0, 0, *pill.size), 1, border_radius=pill.h // 2)
        surf.blit(ps, pill.topleft)
        surf.blit(tag, (W // 2 - tag.get_width() // 2, 318))
        self.menu.draw(surf, self.assets, 420)
        v = self.assets.text.render(f"v{VERSION}", 14, TEXT_DIM)
        surf.blit(v, (W - v.get_width() - 12, 8))
        if not self.app.settings.extra.get("calibrated"):
            tip = self.assets.text.render("Tip: run CALIBRATION once for perfect audio/video sync", 16, TEXT_DIM)
            surf.blit(tip, (W // 2 - tip.get_width() // 2, 652))
        draw_hints(surf, self.assets, [("Up/Down", "Move"), ("Enter / Green", "Select"), ("Esc", "Quit"),
                                       ("F11", "Fullscreen")])
