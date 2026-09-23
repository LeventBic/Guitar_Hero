"""Yazi tipleri, metin onbellegi ve prosedurel sprite'lar (gem, perde butonu, alev, parilti).

Her sey bir kez (veya ilk ihtiyacta) cizilip onbelleklenir; frame basina piksel islemi yapilmaz.
Gem'ler 4x supersample cizilip smoothscale ile kucultulur (kenar yumusatma).
"""
from __future__ import annotations

import math
import random
from collections import OrderedDict

import pygame

from ..config import FRET_COLORS, OPEN_COLOR, SP_COLOR

W, H = 1280, 720

# ---- palet: rock sahnesi (koyu komur + alev / kehribar + bronz metal). Adlar eski neon temadan kalma;
# anlamlari: PINK = birincil vurgu (alev), CYAN = ikincil vurgu (kehribar), PURPLE = cerceve (bronz).
BG_TOP = (10, 8, 8)
BG_BOTTOM = (28, 14, 9)
NEON_PINK = (240, 82, 34)
NEON_CYAN = (255, 190, 82)
NEON_PURPLE = (156, 122, 84)
NEON_ORANGE = (255, 150, 40)
TEXT = (238, 234, 226)
TEXT_DIM = (172, 164, 152)
METAL_HI = (86, 80, 76)
METAL_LO = (22, 20, 20)
GOLD = (255, 205, 60)
SP_BLUE = (70, 170, 255)
MISS_GREY = (95, 95, 105)

FONT_FAMILIES = {
    "ui": "bahnschrift,segoeui,verdana,arial",
    "title": "bahnschrift,impact,arialblack,arial",
    "mono": "consolas,couriernew,lucidaconsole",
}


def lerp(a, b, t):
    return a + (b - a) * t


def lerp_color(c1, c2, t):
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return (int(c1[0] + (c2[0] - c1[0]) * t), int(c1[1] + (c2[1] - c1[1]) * t),
            int(c1[2] + (c2[2] - c1[2]) * t))


def scale_color(c, k):
    return (max(0, min(255, int(c[0] * k))), max(0, min(255, int(c[1] * k))), max(0, min(255, int(c[2] * k))))


def lighten(c, t):
    return lerp_color(c, (255, 255, 255), t)


# --------------------------------------------------------------------------- yazi

class Fonts:
    def __init__(self):
        self._cache: dict[tuple, pygame.font.Font] = {}

    def get(self, size: int, family: str = "ui", bold: bool = False) -> pygame.font.Font:
        key = (size, family, bold)
        f = self._cache.get(key)
        if f is None:
            names = FONT_FAMILIES.get(family, family)
            try:
                f = pygame.font.SysFont(names, size, bold=bold)
            except Exception:
                f = None
            if f is None:
                f = pygame.font.Font(None, int(size * 1.3))
                f.set_bold(bold)
            self._cache[key] = f
        return f


class TextCache:
    """(metin, boyut, renk, aile, kalin) -> Surface; LRU."""

    def __init__(self, fonts: Fonts, limit: int = 700):
        self.fonts = fonts
        self.limit = limit
        self._c: OrderedDict = OrderedDict()

    def render(self, text: str, size: int, color=TEXT, family: str = "ui", bold: bool = False) -> pygame.Surface:
        key = (text, size, color, family, bold)
        s = self._c.get(key)
        if s is not None:
            self._c.move_to_end(key)
            return s
        s = self.fonts.get(size, family, bold).render(text, True, color).convert_alpha()
        self._c[key] = s
        if len(self._c) > self.limit:
            self._c.popitem(last=False)
        return s

    def glow(self, text: str, size: int, color, family: str = "title", bold: bool = True,
             glow_color=None, radius: int = 10, core=(255, 255, 255)) -> pygame.Surface:
        """Neon yazi: bulanik renkli hale + acik renkli cekirdek (onbellekli)."""
        key = ("__glow", text, size, color, family, bold, glow_color, radius, core)
        s = self._c.get(key)
        if s is not None:
            self._c.move_to_end(key)
            return s
        font = self.fonts.get(size, family, bold)
        gc = glow_color or color
        base = font.render(text, True, gc).convert_alpha()
        pad = radius * 2
        w, h = base.get_width() + pad * 2, base.get_height() + pad * 2
        halo = pygame.Surface((w, h), pygame.SRCALPHA)
        halo.blit(base, (pad, pad))
        blur = blur_surface(halo, radius)
        out = pygame.Surface((w, h), pygame.SRCALPHA)
        out.blit(blur, (0, 0))
        out.blit(blur, (0, 0))
        top = font.render(text, True, lerp_color(color, core, 0.55)).convert_alpha()
        out.blit(font.render(text, True, color).convert_alpha(), (pad, pad + 2))
        out.blit(top, (pad, pad))
        self._c[key] = out
        if len(self._c) > self.limit:
            self._c.popitem(last=False)
        return out


