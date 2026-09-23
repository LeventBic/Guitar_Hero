"""Menu arayuzu yardimcilari: neon arka planlar, menu listesi, paneller, yildizlar, ipucu cubugu."""
from __future__ import annotations

import math
import random

import pygame

from ..i18n import t
from .assets import (BG_BOTTOM, BG_TOP, GOLD, NEON_CYAN, NEON_PINK, NEON_PURPLE, TEXT_DIM, W,
                     blur_surface, lerp_color, lighten, radial_glow, scale_color, star_points, vertical_gradient)

H = 720


class SynthBackground:
    """Menu arka plani: degrade gok, cizgili gunes, kayan perspektif izgara, yildizlar."""

    def __init__(self):
        self.t = 0.0
        sky = vertical_gradient((W, H), (6, 4, 20), (40, 10, 60))
        # gunes
        sun_r = 150
        sun = pygame.Surface((sun_r * 2, sun_r * 2), pygame.SRCALPHA)
        grad = vertical_gradient((sun_r * 2, sun_r * 2), (255, 220, 90, 255), (255, 40, 150, 255), alpha=True)
        mask = pygame.Surface((sun_r * 2, sun_r * 2), pygame.SRCALPHA)
        pygame.draw.circle(mask, (255, 255, 255, 255), (sun_r, sun_r), sun_r)
        for i in range(7):
            y = sun_r + 20 + i * 18
            pygame.draw.rect(mask, (0, 0, 0, 0), (0, y, sun_r * 2, 3 + i * 1.6))
        grad.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        glow = radial_glow(sun_r + 90, (120, 30, 90), 1.6)
        self.horizon = 430
        sky.blit(glow, (W // 2 - glow.get_width() // 2, self.horizon - 120 - glow.get_height() // 2 + 40),
                 special_flags=pygame.BLEND_ADD)
        sky.blit(grad, (W // 2 - sun_r, self.horizon - sun_r - 110))
        # daglar
        rng = random.Random(5)
        pts = [(0, self.horizon)]
        x = 0
        while x < W:
            x += rng.randint(40, 90)
            pts.append((x, self.horizon - rng.randint(10, 70)))
        pts += [(W, self.horizon), (W, H), (0, H)]
        pygame.draw.polygon(sky, (16, 6, 34), pts)
        pygame.draw.lines(sky, (120, 40, 160), False, pts[:-3], 2)
        floor = vertical_gradient((W, H - self.horizon), (22, 6, 40), (8, 2, 18))
        sky.blit(floor, (0, self.horizon))
        # yildizlar
        for _ in range(140):
            x, y = rng.randint(0, W), rng.randint(0, self.horizon - 60)
            c = rng.randint(90, 220)
            sky.set_at((x, y), (c, c, min(255, c + 30)))
        self.base = sky.convert()
        self.hglow = radial_glow(80, (255, 60, 170), 1.5).convert()

    def update(self, dt: float) -> None:
        self.t += dt

    def draw(self, surf: pygame.Surface, pulse: float = 0.0) -> None:
        surf.blit(self.base, (0, 0))
        hz = self.horizon
        col = lerp_color((150, 40, 170), (255, 90, 200), pulse)
        # yatay cizgiler (kayan)
        phase = (self.t * 0.6) % 1.0
        for i in range(18):
            k = (i + phase) / 18
            y = hz + (H - hz) * (k ** 2.2)
            c = lerp_color((40, 10, 60), col, min(1.0, k * 1.6))
            pygame.draw.line(surf, c, (0, y), (W, y), 1 if k < 0.4 else 2)
        for i in range(-16, 17):
            x_far = W / 2 + i * 22
            x_near = W / 2 + i * 150
            pygame.draw.line(surf, lerp_color((40, 10, 60), col, 0.7), (x_far, hz), (x_near, H), 1)
        pygame.draw.line(surf, (255, 120, 220), (0, hz), (W, hz), 2)


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
        g = radial_glow(420, (40, 18, 70), 1.3)
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

def draw_panel(surf, rect, border=NEON_PURPLE, fill=(12, 10, 28, 215), radius=16, width=2):
    r = pygame.Rect(rect)
    s = pygame.Surface(r.size, pygame.SRCALPHA)
    pygame.draw.rect(s, fill, (0, 0, *r.size), border_radius=radius)
    pygame.draw.rect(s, border + (230,), (0, 0, *r.size), width, border_radius=radius)
    surf.blit(s, r.topleft)


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
        pygame.draw.rect(s, (255, 60, 170, 60 + int(30 * k)), (0, 0, *bar.size), border_radius=12)
        pygame.draw.rect(s, (255, 90, 190, 220), (0, 0, *bar.size), 2, border_radius=12)
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
        pygame.draw.polygon(surf, (40, 36, 60), pts)
        pygame.draw.polygon(surf, (90, 86, 120), pts, 2)


def draw_hints(surf, assets, hints: list[tuple[str, str]], y: int = 690) -> None:
    """Alt ipucu cubugu: [(tus, aciklama), ...]."""
    tc = assets.text
    parts = []
    total = 0
    for key, desc in hints:
        k = tc.render(t(key), 16, (20, 16, 30), "ui", True)
        d = tc.render(t(desc), 16, TEXT_DIM, "ui")
        parts.append((k, d))
        total += k.get_width() + 14 + 8 + d.get_width() + 28
    strip = pygame.Surface((W, 36), pygame.SRCALPHA)
    strip.fill((4, 2, 12, 225))
    surf.blit(strip, (0, y - 8))
    x = W // 2 - total // 2
    for k, d in parts:
        r = pygame.Rect(x, y - 2, k.get_width() + 14, 22)
        pygame.draw.rect(surf, (200, 200, 225), r, border_radius=5)
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
    img = assets.text.glow("RIFF", size, (255, 110, 200), "title", True, glow_color=(255, 40, 160), radius=16)
    x = center[0] - img.get_width() // 2
    y = center[1] - img.get_height() // 2
    surf.blit(img, (x, y))
    # alt cizgi
    w = img.get_width() - 80
    k = 0.5 + 0.5 * math.sin(t * 2.5)
    col = lerp_color(NEON_CYAN, (255, 255, 255), k * 0.4)
    pygame.draw.line(surf, col, (center[0] - w // 2, y + img.get_height() - 30), (center[0] + w // 2, y + img.get_height() - 30), 3)
