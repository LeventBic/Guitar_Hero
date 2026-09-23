"""Prosedurel 512x512 albüm kapaklari (pygame, ekran gerekmez).

Demo sarkilar (tools/make_demo_songs.py) ve ice aktarilan kapaksiz sarkilar icin ortak cizim kodu.
Ice aktarma arka plan is parcaciginda calistigi icin `draw_cover(..., text=False)` yazi tipi KULLANMAZ
(SDL_ttf ayni anda iki is parcaciginda yazi tipi acmaya karsi guvenli degil); yazili kapak yalniz ana
is parcacigindan / araclardan cizilir.
"""
from __future__ import annotations

import math
import zlib

import numpy as np
import pygame

SIZE = 512
STYLES = ("sun", "bolt", "fractal", "waves", "rings")
PALETTES = {
    "sun": ((40, 20, 90), (250, 120, 90)),
    "bolt": ((20, 20, 30), (120, 20, 30)),
    "fractal": ((5, 5, 20), (40, 10, 60)),
    "waves": ((10, 30, 70), (20, 160, 170)),
    "rings": ((30, 5, 40), (200, 40, 120)),
}


def _gradient(top, bottom) -> pygame.Surface:
    y = np.linspace(0.0, 1.0, SIZE)[None, :, None]
    a = np.array(top, dtype=np.float64)[None, None, :]
    b = np.array(bottom, dtype=np.float64)[None, None, :]
    arr = (a * (1 - y) + b * y) * np.ones((SIZE, 1, 1))
    return pygame.surfarray.make_surface(arr.astype(np.uint8))


def _noise(surf: pygame.Surface, rng: np.random.Generator, amount: int = 10) -> None:
    arr = pygame.surfarray.pixels3d(surf)
    n = rng.integers(-amount, amount + 1, size=arr.shape[:2])[:, :, None]
    arr[:] = np.clip(arr.astype(np.int16) + n, 0, 255).astype(np.uint8)
    del arr


def _text(surf, text, size, color, center, shadow=(0, 0, 0)):
    font = pygame.font.Font(None, size)
    img = font.render(text, True, color)
    if img.get_width() > SIZE - 40:
        img = pygame.transform.smoothscale(img, (SIZE - 40, int(img.get_height() * (SIZE - 40) / img.get_width())))
    sh = font.render(text, True, shadow)
    if sh.get_width() > SIZE - 40:
        sh = pygame.transform.smoothscale(sh, img.get_size())
    r = img.get_rect(center=center)
    surf.blit(sh, r.move(3, 3))
    surf.blit(img, r)


def _art_sun(s: pygame.Surface, rng) -> None:
    for i in range(14, 0, -1):
        rad = 60 + i * 9
        c = (255, max(80, 200 - i * 9), max(30, 90 - i * 4))
        glow = pygame.Surface((SIZE, SIZE), pygame.SRCALPHA)
        pygame.draw.circle(glow, (*c, 22), (256, 250), rad)
        s.blit(glow, (0, 0))
    pygame.draw.circle(s, (255, 214, 120), (256, 250), 70)
    for k in range(6):  # sun stripes
        y = 262 + k * 11
        pygame.draw.rect(s, (236, 110, 80), (180, y, 152, 4 + k))
    pygame.draw.rect(s, (40, 22, 60), (0, 300, SIZE, SIZE - 300))
    for x in range(-12, 13):  # perspective road grid
        pygame.draw.line(s, (255, 90, 160), (256 + x * 8, 300), (256 + x * 90, SIZE), 2)
    y, dy = 302.0, 4.0
    while y < SIZE:
        pygame.draw.line(s, (255, 90, 160), (0, int(y)), (SIZE, int(y)), 2)
        y += dy
        dy *= 1.35
    for _ in range(40):
        pygame.draw.circle(s, (255, 240, 220), (int(rng.integers(0, SIZE)), int(rng.integers(0, 200))), 1)


