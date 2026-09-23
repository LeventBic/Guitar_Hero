"""Menu arayuzu yardimcilari: sahne / video arka planlari, menu listesi, metal paneller, yildizlar, ipucu cubugu."""
from __future__ import annotations

import math
import random

import pygame

from ..i18n import t
from .assets import (BG_BOTTOM, BG_TOP, GOLD, NEON_CYAN, NEON_PINK, NEON_PURPLE, TEXT_DIM, W,
                     blur_surface, lerp_color, lighten, metal_panel, radial_glow, scale_color, star_points,
                     vertical_gradient)

H = 720


# menu videosu (Ayarlar -> Arka plan videosu); App ve ayarlar sahnesi gunceller
menu_video_enabled = True


class SynthBackground:
    """Menu arka plani (rock sahnesi): karartilmis gitarist klibi - tum menulerde kesintisiz tek oynatici -
    video yoksa spot isikli, sisli koyu sahne. (Ad eski synthwave temasindan kalma; API ayni.)"""

    _video = None
    _video_t0 = 0.0
    _video_tried = False

    def __init__(self):
        self.t = 0.0
        base = vertical_gradient((W, H), (5, 4, 4), (30, 14, 8))
        floor = radial_glow(520, (70, 30, 10), 1.6)
        base.blit(pygame.transform.smoothscale(floor, (1600, 420)), (W // 2 - 800, H - 250),
                  special_flags=pygame.BLEND_ADD)
        self.base = base.convert()
        # spot huzmeleri: sicak beyaz / kehribar, 3 yogunluk seviyesi
        self.beams = []
        for x, col, ang in ((170, (255, 170, 80), 0.32), (470, (255, 235, 200), 0.1),
                            (810, (255, 235, 200), -0.1), (1110, (255, 170, 80), -0.32)):
            cone = self._cone(col, ang)
            self.beams.append((x, [self._scaled(cone, k) for k in (0.45, 0.7, 1.0)]))
        # sis bulutlari (yavas kayan, toplamali)
        rng = random.Random(11)
        self.smoke = []
        for _ in range(5):
            g = radial_glow(rng.randint(160, 260), (34, 26, 22), 1.2)
            g = pygame.transform.smoothscale(g, (g.get_width() * 2, g.get_height())).convert()
            self.smoke.append((g, rng.uniform(0, W), rng.uniform(H * 0.35, H * 0.8), rng.uniform(8, 22)))
        # vinyet (kenarlar koyu, alt kisim sicak)
        vig = pygame.Surface((W, H), pygame.SRCALPHA)
        for i in range(24):
            k = i / 24
            pygame.draw.rect(vig, (0, 0, 0, int(150 * (1 - k) ** 2)), (int(k * 120), int(k * 70),
                             W - int(k * 240), H - int(k * 140)), 6)
        self.vignette = vig.convert_alpha()
        self.dim = pygame.Surface((W, H))
        self._ensure_video()

    @staticmethod
    def _scaled(img, k):
        s = img.copy()
        m = pygame.Surface(s.get_size())
        v = int(255 * k)
        m.fill((v, v, v))
        s.blit(m, (0, 0), special_flags=pygame.BLEND_MULT)
        return s.convert()

    @staticmethod
    def _cone(color, ang):
        w, h = 380, 620
        s = pygame.Surface((w, h))
        s.fill((0, 0, 0))
        for k in range(22):
            t = k / 22
            half = 10 + t * 160
            c = scale_color(color, 0.016 * (1 - t) + 0.004)
            tmp = pygame.Surface((w, h))
            tmp.fill((0, 0, 0))
            pygame.draw.polygon(tmp, c, [(w / 2 - 5, 0), (w / 2 + 5, 0), (w / 2 + half, h), (w / 2 - half, h)])
            s.blit(tmp, (0, 0), special_flags=pygame.BLEND_ADD)
        return pygame.transform.rotate(blur_surface(s, 8), math.degrees(ang))

    @classmethod
    def _ensure_video(cls) -> None:
        if cls._video is not None or cls._video_tried or not menu_video_enabled:
            return
        cls._video_tried = True
        try:
            import time as _time

            from ..video import VideoPlayer, available, stock_clips
            clips = stock_clips()
            if clips and available():
                cls._video = VideoPlayer(random.choice(clips), (W, H), loop=True)
                cls._video_t0 = _time.perf_counter()
        except Exception:
            cls._video = None

    def update(self, dt: float) -> None:
        self.t += dt

    def draw(self, surf: pygame.Surface, pulse: float = 0.0) -> None:
        frame = None
        v = SynthBackground._video
        if v is not None and menu_video_enabled:
            import time as _time
            frame = v.frame(_time.perf_counter() - SynthBackground._video_t0)
        if frame is not None:
            surf.blit(frame, (0, 0))
            k = int(70 + 14 * pulse)
            self.dim.fill((k + 8, k, k - 6))                     # karart + sicak ton
            surf.blit(self.dim, (0, 0), special_flags=pygame.BLEND_MULT)
        else:
            surf.blit(self.base, (0, 0))
            for g, x0, y, speed in self.smoke:
                x = (x0 + self.t * speed) % (W + g.get_width()) - g.get_width()
                surf.blit(g, (x, y - g.get_height() // 2), special_flags=pygame.BLEND_ADD)
        for i, (x, levels) in enumerate(self.beams):
            sway = math.sin(self.t * 0.35 + i * 1.7) * 18
            lvl = 2 if pulse > 0.66 else 1 if pulse > 0.2 else 0
            img = levels[lvl if frame is None else max(0, lvl - 1)]
            surf.blit(img, (x + sway - img.get_width() // 2, -60), special_flags=pygame.BLEND_ADD)
        surf.blit(self.vignette, (0, 0))


class StageBackground:
    """Oyun ici sahne: koyu degrade, ritme gore nabizlayan isik huzmeleri, kalabalik silueti."""

    def __init__(self, album: pygame.Surface | None = None):
        base = vertical_gradient((W, H), BG_TOP, BG_BOTTOM)
        if album is not None:
            try:
                a = pygame.transform.smoothscale(album, (W, W))
                a = blur_surface(a, 18)
                dark = pygame.Surface((W, W))
                dark.fill((40, 40, 50))
                a.blit(dark, (0, 0), special_flags=pygame.BLEND_MULT)
                base.blit(a, (0, (H - W) // 2), special_flags=pygame.BLEND_ADD)
            except Exception:
                pass
        # sahne zemini parlamasi
        g = radial_glow(420, (47, 41, 35), 1.3)
        base.blit(pygame.transform.smoothscale(g, (1400, 500)), (W // 2 - 700, 420), special_flags=pygame.BLEND_ADD)
        self.base = base.convert()
        # isik huzmeleri (toplamali, 3 yogunluk)
        self.beams = []
        specs = [(160, NEON_PINK, 0.28), (360, NEON_CYAN, 0.12), (920, NEON_CYAN, -0.12), (1120, NEON_PINK, -0.28)]
        for x, col, ang in specs:
            levels = []
            cone = self._cone(col, ang)
            for k in (0.35, 0.6, 1.0):
                s = cone.copy()
                m = pygame.Surface(s.get_size())
                v = int(255 * k)
                m.fill((v, v, v))
                s.blit(m, (0, 0), special_flags=pygame.BLEND_MULT)
                levels.append(s.convert())
            self.beams.append((x, levels))
        # kalabalik silueti
        rng = random.Random(9)
        crowd = pygame.Surface((W + 40, 120), pygame.SRCALPHA)
        for i in range(90):
            x = rng.randint(-20, W + 40)
            y = rng.randint(40, 90)
            r = rng.randint(14, 22)
            col = (6, 4, 14, 255)
            pygame.draw.circle(crowd, col, (x, y), r)
            pygame.draw.rect(crowd, col, (x - r - 4, y + r - 6, 2 * r + 8, 120))
            if rng.random() < 0.3:
                pygame.draw.line(crowd, col, (x + r, y + 8), (x + r + 14, y - 34), 7)
        self.crowd = crowd.convert_alpha()

    def _cone(self, color, ang):
        w, h = 360, 560
        s = pygame.Surface((w, h))
        s.fill((0, 0, 0))
        for k in range(24):
            t = k / 24
            half = 12 + t * 150
            c = scale_color(color, 0.018 * (1 - t) + 0.006)
            pts = [(w / 2 - 6, 0), (w / 2 + 6, 0), (w / 2 + half, h), (w / 2 - half, h)]
            tmp = pygame.Surface((w, h))
            tmp.fill((0, 0, 0))
            pygame.draw.polygon(tmp, c, pts)
            s.blit(tmp, (0, 0), special_flags=pygame.BLEND_ADD)
        s = blur_surface(s, 8)
        s = pygame.transform.rotate(s, math.degrees(ang))
        return s

    def draw(self, surf: pygame.Surface, beat_phase: float, beat_index: int, sp: bool) -> None:
        surf.blit(self.base, (0, 0))
        for i, (x, levels) in enumerate(self.beams):
            on = (beat_index + i) % 2 == 0
            lvl = 2 if (on and beat_phase < 0.2) else 1 if beat_phase < 0.5 else 0
            img = levels[lvl]
            surf.blit(img, (x - img.get_width() // 2, -40), special_flags=pygame.BLEND_ADD)
        bounce = int(4 * max(0.0, 1 - beat_phase * 3))
        surf.blit(self.crowd, (-20, H - 96 - bounce))


# --------------------------------------------------------------------------- widget'lar

def draw_panel(surf, rect, border=NEON_PURPLE, fill=(18, 16, 14, 215), radius=12, width=2):
    """Metal plaka panel (fill'in yalniz alfa degeri kullanilir: seffaflik)."""
    r = pygame.Rect(rect)
    alpha = fill[3] if len(fill) > 3 else 232
    surf.blit(metal_panel(r.size, border, radius, min(245, alpha + 20), width), r.topleft)


class MenuList:
    """Dikey menu: animasyonlu secim cubugu, secili oge neon."""

    def __init__(self, items: list[str], x: int, y: int, spacing: int = 58, size: int = 36, align: str = "center"):
        self.items = items
        self.index = 0
        self.x, self.y = x, y
        self.spacing = spacing
        self.size = size
        self.align = align
        self._bar_y = float(y)
        self.t = 0.0

    def move(self, d: int) -> None:
        self.index = (self.index + d) % len(self.items)

    def update(self, dt: float) -> None:
        self.t += dt
        target = self.y + self.index * self.spacing
        self._bar_y += (target - self._bar_y) * min(1.0, dt * 18)

    def draw(self, surf, assets, width: int = 420) -> None:
        tc = assets.text
        bar = pygame.Rect(0, 0, width, self.spacing - 10)
        if self.align == "center":
            bar.centerx = self.x
        else:
            bar.x = self.x - 20
        bar.centery = int(self._bar_y)
        s = pygame.Surface(bar.size, pygame.SRCALPHA)
        k = 0.5 + 0.5 * math.sin(self.t * 4)
        pygame.draw.rect(s, (255, 118, 30, 60 + int(30 * k)), (0, 0, *bar.size), border_radius=12)
        pygame.draw.rect(s, (255, 176, 72, 220), (0, 0, *bar.size), 2, border_radius=12)
        surf.blit(s, bar.topleft)
        for i, key in enumerate(self.items):
            it = t(key)            # ogeler i18n anahtari (ya da duz metin); cizimde cevrilir
            sel = i == self.index
            if sel:
                img = tc.glow(it, self.size, (255, 230, 250), "title", True, glow_color=NEON_PINK, radius=8)
                pad = 16
            else:
                img = tc.render(it, self.size - 4, TEXT_DIM, "title", True)
                pad = 0
            y = self.y + i * self.spacing
            if self.align == "center":
                surf.blit(img, (self.x - img.get_width() // 2, y - img.get_height() // 2))
            else:
                surf.blit(img, (self.x - pad, y - img.get_height() // 2))


def draw_star(surf, center, r, filled: bool, color=GOLD, outline=(255, 250, 220)):
    pts = star_points(center[0], center[1], r, r * 0.45)
    if filled:
        pygame.draw.polygon(surf, color, pts)
        pygame.draw.polygon(surf, lighten(color, 0.5), star_points(center[0], center[1] - r * 0.08, r * 0.55, r * 0.25))
        pygame.draw.polygon(surf, outline, pts, 2)
    else:
        pygame.draw.polygon(surf, (50, 44, 38), pts)
        pygame.draw.polygon(surf, (90, 86, 120), pts, 2)


def draw_hints(surf, assets, hints: list[tuple[str, str]], y: int = 690) -> None:
    """Alt ipucu cubugu: [(tus, aciklama), ...]."""
    tc = assets.text
    parts = []
    total = 0
    for key, desc in hints:
        k = tc.render(t(key), 16, (26, 20, 14), "ui", True)
        d = tc.render(t(desc), 16, TEXT_DIM, "ui")
        parts.append((k, d))
        total += k.get_width() + 14 + 8 + d.get_width() + 28
    strip = pygame.Surface((W, 36), pygame.SRCALPHA)
    strip.fill((10, 8, 6, 232))
    surf.blit(strip, (0, y - 8))
    x = W // 2 - total // 2
    for k, d in parts:
        r = pygame.Rect(x, y - 2, k.get_width() + 14, 22)
        pygame.draw.rect(surf, (222, 212, 194), r, border_radius=5)
        surf.blit(k, (x + 7, y))
        x = r.right + 8
        surf.blit(d, (x, y))
        x += d.get_width() + 28


def fade_overlay(surf, alpha: int, color=(0, 0, 0)) -> None:
    if alpha <= 0:
        return
    s = pygame.Surface(surf.get_size())
    s.fill(color)
    s.set_alpha(min(255, alpha))
    surf.blit(s, (0, 0))


def draw_title_logo(surf, assets, center, size=150, t=0.0) -> None:
    img = assets.text.glow("RIFF", size, (255, 206, 120), "title", True, glow_color=(255, 90, 20), radius=16)
    x = center[0] - img.get_width() // 2
    y = center[1] - img.get_height() // 2
    surf.blit(img, (x, y))
    # alt cizgi
    w = img.get_width() - 80
    k = 0.5 + 0.5 * math.sin(t * 2.5)
    col = lerp_color(NEON_CYAN, (255, 255, 255), k * 0.4)
    pygame.draw.line(surf, col, (center[0] - w // 2, y + img.get_height() - 30), (center[0] + w // 2, y + img.get_height() - 30), 3)