def blur_surface(surf: pygame.Surface, radius: int) -> pygame.Surface:
    """Hizli bulaniklik: pygame-ce gaussian_blur varsa onu, yoksa kucult-buyut."""
    try:
        return pygame.transform.gaussian_blur(surf, max(1, radius))
    except Exception:
        w, h = surf.get_size()
        k = max(2, radius // 2)
        small = pygame.transform.smoothscale(surf, (max(1, w // k), max(1, h // k)))
        return pygame.transform.smoothscale(small, (w, h))


# --------------------------------------------------------------------------- temel sekiller

def vertical_gradient(size, top, bottom, alpha=False) -> pygame.Surface:
    w, h = size
    surf = pygame.Surface((w, h), pygame.SRCALPHA if alpha else 0)
    col = pygame.Surface((1, h), pygame.SRCALPHA if alpha else 0)
    for y in range(h):
        t = y / max(1, h - 1)
        c = [int(top[i] + (bottom[i] - top[i]) * t) for i in range(len(top))]
        col.set_at((0, y), c)
    return pygame.transform.scale(col, (w, h)) if w > 1 else col


def radial_glow(radius: int, color, power: float = 2.0) -> pygame.Surface:
    """Toplamali (BLEND_ADD) kullanim icin siyah zeminde yumusak parlama (RGB)."""
    d = radius * 2
    surf = pygame.Surface((d, d))
    surf.fill((0, 0, 0))
    steps = max(8, radius)
    for i in range(steps, 0, -1):
        r = radius * i / steps
        k = (1.0 - i / steps) ** power
        # halka katmanlari ust uste: merkeze dogru artan parlaklik
        c = scale_color(color, 0.08 + 0.92 * k)
        pygame.draw.circle(surf, c, (radius, radius), max(1, int(r)))
    return surf


def ellipse_mask_fill(size, rect, top_color, bottom_color) -> pygame.Surface:
    """rect icinde dikey degrade dolgulu elips (SRCALPHA)."""
    w, h = size
    grad = vertical_gradient((rect[2], rect[3]), top_color + (255,), bottom_color + (255,), alpha=True)
    mask = pygame.Surface((rect[2], rect[3]), pygame.SRCALPHA)
    pygame.draw.ellipse(mask, (255, 255, 255, 255), (0, 0, rect[2], rect[3]))
    grad.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    out = pygame.Surface((w, h), pygame.SRCALPHA)
    out.blit(grad, (rect[0], rect[1]))
    return out


def star_points(cx, cy, r_out, r_in, squash=1.0, rot=-math.pi / 2):
    pts = []
    for i in range(10):
        r = r_out if i % 2 == 0 else r_in
        a = rot + i * math.pi / 5
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a) * squash))
    return pts


def polygon_gradient(size, pts, top_color, bottom_color, bbox) -> pygame.Surface:
    w, h = size
    x0, y0, bw, bh = bbox
    grad = vertical_gradient((bw, bh), top_color + (255,), bottom_color + (255,), alpha=True)
    mask = pygame.Surface((bw, bh), pygame.SRCALPHA)
    pygame.draw.polygon(mask, (255, 255, 255, 255), [(x - x0, y - y0) for x, y in pts])
    grad.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    out = pygame.Surface((w, h), pygame.SRCALPHA)
    out.blit(grad, (x0, y0))
    return out


# --------------------------------------------------------------------------- gem'ler

GEM_BASE_W = 128          # ana sprite genisligi (smoothscale kaynagi)
GEM_ASPECT = 0.46         # ust elips yukseklik / genislik
GEM_THICK = 0.15          # taban kalinligi / genislik
SS = 4                    # supersample


def _gem_body_colors(color, style):
    if style == "sp":
        return (200, 245, 255), (40, 140, 255)
    if style == "miss":
        return (120, 120, 128), (60, 60, 68)
    if style == "star":
        return (255, 255, 255), (120, 220, 255)
    return lighten(color, 0.35), scale_color(color, 0.62)


_PANEL_CACHE: "OrderedDict[tuple, pygame.Surface]" = OrderedDict()


def metal_panel(size, border=NEON_PURPLE, radius: int = 12, alpha: int = 232, bw: int = 2,
                screws: bool = True) -> pygame.Surface:
    """Koyu metal plaka: dikey degrade + ust parlama, ust isik cizgisi, renkli cerceve, vida basi."""
    w, h = int(size[0]), int(size[1])
    key = (w, h, tuple(border), radius, alpha, bw, screws)
    s = _PANEL_CACHE.get(key)
    if s is not None:
        _PANEL_CACHE.move_to_end(key)
        return s
    body = vertical_gradient((w, h), METAL_HI + (alpha,), METAL_LO + (alpha,), alpha=True)
    sheen = vertical_gradient((w, max(2, h // 3)), (255, 255, 255, 16), (255, 255, 255, 0), alpha=True)
    body.blit(sheen, (0, 0))                              # ust kisimda yumusak metal parlamasi
    mask = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), (0, 0, w, h), border_radius=radius)
    body.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    s = body
    pygame.draw.rect(s, (0, 0, 0, 200), (0, 0, w, h), bw + 2, border_radius=radius)            # dis golge
    pygame.draw.rect(s, tuple(border) + (235,), (1, 1, w - 2, h - 2), bw, border_radius=radius)
    pygame.draw.line(s, lighten(border, 0.55) + (170,), (radius, bw + 2), (w - radius, bw + 2))  # ust isik
    pygame.draw.line(s, (0, 0, 0, 120), (radius, h - bw - 3), (w - radius, h - bw - 3))
    if screws and w >= 160 and h >= 90:
        for cx, cy in ((10, 10), (w - 11, 10), (10, h - 11), (w - 11, h - 11)):
            pygame.draw.circle(s, (18, 16, 16, 255), (cx, cy), 5)
            pygame.draw.circle(s, (150, 144, 136, 255), (cx, cy), 4)
            pygame.draw.circle(s, (230, 226, 218, 255), (cx - 1, cy - 1), 2)
            pygame.draw.line(s, (40, 36, 34, 255), (cx - 3, cy + 1), (cx + 2, cy - 2), 1)
    _PANEL_CACHE[key] = s
    if len(_PANEL_CACHE) > 64:
        _PANEL_CACHE.popitem(last=False)
    return s


def draw_gem_master(color, kind: str, style: str) -> tuple[pygame.Surface, int]:
    """kind: strum | hopo | tap ; style: normal | star | sp | miss.
    Doner: (sprite GEM_BASE_W genisliginde, ust elips merkezinin y'si)."""
    bw = GEM_BASE_W * SS
    top_h = int(bw * GEM_ASPECT)
    thick = int(bw * GEM_THICK)
    pad = int(bw * 0.06)
    w = bw + pad * 2
    h = top_h + thick + pad * 2
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    cx = w // 2
    top_rect = pygame.Rect(pad, pad, bw, top_h)
    cy = top_rect.centery
    c_top, c_bot = _gem_body_colors(color, style)
    dark = (18, 18, 24)
    if style == "miss":
        dark = (40, 40, 46)

    if style == "star":
        _draw_star_gem(surf, cx, cy, bw, top_h, thick, color, kind)
    else:
        # taban silindiri (koyu) + ince metalik kenar
        base_rect = top_rect.move(0, thick)
        pygame.draw.ellipse(surf, dark, base_rect)
        pygame.draw.rect(surf, dark, (top_rect.x, cy, bw, thick))
        side_col = scale_color(c_bot, 0.45) if style != "miss" else (55, 55, 60)
        pygame.draw.ellipse(surf, side_col, base_rect.inflate(-bw * 0.04, -thick * 0.2))
        pygame.draw.ellipse(surf, dark, base_rect.move(0, -thick * 0.35).inflate(-bw * 0.02, 0))
        if kind == "tap":
            # TAP: renkli dis halka + koyu (siyah) govde + renkli kucuk merkez
            surf.blit(ellipse_mask_fill((w, h), top_rect, lighten(c_top, 0.25), c_bot), (0, 0))
            body = top_rect.inflate(-bw * 0.17, -top_h * 0.2)
            surf.blit(ellipse_mask_fill((w, h), body, (46, 46, 58), (6, 6, 10)), (0, 0))
            pygame.draw.ellipse(surf, (120, 120, 140) if style != "miss" else (80, 80, 85), body,
                                max(2, int(bw * 0.012)))
            dot = top_rect.inflate(-bw * 0.66, -top_h * 0.66)
            surf.blit(ellipse_mask_fill((w, h), dot, lighten(c_top, 0.4), c_top), (0, 0))
        else:
            # beyaz/gumus dis kenar
            rim_top = (250, 250, 255) if style != "miss" else (150, 150, 155)
            surf.blit(ellipse_mask_fill((w, h), top_rect, rim_top, (170, 170, 185)), (0, 0))
            body = top_rect.inflate(-bw * 0.075, -top_h * 0.09)
            surf.blit(ellipse_mask_fill((w, h), body, c_top, c_bot), (0, 0))
            if kind == "hopo":
                # parlak beyaz merkez (HOPO)
                inner = top_rect.inflate(-bw * 0.42, -top_h * 0.42)
                glow = inner.inflate(bw * 0.08, top_h * 0.08)
                pygame.draw.ellipse(surf, lighten(c_top, 0.55), glow)
                surf.blit(ellipse_mask_fill((w, h), inner, (255, 255, 255), (225, 230, 240)), (0, 0))
            else:
                inner = top_rect.inflate(-bw * 0.56, -top_h * 0.56)
                pygame.draw.ellipse(surf, (230, 230, 238) if style != "miss" else (140, 140, 145),
                                    inner.inflate(bw * 0.05, top_h * 0.05))
                surf.blit(ellipse_mask_fill((w, h), inner, (22, 22, 30), (8, 8, 12)), (0, 0))
                cap = inner.inflate(-inner.w * 0.55, -inner.h * 0.55).move(0, -inner.h * 0.05)
                pygame.draw.ellipse(surf, (90, 90, 105) if style != "miss" else (70, 70, 75), cap)
            # parlama (ust-sol)
            if style != "miss":
                hl = pygame.Surface((w, h), pygame.SRCALPHA)
                hr = pygame.Rect(0, 0, int(bw * 0.34), int(top_h * 0.2))
                hr.center = (cx - int(bw * 0.2), top_rect.y + int(top_h * 0.2))
                pygame.draw.ellipse(hl, (255, 255, 255, 110), hr)
                surf.blit(hl, (0, 0))
    out_w = GEM_BASE_W + int(GEM_BASE_W * 0.12)
    scale = out_w / w
    out = pygame.transform.smoothscale(surf, (out_w, max(1, int(h * scale))))
    return out, int(cy * scale)


def _draw_star_gem(surf, cx, cy, bw, top_h, thick, color, kind):
    r_out = bw * (0.6 if kind != "hopo" else 0.52)
    r_in = r_out * 0.48
    sq = GEM_ASPECT * 1.08
    pts = star_points(cx, cy, r_out, r_in, sq)
    base_pts = [(x, y + thick) for x, y in pts]
    # taban (koyu)
    pygame.draw.polygon(surf, (16, 20, 34), base_pts)
    side = [(x, y + thick * 0.5) for x, y in pts]
    pygame.draw.polygon(surf, (20, 60, 110), side)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    bbox = (int(min(xs)) - 2, int(min(ys)) - 2, int(max(xs) - min(xs)) + 5, int(max(ys) - min(ys)) + 5)
    w, h = surf.get_size()
    if kind == "tap":
        surf.blit(polygon_gradient((w, h), pts, (200, 245, 255), (60, 170, 255), bbox), (0, 0))
        inner = star_points(cx, cy, r_out * 0.66, r_in * 0.66, sq)
        pygame.draw.polygon(surf, (12, 16, 28), inner)
        pygame.draw.polygon(surf, color, inner, max(2, int(bw * 0.02)))
        return
    surf.blit(polygon_gradient((w, h), pts, (255, 255, 255), (110, 205, 255), bbox), (0, 0))
    pygame.draw.polygon(surf, (255, 255, 255), pts, max(2, int(bw * 0.012)))
    inner = star_points(cx, cy, r_out * 0.5, r_in * 0.5, sq)
    if kind == "hopo":
        pygame.draw.polygon(surf, (255, 255, 255), inner)
    else:
        pygame.draw.polygon(surf, lighten(color, 0.15), inner)
        pygame.draw.polygon(surf, (255, 255, 255), inner, max(2, int(bw * 0.012)))


def draw_open_master(kind: str, style: str) -> tuple[pygame.Surface, int]:
    """Acik nota: otoban boyunca mor cubuk. Genislik 512 (smoothscale kaynagi)."""
    bw = 512 * 2
    bh = int(bw * 0.055)
    thick = int(bh * 0.55)
    pad = 6
    w, h = bw + pad * 2, bh + thick + pad * 2
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    if style == "star" or style == "sp":
        c_top, c_bot = (235, 250, 255), (70, 170, 255)
    elif style == "miss":
        c_top, c_bot = (120, 120, 128), (60, 60, 68)
    else:
        c_top, c_bot = lighten(OPEN_COLOR, 0.35), scale_color(OPEN_COLOR, 0.55)
    r = pygame.Rect(pad, pad, bw, bh)
    pygame.draw.rect(surf, (16, 12, 24), r.move(0, thick), border_radius=bh // 2)
    pygame.draw.rect(surf, (16, 12, 24), (r.x, r.centery, bw, thick))
    grad = vertical_gradient((bw, bh), (255, 255, 255, 255), (170, 170, 190, 255), alpha=True)
    mask = pygame.Surface((bw, bh), pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), (0, 0, bw, bh), border_radius=bh // 2)
    grad.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    surf.blit(grad, r.topleft)
    inner = r.inflate(-bh * 0.3, -bh * 0.3)
    g2 = vertical_gradient(inner.size, c_top + (255,), c_bot + (255,), alpha=True)
    m2 = pygame.Surface(inner.size, pygame.SRCALPHA)
    pygame.draw.rect(m2, (255, 255, 255, 255), (0, 0, *inner.size), border_radius=inner.h // 2)
    g2.blit(m2, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    surf.blit(g2, inner.topleft)
    if kind == "hopo" and style != "miss":
        line = inner.inflate(-inner.w * 0.1, -inner.h * 0.55)
        pygame.draw.rect(surf, (255, 255, 255), line, border_radius=line.h // 2)
    elif kind == "tap":
        line = inner.inflate(-inner.w * 0.08, -inner.h * 0.45)
        pygame.draw.rect(surf, (20, 14, 30), line, border_radius=line.h // 2)
    out_w = 512
    k = out_w / w
    out = pygame.transform.smoothscale(surf, (out_w, max(2, int(h * k))))
    return out, int((pad + bh / 2) * k)


class GemCache:
    """(renk indeksi, kind, style, piksel genisligi) -> (sprite, anchor_y)."""

    def __init__(self):
        self._master: dict[tuple, tuple[pygame.Surface, int]] = {}
        self._scaled: dict[tuple, tuple[pygame.Surface, int]] = {}

    def master(self, fret: int, kind: str, style: str):
        key = (fret, kind, style)
        m = self._master.get(key)
        if m is None:
            if fret < 0:
                m = draw_open_master(kind, style)
            else:
                m = draw_gem_master(FRET_COLORS[fret], kind, style)
            m = (m[0].convert_alpha(), m[1])
            self._master[key] = m
        return m

    def get(self, fret: int, kind: str, style: str, width: int):
        width = max(4, int(width) & ~1)
        key = (fret, kind, style, width)
        s = self._scaled.get(key)
        if s is None:
            m, ay = self.master(fret, kind, style)
            k = width / m.get_width()
            img = pygame.transform.smoothscale(m, (width, max(2, int(m.get_height() * k))))
            s = (img, int(ay * k))
            self._scaled[key] = s
        return s

    def warm(self, widths, frets=range(5), kinds=("strum", "hopo", "tap"), styles=("normal", "star", "sp")):
        for f in frets:
            for kd in kinds:
                for st in styles:
                    self.master(f, kd, st)


# --------------------------------------------------------------------------- perde butonlari

def draw_fret_button(color, pressed: bool, width: int) -> tuple[pygame.Surface, int]:
    bw = width * SS
    top_h = int(bw * 0.5)
    thick = int(bw * 0.2)
    pad = int(bw * 0.05)
    w, h = bw + pad * 2, top_h + thick + pad * 2
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    top = pygame.Rect(pad, pad, bw, top_h)
    press_off = int(thick * 0.45) if pressed else 0
    top = top.move(0, press_off)
    base = pygame.Rect(pad, pad + thick, bw, top_h)
    pygame.draw.ellipse(surf, (10, 10, 14), base)
    pygame.draw.rect(surf, (10, 10, 14), (pad, pad + top_h // 2, bw, thick))
    pygame.draw.ellipse(surf, (60, 60, 72), base.inflate(-bw * 0.06, -top_h * 0.1))
    pygame.draw.ellipse(surf, (10, 10, 14), base.move(0, -thick * 0.3).inflate(-bw * 0.03, 0))
    # dis metal halka
    surf.blit(ellipse_mask_fill((w, h), top, (200, 200, 212), (90, 90, 104)), (0, 0))
    ring = top.inflate(-bw * 0.07, -top_h * 0.08)
    if pressed:
        surf.blit(ellipse_mask_fill((w, h), ring, lighten(color, 0.55), color), (0, 0))
        inner = top.inflate(-bw * 0.36, -top_h * 0.36)
        surf.blit(ellipse_mask_fill((w, h), inner, (255, 255, 255), lighten(color, 0.4)), (0, 0))
    else:
        surf.blit(ellipse_mask_fill((w, h), ring, lighten(color, 0.1), scale_color(color, 0.55)), (0, 0))
        inner = top.inflate(-bw * 0.28, -top_h * 0.28)
        pygame.draw.ellipse(surf, (16, 16, 22), inner)
        in2 = inner.inflate(-bw * 0.05, -top_h * 0.05)
        surf.blit(ellipse_mask_fill((w, h), in2, (60, 60, 74), (22, 22, 30)), (0, 0))
        spot = in2.inflate(-in2.w * 0.5, -in2.h * 0.5).move(0, -in2.h * 0.12)
        pygame.draw.ellipse(surf, (90, 90, 106), spot)
    out_w = width + int(width * 0.1)
    k = out_w / w
    out = pygame.transform.smoothscale(surf, (out_w, int(h * k))).convert_alpha()
    return out, int((pad + top_h / 2) * k)


# --------------------------------------------------------------------------- alev / parilti

def make_flame_frames(color, n: int = 10, w: int = 110, h: int = 170, seed: int = 0) -> list[pygame.Surface]:
    """Toplamali alev kareleri (RGB, siyah zemin). Alt: beyaz-sari cekirdek, ust: renkli dil."""
    rng = random.Random(seed)
    frames = []
    glow_cache: dict[tuple, pygame.Surface] = {}

    def blob(r, c):
        key = (r, c)
        g = glow_cache.get(key)
        if g is None:
            g = radial_glow(max(2, r), c, 1.6)
            glow_cache[key] = g
        return g

    tongues = [(rng.uniform(-0.25, 0.25), rng.uniform(0.6, 1.0), rng.uniform(0, 6.28)) for _ in range(5)]
    for f in range(n):
        ph = f / n * 2 * math.pi
        surf = pygame.Surface((w, h))
        surf.fill((0, 0, 0))
        for (xo, hk, p0) in tongues:
            steps = 16
            for j in range(steps):
                t = j / steps
                y = h - 18 - t * (h - 30) * hk
                x = w / 2 + xo * w * t + math.sin(ph + p0 + t * 5) * w * 0.08 * t
                r = int((1 - t) ** 0.8 * w * 0.2 + 2)
                if t < 0.25:
                    c = lerp_color((255, 255, 230), (255, 200, 90), t / 0.25)
                elif t < 0.6:
                    c = lerp_color((255, 200, 90), lerp_color(NEON_ORANGE, color, 0.5), (t - 0.25) / 0.35)
                else:
                    c = lerp_color(lerp_color(NEON_ORANGE, color, 0.5), scale_color(color, 0.5), (t - 0.6) / 0.4)
                c = scale_color(c, 0.34 * (1 - t * 0.55))
                g = blob(r, c)
                surf.blit(g, (x - r, y - r), special_flags=pygame.BLEND_ADD)
        frames.append(surf.convert())
    return frames


def make_ring_glow(color, w: int, h: int) -> pygame.Surface:
    """Vurus aninda perde butonunda patlayan elips halka (RGB toplamali)."""
    surf = pygame.Surface((w, h))
    surf.fill((0, 0, 0))
    for i in range(10):
        k = i / 10
        c = scale_color(lighten(color, 0.5), 0.12 + 0.1 * k)
        r = pygame.Rect(0, 0, int(w * (1 - k * 0.5)), int(h * (1 - k * 0.5)))
        r.center = (w // 2, h // 2)
        pygame.draw.ellipse(surf, c, r, max(2, int(w * 0.04)))
    pygame.draw.ellipse(surf, scale_color(lighten(color, 0.7), 0.5), (w * 0.2, h * 0.2, w * 0.6, h * 0.6))
    return blur_surface(surf, 3).convert()


class SparkSprites:
    def __init__(self):
        self._c: dict[tuple, pygame.Surface] = {}

    def get(self, r: int, color) -> pygame.Surface:
        key = (r, color)
        s = self._c.get(key)
        if s is None:
            s = radial_glow(r, color, 1.8).convert()
            self._c[key] = s
        return s


class Assets:
    """Paylasilan kaynaklar (App basina bir kez)."""

    def __init__(self):
        self.fonts = Fonts()
        self.text = TextCache(self.fonts)
        self.gems = GemCache()
        self.sparks = SparkSprites()
        self._flames: dict[int, list[pygame.Surface]] = {}
        self._rings: dict[int, pygame.Surface] = {}
        self._buttons: dict[tuple, tuple[pygame.Surface, int]] = {}
        self._album: OrderedDict = OrderedDict()

    def flames(self, fret: int) -> list[pygame.Surface]:
        f = self._flames.get(fret)
        if f is None:
            col = SP_COLOR if fret == 5 else (OPEN_COLOR if fret < 0 else FRET_COLORS[fret])
            f = make_flame_frames(col, seed=fret + 11)
            self._flames[fret] = f
        return f

    def ring(self, fret: int) -> pygame.Surface:
        r = self._rings.get(fret)
        if r is None:
            col = OPEN_COLOR if fret < 0 else FRET_COLORS[fret]
            r = make_ring_glow(col, 150, 80)
            self._rings[fret] = r
        return r

    def button(self, fret: int, pressed: bool, width: int):
        key = (fret, pressed, width)
        b = self._buttons.get(key)
        if b is None:
            b = draw_fret_button(FRET_COLORS[fret], pressed, width)
            self._buttons[key] = b
        return b

    def logo(self, width: int) -> pygame.Surface | None:
        """assets/logo.png (saydam), istenen genislige olceklenmis; yoksa None."""
        key = ("__logo__", width)
        if key in self._album:
            return self._album[key]
        img = None
        try:
            import os

            from ..config import resource_root
            raw = pygame.image.load(os.path.join(resource_root(), "assets", "logo.png")).convert_alpha()
            img = pygame.transform.smoothscale(raw, (width, round(raw.get_height() * width / raw.get_width())))
        except Exception:
            img = None
        self._album[key] = img
        return img

    def album(self, path: str, size: int) -> pygame.Surface | None:
        key = (path, size)
        if key in self._album:
            self._album.move_to_end(key)
            return self._album[key]
        img = None
        if path:
            try:
                raw = pygame.image.load(path)
                raw = raw.convert_alpha() if raw.get_alpha() else raw.convert()
                img = pygame.transform.smoothscale(raw, (size, size))
            except Exception:
                img = None
        self._album[key] = img
        if len(self._album) > 24:
            self._album.popitem(last=False)
        return img