def _art_bolt(s: pygame.Surface, rng) -> None:
    for i in range(18):  # speed stripes
        y = int(rng.integers(0, SIZE))
        w = int(rng.integers(120, 400))
        x = int(rng.integers(-100, SIZE))
        pygame.draw.rect(s, (255, 200, 40) if i % 3 else (255, 255, 255), (x, y, w, int(rng.integers(2, 6))))
    bolt = [(290, 40), (170, 270), (250, 270), (200, 470), (350, 210), (265, 210), (330, 40)]
    glow = pygame.Surface((SIZE, SIZE), pygame.SRCALPHA)
    for w in range(24, 0, -4):
        pygame.draw.polygon(glow, (255, 230, 90, 18), bolt, w)
    s.blit(glow, (0, 0))
    pygame.draw.polygon(s, (255, 226, 60), bolt)
    pygame.draw.polygon(s, (255, 255, 255), bolt, 4)


def _art_fractal(s: pygame.Surface, rng) -> None:
    cx, cy = 256, 240

    def tri(x, y, r, a, depth):
        pts = [(x + r * math.cos(a + k * 2 * math.pi / 3), y + r * math.sin(a + k * 2 * math.pi / 3)) for k in range(3)]
        c = (80 + depth * 30, 220 - depth * 25, 255)
        pygame.draw.polygon(s, c, pts, 2)
        if depth < 5:
            for px, py in pts:
                tri(px, py, r * 0.48, a + 0.35, depth + 1)

    tri(cx, cy, 150, -math.pi / 2, 0)
    for k in range(7, 0, -1):
        pygame.draw.circle(s, (120, 40 + k * 20, 200), (cx, cy), 18 + k * 30, 1)
    pygame.draw.circle(s, (255, 60, 120), (cx, cy), 14)


def _art_waves(s: pygame.Surface, rng) -> None:
    ph = float(rng.uniform(0, 6.28))
    for k in range(16):
        amp = 18 + k * 3
        y0 = 90 + k * 24
        col = (60 + k * 10, 200 - k * 5, 255 - k * 6)
        pts = [(x, y0 + amp * math.sin(x / 60.0 + ph + k * 0.45)) for x in range(0, SIZE + 8, 8)]
        pygame.draw.lines(s, col, False, pts, 3)
    pygame.draw.circle(s, (255, 250, 230), (380, 110), 36)


def _art_rings(s: pygame.Surface, rng) -> None:
    cx, cy = int(rng.integers(180, 330)), int(rng.integers(180, 300))
    for k in range(18, 0, -1):
        col = (255, 60 + k * 10, 150 + k * 5) if k % 2 else (40, 10, 60)
        pygame.draw.circle(s, col, (cx, cy), k * 17, 0 if k == 1 else 6)
    for _ in range(60):
        pygame.draw.circle(s, (255, 230, 250), (int(rng.integers(0, SIZE)), int(rng.integers(0, SIZE))), 1)


ARTS = {"sun": _art_sun, "bolt": _art_bolt, "fractal": _art_fractal, "waves": _art_waves, "rings": _art_rings}


def style_for(key: str) -> tuple[str, int]:
    """Metinden deterministik (stil, tohum)."""
    h = zlib.crc32(key.encode("utf-8", "replace"))
    return STYLES[h % len(STYLES)], h & 0xFFFF


def draw_cover(title: str, artist: str, style: str | None = None, seed: int | None = None,
               text: bool = True) -> pygame.Surface:
    if style is None or seed is None:
        st, sd = style_for(f"{artist}\n{title}")
        style = style or st
        seed = sd if seed is None else seed
    rng = np.random.default_rng(seed)
    surf = _gradient(*PALETTES.get(style, PALETTES["sun"]))
    ARTS.get(style, _art_sun)(surf, rng)
    _noise(surf, rng, 6)
    if text:
        if not pygame.font.get_init():
            pygame.font.init()
        band = pygame.Surface((SIZE, 110), pygame.SRCALPHA)
        band.fill((0, 0, 0, 120))
        surf.blit(band, (0, SIZE - 118))
        _text(surf, title.upper(), 56, (255, 255, 255), (256, SIZE - 82))
        _text(surf, artist, 32, (220, 220, 220), (256, SIZE - 38))
    pygame.draw.rect(surf, (255, 255, 255), (0, 0, SIZE, SIZE), 6)
    return surf


def draw_album(path: str, title: str, artist: str, style: str, seed: int) -> None:
    """Demo sarki kapagi (yazili) -> PNG."""
    pygame.init()
    pygame.image.save(draw_cover(title, artist, style, seed, text=True), path)
