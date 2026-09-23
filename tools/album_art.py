"""Procedural 512x512 album covers drawn with pygame (headless)."""
from __future__ import annotations

import math
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import numpy as np
import pygame

SIZE = 512


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


def draw_album(path: str, title: str, artist: str, style: str, seed: int) -> None:
    pygame.init()
    rng = np.random.default_rng(seed)
    palettes = {"sun": ((40, 20, 90), (250, 120, 90)), "bolt": ((20, 20, 30), (120, 20, 30)),
                "fractal": ((5, 5, 20), (40, 10, 60))}
    surf = _gradient(*palettes.get(style, palettes["sun"]))
    {"sun": _art_sun, "bolt": _art_bolt, "fractal": _art_fractal}[style](surf, rng)
    _noise(surf, rng, 6)
    band = pygame.Surface((SIZE, 110), pygame.SRCALPHA)
    band.fill((0, 0, 0, 120))
    surf.blit(band, (0, SIZE - 118))
    _text(surf, title.upper(), 56, (255, 255, 255), (256, SIZE - 82))
    _text(surf, artist, 32, (220, 220, 220), (256, SIZE - 38))
    pygame.draw.rect(surf, (255, 255, 255), (0, 0, SIZE, SIZE), 6)
    pygame.image.save(surf, path)
