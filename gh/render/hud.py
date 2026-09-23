"""Oyun ici HUD: skor, carpan kuresi + 10'lu combo halkasi, seri, Star Power bari, rock metre, ilerleme,
bolum/seri/solo acilir yazilari, erken/gec gostergesi ve F3 debug katmani."""
from __future__ import annotations

import math

import pygame

from ..i18n import t
from .assets import (NEON_CYAN, NEON_ORANGE, NEON_PINK, SP_BLUE, TEXT, TEXT_DIM, W, lerp_color,
                     lighten, radial_glow, scale_color)

MULT_COLORS = {1: (205, 205, 220), 2: (255, 165, 40), 3: (80, 230, 110), 4: (190, 100, 255)}
SP_MULT_COLOR = (90, 220, 255)
SS = 4

ORB_C = (236, 640)
ORB_R = 44
GAUGE_C = (1112, 628)
GAUGE_R = 96


def _rounded_panel(size, radius=16, fill=(12, 10, 26, 205), border=(120, 90, 220), bw=2) -> pygame.Surface:
    w, h = size
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.rect(s, fill, (0, 0, w, h), border_radius=radius)
    pygame.draw.rect(s, border + (230,), (0, 0, w, h), bw, border_radius=radius)
    hl = pygame.Surface((w, h // 2), pygame.SRCALPHA)
    pygame.draw.rect(hl, (255, 255, 255, 14), (0, 0, w, h // 2), border_top_left_radius=radius,
                     border_top_right_radius=radius)
    s.blit(hl, (0, 0))
    return s


def _arc_poly(cx, cy, r0, r1, a0, a1, steps=16):
    pts = []
    for k in range(steps + 1):
        a = a0 + (a1 - a0) * k / steps
        pts.append((cx + r1 * math.cos(a), cy + r1 * math.sin(a)))
    for k in range(steps, -1, -1):
        a = a0 + (a1 - a0) * k / steps
        pts.append((cx + r0 * math.cos(a), cy + r0 * math.sin(a)))
    return pts


class Popup:
    __slots__ = ("surf", "t0", "dur", "y", "kind")

    def __init__(self, surf, t0, dur, y, kind="pop"):
        self.surf, self.t0, self.dur, self.y, self.kind = surf, t0, dur, y, kind


class HUD:
    def __init__(self, assets, settings):
        self.a = assets
        self.settings = settings
        self.popups: list[Popup] = []
        self.timing_marks: list[tuple[float, float]] = []   # (gercek zaman, offset)
        self.mult_pulse = -10.0
        self.sp_ready_since = -10.0
        self.solo: dict | None = None
        self.danger = 0.0
        self.clock = 0.0
        self._build()

    # ------------------------------------------------------------------ onceden cizim
    def _build(self) -> None:
        self.panel_left = _rounded_panel((300, 196), border=(255, 60, 170))
        self.panel_right = _rounded_panel((300, 196), border=(60, 200, 255))
        # carpan halkasi segmentleri
        self.seg = {}
        colors = dict(MULT_COLORS)
        colors["sp"] = SP_MULT_COLOR
        colors["off"] = (38, 36, 56)
        big = (ORB_R + 20) * 2 * SS
        for key, col in colors.items():
            segs = []
            for i in range(10):
                s = pygame.Surface((big, big), pygame.SRCALPHA)
                c = big // 2
                a0 = -math.pi / 2 + i * (2 * math.pi / 10) + 0.05
                a1 = a0 + 2 * math.pi / 10 - 0.1
                pygame.draw.polygon(s, col, _arc_poly(c, c, (ORB_R + 5) * SS, (ORB_R + 17) * SS, a0, a1))
                if key != "off":
                    pygame.draw.polygon(s, lighten(col, 0.5),
                                        _arc_poly(c, c, (ORB_R + 12) * SS, (ORB_R + 16) * SS, a0, a1))
                segs.append(pygame.transform.smoothscale(s, (big // SS, big // SS)).convert_alpha())
            self.seg[key] = segs
        # kure
        self.orbs = {}
        for key, col in list(MULT_COLORS.items()) + [("sp", SP_MULT_COLOR)]:
            d = ORB_R * 2 * SS
            s = pygame.Surface((d, d), pygame.SRCALPHA)
            for k in range(40, 0, -1):
                r = d / 2 * k / 40
                t = 1 - k / 40
                c2 = lerp_color(scale_color(col, 0.18), lighten(col, 0.1), t ** 1.4)
                pygame.draw.circle(s, c2, (d // 2, d // 2 - int((1 - k / 40) * d * 0.08)), int(r))
            pygame.draw.circle(s, lighten(col, 0.4), (d // 2, d // 2), d // 2, 3 * SS)
            self.orbs[key] = pygame.transform.smoothscale(s, (ORB_R * 2, ORB_R * 2)).convert_alpha()
        self.orb_glow = {k: radial_glow(ORB_R + 30, scale_color(c, 0.6), 2.0).convert()
                         for k, c in list(MULT_COLORS.items()) + [("sp", SP_MULT_COLOR)]}
        # rock metre
        big = (GAUGE_R + 14) * 2 * SS
        g = pygame.Surface((big, big // 2 + 20 * SS), pygame.SRCALPHA)
        c = (big // 2, big // 2)
        zones = [((225, 40, 40), 0.0, 1 / 3), ((245, 205, 40), 1 / 3, 2 / 3), ((50, 215, 80), 2 / 3, 1.0)]
        pygame.draw.circle(g, (14, 12, 26), c, (GAUGE_R + 12) * SS)
        for col, f0, f1 in zones:
            a0 = math.pi + f0 * math.pi + 0.02
            a1 = math.pi + f1 * math.pi - 0.02
            pygame.draw.polygon(g, scale_color(col, 0.75), _arc_poly(c[0], c[1], (GAUGE_R - 26) * SS, GAUGE_R * SS, a0, a1, 24))
            pygame.draw.polygon(g, lighten(col, 0.3), _arc_poly(c[0], c[1], (GAUGE_R - 6) * SS, GAUGE_R * SS, a0, a1, 24))
        for k in range(13):
            a = math.pi + k / 12 * math.pi
            r0, r1 = (GAUGE_R - 34) * SS, (GAUGE_R - 28) * SS
            pygame.draw.line(g, (160, 160, 190), (c[0] + r0 * math.cos(a), c[1] + r0 * math.sin(a)),
                             (c[0] + r1 * math.cos(a), c[1] + r1 * math.sin(a)), SS * 2)
        pygame.draw.rect(g, (0, 0, 0, 0), (0, big // 2 + 2 * SS, big, 40 * SS))
        self.gauge = pygame.transform.smoothscale(g, (g.get_width() // SS, g.get_height() // SS)).convert_alpha()
        red = pygame.Surface((big, big // 2), pygame.SRCALPHA)
        pygame.draw.polygon(red, (255, 70, 70), _arc_poly(c[0], c[1], (GAUGE_R - 26) * SS, GAUGE_R * SS,
                                                          math.pi + 0.02, math.pi * 4 / 3 - 0.02, 24))
        self.gauge_red = pygame.transform.smoothscale(red, (big // SS, big // 2 // SS)).convert_alpha()
        # tehlike vinyeti (toplamali)
        vg = pygame.Surface((W, 720))
        vg.fill((0, 0, 0))
        for k in range(30):
            t = k / 30
            col = scale_color((200, 20, 30), 0.03 + 0.05 * (1 - t))
            pygame.draw.rect(vg, col, (int(t * 90), int(t * 60), W - int(t * 180), 720 - int(t * 120)), 6)
        self.vignette = vg.convert()
        self.sp_glow = radial_glow(40, (40, 150, 255), 2.0).convert()

    # ------------------------------------------------------------------ olaylar
    def popup(self, text: str, size: int, color, dur: float = 1.6, y: int = 300, kind: str = "pop"):
        surf = self.a.text.glow(text, size, color)
        t = self.clock
        self.popups = [p for p in self.popups if p.y != y]
        self.popups.append(Popup(surf, t, dur, y, kind))

    def banner(self, text: str, dur: float = 2.4, y: int = 200) -> None:
        """Bolum adi: koyu serit uzerinde neon yazi (kayarak gelir)."""
        txt = self.a.text.glow(text, 36, (170, 240, 255), "title", True, glow_color=NEON_CYAN, radius=8)
        w = max(360, txt.get_width() + 80)
        h = txt.get_height() + 4
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        for x in range(w):
            k = 1 - abs(x / w * 2 - 1)
            a = int(135 * min(1.0, k * 3))
            pygame.draw.line(s, (6, 4, 18, a), (x, 8), (x, h - 8))
        pygame.draw.line(s, NEON_CYAN + (200,), (w * 0.15, 8), (w * 0.85, 8), 2)
        pygame.draw.line(s, NEON_CYAN + (200,), (w * 0.15, h - 9), (w * 0.85, h - 9), 2)
        s.blit(txt, (w // 2 - txt.get_width() // 2, 2))
        self.popups = [p for p in self.popups if p.y != y]
        self.popups.append(Popup(s, self.clock, dur, y, "slide"))

    def on_hit_offset(self, offset: float) -> None:
        self.timing_marks.append((self.clock, offset))
        if len(self.timing_marks) > 24:
            del self.timing_marks[:len(self.timing_marks) - 24]

    def on_mult(self) -> None:
        self.mult_pulse = self.clock

    # ------------------------------------------------------------------ cizim
    def update(self, dt: float) -> None:
        self.clock += dt

    def draw(self, surf: pygame.Surface, st) -> None:
        eng = st.engine
        a = self.a
        now = self.clock
        # tehlike
        if eng.rock_meter < 1 / 3 and not eng.failed and st.rock_active:
            k = 0.5 + 0.5 * math.sin(now * 7)
            if k > 0.25:
                surf.blit(self.vignette, (0, 0), special_flags=pygame.BLEND_ADD)
        self._draw_score(surf, st)
        self._draw_right(surf, st)
        self._draw_progress(surf, st)
        self._draw_timing(surf, st)
        self._draw_solo(surf, st)
        # acilir yazilar
        keep = []
        for p in self.popups:
            age = self.clock - p.t0
            if age > p.dur or age < 0:
                if age <= p.dur:
                    keep.append(p)
                continue
            keep.append(p)
            k = age / p.dur
            img = p.surf
            if p.kind == "pop":
                sc = 1.0 + 0.35 * max(0.0, 1 - age / 0.12) if age < 0.12 else 1.0
                if age < 0.12:
                    sc = 0.6 + 0.4 * (age / 0.12) + 0.15 * math.sin(age / 0.12 * math.pi)
                if sc != 1.0:
                    img = pygame.transform.smoothscale(img, (max(1, int(img.get_width() * sc)),
                                                             max(1, int(img.get_height() * sc))))
                alpha = 255 if k < 0.75 else int(255 * (1 - (k - 0.75) / 0.25))
                x = W // 2 - img.get_width() // 2
                y = p.y - img.get_height() // 2
            else:  # slide: bolum adi
                slide = min(1.0, age / 0.25)
                alpha = int(255 * min(1.0, age / 0.2)) if k < 0.8 else int(255 * (1 - (k - 0.8) / 0.2))
                x = W // 2 - img.get_width() // 2 + int((1 - slide) ** 2 * 120)
                y = p.y - img.get_height() // 2
            if alpha < 255:
                img = img.copy()
                img.set_alpha(max(0, alpha))
            surf.blit(img, (x, y))
        self.popups = keep
        if st.show_debug:
            self._draw_debug(surf, st)

    def _draw_score(self, surf, st) -> None:
        eng = st.engine
        a = self.a
        surf.blit(self.panel_left, (18, 512))
        mult = eng.multiplier
        base = eng.base_multiplier
        key = "sp" if eng.sp_active else min(4, base)
        col = SP_MULT_COLOR if eng.sp_active else MULT_COLORS[min(4, base)]
        # skor
        score_s = a.text.render(f"{st.display_score:,}", 44, TEXT, "title", True)
        surf.blit(score_s, (302 - score_s.get_width(), 516))
        # kure
        pulse = max(0.0, 1 - (self.clock - self.mult_pulse) / 0.25)
        if mult > 1 or eng.sp_active:
            gl = self.orb_glow[key]
            surf.blit(gl, (ORB_C[0] - gl.get_width() // 2, ORB_C[1] - gl.get_height() // 2), special_flags=pygame.BLEND_ADD)
        segs_on = 10 if base >= 4 else eng.combo % 10
        for i in range(10):
            img = self.seg[key if i < segs_on else "off"][i]
            surf.blit(img, (ORB_C[0] - img.get_width() // 2, ORB_C[1] - img.get_height() // 2))
        orb = self.orbs[key]
        if pulse > 0:
            sz = int(ORB_R * 2 * (1 + 0.18 * pulse))
            orb = pygame.transform.smoothscale(orb, (sz, sz))
        surf.blit(orb, (ORB_C[0] - orb.get_width() // 2, ORB_C[1] - orb.get_height() // 2))
        ms = a.text.render(f"x{mult}", 36, (255, 255, 255), "title", True)
        sh = a.text.render(f"x{mult}", 36, (0, 0, 0), "title", True)
        surf.blit(sh, (ORB_C[0] - ms.get_width() // 2 + 2, ORB_C[1] - ms.get_height() // 2 + 2))
        surf.blit(ms, (ORB_C[0] - ms.get_width() // 2, ORB_C[1] - ms.get_height() // 2))
        # seri
        lab = a.text.render(t("hud.streak"), 16, TEXT_DIM, "ui", True)
        surf.blit(lab, (38, 586))
        cs = a.text.render(str(eng.combo), 40, lighten(col, 0.3) if eng.combo else TEXT_DIM, "title", True)
        surf.blit(cs, (38, 602))
        if st.autoplay:
            b = a.text.render(t("common.bot"), 16, (20, 20, 30), "ui", True)
            r = pygame.Rect(38, 664, b.get_width() + 16, 22)
            pygame.draw.rect(surf, NEON_CYAN, r, border_radius=6)
            surf.blit(b, (r.x + 8, r.y + 2))

    def _draw_right(self, surf, st) -> None:
        eng = st.engine
        a = self.a
        surf.blit(self.panel_right, (W - 318, 512))
        # rock metre
        gx = GAUGE_C[0] - self.gauge.get_width() // 2
        gy = GAUGE_C[1] - (GAUGE_R + 14)
        surf.blit(self.gauge, (gx, gy))
        rm = eng.rock_meter
        if rm < 1 / 3 and st.rock_active and math.sin(self.clock * 12) > 0:
            surf.blit(self.gauge_red, (gx, gy))
        ang = math.pi + rm * math.pi
        L = GAUGE_R - 10
        tip = (GAUGE_C[0] + L * math.cos(ang), GAUGE_C[1] + L * math.sin(ang))
        perp = (math.cos(ang + math.pi / 2) * 5, math.sin(ang + math.pi / 2) * 5)
        base_pt = GAUGE_C
        needle = [(base_pt[0] + perp[0], base_pt[1] + perp[1]), tip, (base_pt[0] - perp[0], base_pt[1] - perp[1])]
        pygame.draw.polygon(surf, (20, 20, 26), [(x + 2, y + 2) for x, y in needle])
        pygame.draw.polygon(surf, (250, 250, 255), needle)
        pygame.draw.circle(surf, (60, 60, 80), GAUGE_C, 10)
        pygame.draw.circle(surf, (200, 200, 220), GAUGE_C, 10, 2)
        lab = a.text.render(t("hud.rock_meter") if st.rock_active else t("hud.no_fail"), 14, TEXT_DIM, "ui", True)
        surf.blit(lab, (GAUGE_C[0] - lab.get_width() // 2, GAUGE_C[1] + 14))
        # star power bari
        x0, y0, bw, bh = W - 296, 676, 256, 18
        sp = eng.sp_meter
        ready = sp >= 0.5 and not eng.sp_active
        lab = a.text.render(t("hud.star_power"), 14, (150, 210, 255) if (ready or eng.sp_active) else TEXT_DIM, "ui", True)
        surf.blit(lab, (x0, y0 - 18))
        if ready:
            k = 0.5 + 0.5 * math.sin(self.clock * 10)
            rd = a.text.render(t("hud.ready"), 14, lerp_color((120, 200, 255), (255, 255, 255), k), "ui", True)
            surf.blit(rd, (x0 + bw - rd.get_width(), y0 - 18))
        elif eng.sp_active:
            rd = a.text.render(t("hud.active"), 14, (120, 220, 255), "ui", True)
            surf.blit(rd, (x0 + bw - rd.get_width(), y0 - 18))
        pygame.draw.rect(surf, (8, 8, 16), (x0 - 3, y0 - 3, bw + 6, bh + 6), border_radius=8)
        seg_w = (bw - 9) / 4
        for i in range(4):
            sx = x0 + i * (seg_w + 3)
            pygame.draw.rect(surf, (30, 34, 56), (sx, y0, seg_w, bh), border_radius=4)
            fill = max(0.0, min(1.0, sp * 4 - i))
            if fill > 0:
                if eng.sp_active:
                    c1 = lerp_color(SP_BLUE, (230, 250, 255), 0.5 + 0.5 * math.sin(self.clock * 14 + i))
                elif ready:
                    c1 = lerp_color((60, 180, 255), (200, 240, 255), 0.5 + 0.5 * math.sin(self.clock * 10))
                else:
                    c1 = (50, 150, 240)
                pygame.draw.rect(surf, c1, (sx, y0, max(2, seg_w * fill), bh), border_radius=4)
                pygame.draw.rect(surf, lighten(c1, 0.5), (sx + 2, y0 + 2, max(1, seg_w * fill - 4), 4), border_radius=2)
        if ready or eng.sp_active:
            gx2 = x0 + int(bw * min(1.0, sp)) - 40
            surf.blit(self.sp_glow, (gx2, y0 + bh // 2 - 40), special_flags=pygame.BLEND_ADD)

    def _draw_progress(self, surf, st) -> None:
        a = self.a
        x0, y0, w = 390, 12, 500
        pygame.draw.rect(surf, (20, 18, 36), (x0 - 2, y0 - 2, w + 4, 10), border_radius=5)
        prog = 0.0 if st.song_length <= 0 else max(0.0, min(1.0, st.visual_time / st.song_length))
        pygame.draw.rect(surf, (40, 36, 70), (x0, y0, w, 6), border_radius=3)
        if prog > 0:
            pygame.draw.rect(surf, lerp_color(NEON_PINK, NEON_CYAN, prog), (x0, y0, max(3, int(w * prog)), 6),
                             border_radius=3)
        for sx in st.section_marks:
            pygame.draw.line(surf, (120, 110, 170), (x0 + int(w * sx), y0 - 2), (x0 + int(w * sx), y0 + 7), 1)
        t = max(0.0, st.visual_time)
        ts = a.text.render(f"{int(t // 60)}:{int(t % 60):02d}", 14, TEXT_DIM, "ui")
        surf.blit(ts, (x0 - ts.get_width() - 10, y0 - 5))
        L = st.song_length
        te = a.text.render(f"{int(L // 60)}:{int(L % 60):02d}", 14, TEXT_DIM, "ui")
        surf.blit(te, (x0 + w + 10, y0 - 5))
        # sarki karti
        age = st.visual_time + st.lead_in
        if age < 7.0:
            alpha = 255 if age < 6.0 else int(255 * (7.0 - age))
            slide = min(1.0, max(0.0, age / 0.5))
            x = int(-300 + 320 * (1 - (1 - slide) ** 3))
            n = a.text.render(st.title, 30, TEXT, "title", True)
            ar = a.text.render(st.artist, 20, NEON_CYAN, "ui")
            d = a.text.render(st.diff_label, 16, NEON_ORANGE, "ui", True)
            wbox = max(n.get_width(), ar.get_width(), d.get_width()) + 30
            box = pygame.Surface((wbox, 96), pygame.SRCALPHA)
            pygame.draw.rect(box, (10, 8, 24, 200), (0, 0, wbox, 96), border_radius=10)
            pygame.draw.rect(box, NEON_PINK + (255,), (0, 0, 4, 96))
            box.blit(n, (16, 6))
            box.blit(ar, (16, 42))
            box.blit(d, (16, 70))
            box.set_alpha(alpha)
            surf.blit(box, (x, 40))

    def _draw_timing(self, surf, st) -> None:
        if not self.settings.extra.get("show_timing", True):
            return
        cx, y, half = W // 2, 704, 110
        pygame.draw.line(surf, (70, 66, 100), (cx - half, y), (cx + half, y), 2)
        pygame.draw.line(surf, (200, 200, 220), (cx, y - 7), (cx, y + 7), 2)
        for k in (-1, 1):
            pygame.draw.line(surf, (90, 86, 120), (cx + k * half, y - 5), (cx + k * half, y + 5), 1)
        e = self.a.text.render(t("hud.early"), 11, TEXT_DIM, "ui", True)
        l = self.a.text.render(t("hud.late"), 11, TEXT_DIM, "ui", True)
        surf.blit(e, (cx - half - e.get_width() - 8, y - 7))
        surf.blit(l, (cx + half + 8, y - 7))
        win = max(0.001, st.window)
        for (t0, off) in self.timing_marks:
            age = self.clock - t0
            if age > 2.5:
                continue
            k = 1 - age / 2.5
            x = cx + max(-1.0, min(1.0, off / win)) * half
            ao = abs(off) / win
            col = (80, 230, 110) if ao < 0.35 else (245, 205, 40) if ao < 0.7 else (240, 80, 60)
            col = lerp_color((30, 30, 40), col, k)
            pygame.draw.line(surf, col, (x, y - 8), (x, y + 8), 3 if age < 0.3 else 2)

    def _draw_solo(self, surf, st) -> None:
        so = self.solo
        if not so:
            return
        a = self.a
        r = pygame.Rect(958, 250, 200, 118)
        box = pygame.Surface(r.size, pygame.SRCALPHA)
        pygame.draw.rect(box, (14, 10, 30, 215), (0, 0, *r.size), border_radius=14)
        pygame.draw.rect(box, NEON_ORANGE + (255,), (0, 0, *r.size), 2, border_radius=14)
        surf.blit(box, r.topleft)
        ti = a.text.render(t("hud.solo"), 18, NEON_ORANGE, "ui", True)
        surf.blit(ti, (r.centerx - ti.get_width() // 2, r.y + 8))
        tot = max(1, so["total"])
        pct = int(100 * so["hits"] / tot)
        ps = a.text.render(f"{pct}%", 46, TEXT, "title", True)
        surf.blit(ps, (r.centerx - ps.get_width() // 2, r.y + 30))
        cs = a.text.render(f"{so['hits']} / {so['total']}", 16, TEXT_DIM, "ui")
        surf.blit(cs, (r.centerx - cs.get_width() // 2, r.y + 90))

    def _draw_debug(self, surf, st) -> None:
        a = self.a
        lines = [
            f"FPS {st.fps:6.1f}   frame {st.frame_ms:5.2f} ms",
            f"song {st.song_time:8.3f}  visual {st.visual_time:8.3f}",
            f"audio drift {st.drift * 1000:+6.2f} ms  {'anchored' if st.anchored else 'free'}",
            f"offsets A {st.audio_offset_ms:+d} V {st.video_offset_ms:+d} ms",
            f"notes {st.engine.notes_hit}/{st.engine.total_notes}  miss {st.engine.notes_missed}  over {st.engine.overstrums}",
            f"sp {st.engine.sp_meter:.2f} {'ACTIVE' if st.engine.sp_active else ''}  whammy {int(st.engine.whammy_active)}",
        ]
        w = 420
        h = 18 * len(lines) + 12
        box = pygame.Surface((w, h), pygame.SRCALPHA)
        box.fill((0, 0, 0, 175))
        surf.blit(box, (8, 150))
        for i, ln in enumerate(lines):
            s = a.text.render(ln, 15, (170, 255, 170), "mono")
            surf.blit(s, (16, 156 + i * 18))
