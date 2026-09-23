"""Sonuc ekrani: skor, animasyonlu yildizlar (0-6, 6 = altin), isabet yuzdesi, max combo, overstrum,
SP cumleleri, 10 ms'lik erken/gec histogrami + medyan."""
from __future__ import annotations

import math
import statistics

import pygame

from ..render.assets import GOLD, NEON_CYAN, NEON_PINK, TEXT, TEXT_DIM, W, lighten
from ..render.ui import MenuList, SynthBackground, draw_hints, draw_panel, draw_star
from .base import Scene

BUCKET = 0.010
HIST_RANGE = 0.070


class ResultsScene(Scene):
    def __init__(self, app, stats: dict):
        super().__init__(app)
        self.s = stats
        self.bg = SynthBackground()
        self.menu = MenuList(["CONTINUE", "RETRY"], 1040, 600, spacing=54, size=30)
        self.stars_full = 0 if stats["failed"] else int(math.floor(stats["stars"] + 1e-9))
        self.star_frac = 0.0 if stats["failed"] else stats["stars"] - self.stars_full
        self.shown = 0
        self.cheered = False
        offs = stats.get("offsets") or []
        nb = int(round(2 * HIST_RANGE / BUCKET))
        self.hist = [0] * nb
        for o in offs:
            k = int(math.floor((o + HIST_RANGE) / BUCKET))
            self.hist[max(0, min(nb - 1, k))] += 1
        self.median = statistics.median(offs) if offs else 0.0
        self.mean = statistics.fmean(offs) if offs else 0.0

    def enter(self) -> None:
        if self.s["failed"]:
            return

    def on_menu(self, action: str) -> None:
        if self.t < 0.4:
            return
        if action in ("UP", "LEFT"):
            self.menu.move(-1)
            self.sfx("menu_move")
        elif action in ("DOWN", "RIGHT"):
            self.menu.move(1)
            self.sfx("menu_move")
        elif action == "CONFIRM":
            self.sfx("menu_select")
            if self.menu.index == 0:
                self._to_songlist()
            else:
                from .gameplay import GameplayScene
                info = self.s["info"]
                try:
                    self.app.replace(GameplayScene(self.app, info, self.s["difficulty"], autoplay=self.s["autoplay"]))
                except Exception:
                    self._to_songlist()
        elif action == "BACK":
            self.sfx("menu_back")
            self._to_songlist()

    def _to_songlist(self) -> None:
        self.app.back_to_songlist()

    def update(self, dt: float) -> None:
        super().update(dt)
        self.bg.update(dt)
        self.menu.update(dt)
        n = 0 if self.t < 0.9 else min(6, int((self.t - 0.9) / 0.28) + 1)
        n = min(n, self.stars_full)
        if n > self.shown:
            self.shown = n
            self.sfx("sp_phrase_complete" if n < 6 else "sp_activate", 0.7)
        if not self.cheered and self.t > 0.9 + 0.28 * max(1, self.stars_full) and not self.s["failed"]:
            self.cheered = True
            if self.stars_full >= 4:
                self.sfx("crowd_cheer", 0.9)

    def draw(self, surf: pygame.Surface) -> None:
        s = self.s
        a = self.assets
        tc = a.text
        self.bg.draw(surf, 0.3)
        shade = pygame.Surface((W, 720), pygame.SRCALPHA)
        shade.fill((4, 2, 12, 140))
        surf.blit(shade, (0, 0))
        head = "SONG FAILED" if s["failed"] else ("FULL COMBO!" if s["fc"] else "SONG COMPLETE")
        col = (255, 90, 100) if s["failed"] else (GOLD if s["fc"] else (255, 120, 210))
        img = tc.glow(head, 58, col, glow_color=col)
        surf.blit(img, (W // 2 - img.get_width() // 2, 18))
        sub = tc.render(f"{s['title']}  -  {s['artist']}   [{s['difficulty'].upper()}{'  BOT' if s['autoplay'] else ''}]",
                        22, TEXT_DIM)
        surf.blit(sub, (W // 2 - sub.get_width() // 2, 100))

        # sol panel: skor + yildizlar + istatistik
        draw_panel(surf, (60, 140, 560, 520), border=NEON_PINK)
        k = min(1.0, max(0.0, (self.t - 0.2) / 1.2))
        k = 1 - (1 - k) ** 3
        score = int(s["score"] * k)
        sc = tc.render(f"{score:,}", 64, TEXT, "title", True)
        surf.blit(sc, (340 - sc.get_width() // 2, 160))
        gold = self.shown >= 6
        n_slots = 5
        for i in range(n_slots):
            cx = 340 + (i - 2) * 76
            cy = 280
            filled = i < self.shown
            if filled:
                age = self.t - (0.9 + i * 0.28)
                sc_k = 1.0 + 0.5 * max(0.0, 1 - age / 0.2) if age < 0.2 else 1.0
                colr = GOLD if not gold else (255, 235, 120)
                draw_star(surf, (cx, cy), int(30 * sc_k), True, color=colr if not gold else (255, 215, 0))
            else:
                draw_star(surf, (cx, cy), 30, False)
                if i == self.shown and self.star_frac > 0 and self.t > 0.9 + self.shown * 0.28:
                    # kismi yildiz ilerlemesi
                    w = int(60 * self.star_frac)
                    pygame.draw.rect(surf, (120, 100, 40), (cx - 30, cy + 38, w, 4))
        if gold:
            g = tc.glow("GOLD STARS!", 30, (255, 220, 60), glow_color=(255, 180, 0))
            surf.blit(g, (340 - g.get_width() // 2, 322))
        total = max(1, s["total"])
        pct = 100.0 * s["notes_hit"] / total
        rows = [
            ("Notes hit", f"{s['notes_hit']} / {s['total']}   ({pct:.1f}%)"),
            ("Max combo", f"{s['max_combo']}"),
            ("Overstrums", f"{s['overstrums']}"),
            ("Star Power phrases", f"{s['sp_done']} / {s['sp_total']}"),
            ("Stars", f"{s['stars']:.2f}" if not s["failed"] else "-"),
        ]
        y = 402
        for lab, val in rows:
            l = tc.render(lab, 24, TEXT_DIM)
            v = tc.render(val, 26, TEXT, "ui", True)
            surf.blit(l, (100, y))
            surf.blit(v, (580 - v.get_width(), y))
            pygame.draw.line(surf, (50, 44, 80), (100, y + 36), (580, y + 36), 1)
            y += 49

        # sag panel: histogram
        draw_panel(surf, (660, 140, 560, 380), border=NEON_CYAN)
        t = tc.render("TIMING", 22, NEON_CYAN, "ui", True)
        surf.blit(t, (690, 156))
        md = tc.render(f"median {self.median * 1000:+.1f} ms   mean {self.mean * 1000:+.1f} ms", 18, TEXT_DIM)
        surf.blit(md, (1190 - md.get_width(), 160))
        hx, hy, hw, hh = 700, 200, 480, 240
        mx = max(1, max(self.hist))
        nb = len(self.hist)
        bw = hw / nb
        for i, c in enumerate(self.hist):
            center = -HIST_RANGE + (i + 0.5) * BUCKET
            ac = abs(center) / HIST_RANGE
            colr = (80, 230, 110) if ac < 0.35 else (245, 205, 40) if ac < 0.7 else (240, 90, 70)
            h = int(hh * c / mx * min(1.0, self.t / 1.0))
            r = pygame.Rect(int(hx + i * bw) + 2, hy + hh - h, int(bw) - 4, h)
            if h > 0:
                pygame.draw.rect(surf, colr, r, border_radius=3)
                pygame.draw.rect(surf, lighten(colr, 0.4), (r.x, r.y, r.w, 3), border_radius=2)
        pygame.draw.line(surf, (120, 116, 160), (hx, hy + hh), (hx + hw, hy + hh), 2)
        zero_x = hx + hw / 2
        pygame.draw.line(surf, (200, 200, 220), (zero_x, hy - 4), (zero_x, hy + hh + 6), 1)
        med_x = hx + hw * (self.median + HIST_RANGE) / (2 * HIST_RANGE)
        med_x = max(hx, min(hx + hw, med_x))
        pygame.draw.line(surf, NEON_PINK, (med_x, hy - 8), (med_x, hy + hh + 6), 3)
        for ms in (-70, -35, 0, 35, 70):
            x = hx + hw * (ms / 1000 + HIST_RANGE) / (2 * HIST_RANGE)
            lab = tc.render(f"{ms:+d}" if ms else "0", 14, TEXT_DIM)
            surf.blit(lab, (x - lab.get_width() // 2, hy + hh + 10))
        e = tc.render("EARLY", 14, TEXT_DIM, "ui", True)
        l = tc.render("LATE", 14, TEXT_DIM, "ui", True)
        surf.blit(e, (hx, hy + hh + 30))
        surf.blit(l, (hx + hw - l.get_width(), hy + hh + 30))
        self.menu.draw(surf, a, 300)
        draw_hints(surf, a, [("Up/Down", "Select"), ("Enter", "Confirm"), ("Esc", "Song list")])
