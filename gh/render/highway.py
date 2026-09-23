"""Perspektif nota otobani: zemin, beat cizgileri, gem'ler, sustain kuyruklari, perde butonlari, alevler.

Konum (YARG TrackElement): z = (nota_zamani - VisualTime) * hiz ; ekran = perspektif izdusum
    s(z) = D / (D + z)      y = HOR + (STRIKE_Y - HOR) * s      x = CX + p * HW * s   (p: -1..1 serit konumu)
Gorunen sure = Z_FAR / hiz  (R: SpawnTimeOffset = highwayLength / noteSpeed).
Yalnizca gorunur pencere (bisect) cizilir; tum sprite'lar onbellekli.
"""
from __future__ import annotations

import bisect
import math
import random

import pygame

from ..config import FRET_COLORS, OPEN_COLOR, SP_COLOR
from ..engine import NOTE_HIT, NOTE_MISSED
from ..models import NoteType
from .assets import (SP_BLUE, W, lerp_color, lighten, radial_glow, scale_color,
                     vertical_gradient)

CX = W // 2
STRIKE_Y = 580
HW = 250                  # vurus cizgisinde otoban yari genisligi (px)
CAM_D = 4.6               # kamera uzakligi (z birimi)
BASE_ZFAR = 11.0
Y_FAR_BASE = 62
BASE_SPEED = 8.0          # z birimi / saniye (note_speed = 1)
Z_NEAR = -1.35
LANE_P = (-0.8, -0.4, 0.0, 0.4, 0.8)
LANE_W = HW * 0.4         # s=1'de serit genisligi
GEM_W = LANE_W * 0.9
RAIL_P = 1.0


class Projection:
    def __init__(self, note_speed: float = 1.0, highway_length: float = 1.0):
        self.speed = BASE_SPEED * note_speed
        self.z_far = BASE_ZFAR * highway_length
        s1 = CAM_D / (CAM_D + BASE_ZFAR)
        self.hor = (Y_FAR_BASE - STRIKE_Y * s1) / (1 - s1)
        self.visible_time = self.z_far / self.speed

    def s(self, z: float) -> float:
        return CAM_D / (CAM_D + z)

    def y(self, z: float) -> float:
        return self.hor + (STRIKE_Y - self.hor) * CAM_D / (CAM_D + z)

    def x(self, p: float, z: float) -> float:
        return CX + p * HW * CAM_D / (CAM_D + z)

    def z_of_y(self, y: float) -> float:
        s = (y - self.hor) / (STRIKE_Y - self.hor)
        return CAM_D / max(1e-6, s) - CAM_D


class Particle:
    __slots__ = ("x", "y", "vx", "vy", "life", "max", "color", "r")

    def __init__(self, x, y, vx, vy, life, color, r):
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.life = self.max = life
        self.color = color
        self.r = r


class HighwayRenderer:
    def __init__(self, assets, settings):
        self.assets = assets
        self.settings = settings
        self.rng = random.Random(7)
        self.particles: list[Particle] = []
        self.hit_time = [-10.0] * 6        # serit basina son vurus (5 = acik)
        self.hit_sp = [False] * 6
        self.sp_flash = -10.0
        self.bolts: list[tuple[float, list]] = []
        self._bolt_next = 0.0
        self.time = 0.0
        self.configure()

    # ------------------------------------------------------------------ kurulum
    def configure(self) -> None:
        v = self.settings.video
        self.proj = Projection(v.note_speed, v.highway_length)
        self._build_board()
        self._build_fog()
        self._build_sp_glow()
        self._build_effect_frames()

    def _poly(self, p0: float, p1: float, z0: float, z1: float):
        pr = self.proj
        return [(pr.x(p0, z0), pr.y(z0)), (pr.x(p1, z0), pr.y(z0)), (pr.x(p1, z1), pr.y(z1)),
                (pr.x(p0, z1), pr.y(z1))]

    def _build_board(self) -> None:
        pr = self.proj
        top = int(pr.y(pr.z_far)) - 2
        self.board_top = top
        h = 720 - top
        board = pygame.Surface((W, h), pygame.SRCALPHA)
        off = (0, -top)

        def sh(pts):
            return [(x + off[0], y + off[1]) for x, y in pts]

        zn, zf = Z_NEAR, pr.z_far
        # zemin: koyu degrade (uzak: daha koyu)
        poly = sh(self._poly(-RAIL_P, RAIL_P, zn, zf))
        grad = vertical_gradient((W, h), (10, 10, 18, 255), (34, 30, 48, 255), alpha=True)
        mask = pygame.Surface((W, h), pygame.SRCALPHA)
        pygame.draw.polygon(mask, (255, 255, 255, 255), poly)
        grad.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        board.blit(grad, (0, 0))
        # doku: kaybolma noktasina yakinsayan ince damarlar
        rng = random.Random(3)
        for _ in range(140):
            p = rng.uniform(-0.98, 0.98)
            c = rng.randint(-10, 12)
            col = (max(0, 24 + c), max(0, 22 + c), max(0, 34 + c))
            a = sh([(pr.x(p, zn), pr.y(zn)), (pr.x(p, zf), pr.y(zf))])
            pygame.draw.line(board, col, a[0], a[1], 1)
        # serit bolucu cizgiler
        for p in (-0.6, -0.2, 0.2, 0.6):
            a = sh([(pr.x(p, zn), pr.y(zn)), (pr.x(p, zf), pr.y(zf))])
            pygame.draw.line(board, (70, 70, 92), a[0], a[1], 2)
            pygame.draw.aaline(board, (110, 110, 140), a[0], a[1])
        # yan raylar (metalik) + ic golge
        for sgn in (-1, 1):
            outer = sh(self._poly(sgn * 1.0, sgn * 1.075, zn, zf))
            pygame.draw.polygon(board, (150, 150, 170), outer)
            inner = sh(self._poly(sgn * 1.0, sgn * 1.03, zn, zf))
            pygame.draw.polygon(board, (225, 225, 240), inner)
            edge = sh([(pr.x(sgn * 1.075, zn), pr.y(zn)), (pr.x(sgn * 1.075, zf), pr.y(zf))])
            pygame.draw.aaline(board, (60, 60, 80), edge[0], edge[1])
            shade = sh(self._poly(sgn * 0.93, sgn * 1.0, zn, zf))
            sshade = pygame.Surface((W, h), pygame.SRCALPHA)
            pygame.draw.polygon(sshade, (0, 0, 0, 90), shade)
            board.blit(sshade, (0, 0))
            # kenar yumusatma (poligon kenarlari)
            for p, col in ((1.075, (120, 120, 140)), (1.03, (200, 200, 215)), (1.0, (150, 150, 168))):
                a = sh([(pr.x(sgn * p, zn), pr.y(zn)), (pr.x(sgn * p, zf), pr.y(zf))])
                pygame.draw.aaline(board, col, a[0], a[1])
        self.board = board.convert_alpha()
        # vurus cizgisi (strike bar)
        self.hw_poly = self._poly(-1.075, 1.075, zn, zf)

    def _build_fog(self) -> None:
        """Otoban katmani + uzak ucta alfa sonumu (otoban sahneye karisarak kaybolur)."""
        pr = self.proj
        top = self.board_top
        z_bot = pr.z_of_y(720)
        half = int(HW * 1.2 * pr.s(z_bot)) + 12
        self.layer_rect = pygame.Rect(CX - half, top, half * 2, 720 - top)
        self.layer = pygame.Surface((W, 720), pygame.SRCALPHA)
        fade_end = pr.y(pr.z_far * 0.5)
        h = int(fade_end - top) + 2
        mask = pygame.Surface((self.layer_rect.w, h), pygame.SRCALPHA)
        for yy in range(h):
            t = yy / max(1, h - 1)
            a = int(255 * min(1.0, t ** 1.35))
            pygame.draw.line(mask, (255, 255, 255, a), (0, yy), (self.layer_rect.w, yy))
        self.fade_mask = mask

    def _build_sp_glow(self) -> None:
        """SP aktifken otoban kenarlarinda mavi parlama (toplamali, 4 yogunluk)."""
        pr = self.proj
        top = self.board_top
        h = 720 - top
        base = pygame.Surface((W, h))
        base.fill((0, 0, 0))
        for i in range(14):
            k = i / 14
            for sgn in (-1, 1):
                p0 = sgn * (1.0 - 0.22 * (1 - k))
                p1 = sgn * (1.1 + 0.08 * (1 - k))
                poly = [(x, y - top) for x, y in self._poly(min(p0, p1), max(p0, p1), Z_NEAR, pr.z_far)]
                c = scale_color(SP_COLOR, 0.05 + 0.06 * k)
                tmp = pygame.Surface((W, h))
                tmp.fill((0, 0, 0))
                pygame.draw.polygon(tmp, c, poly)
                base.blit(tmp, (0, 0), special_flags=pygame.BLEND_ADD)
        tint = pygame.Surface((W, h))
        tint.fill((0, 0, 0))
        pygame.draw.polygon(tint, (0, 18, 40), [(x, y - top) for x, y in self._poly(-1, 1, Z_NEAR, pr.z_far)])
        base.blit(tint, (0, 0), special_flags=pygame.BLEND_ADD)
        # uzak uc sonumu (otoban katmaniyla ayni egri)
        fade = pygame.Surface((W, h))
        fade.fill((255, 255, 255))
        fh = self.fade_mask.get_height()
        for yy in range(fh):
            v = int(255 * min(1.0, (yy / max(1, fh - 1)) ** 1.35))
            pygame.draw.line(fade, (v, v, v), (0, yy), (W, yy))
        base.blit(fade, (0, 0), special_flags=pygame.BLEND_MULT)
        self.sp_glow = []
        for k in (0.55, 0.75, 0.95, 1.15):
            s = base.copy()
            m = pygame.Surface((W, h))
            v = int(min(255, 255 * k))
            m.fill((v, v, v))
            s.blit(m, (0, 0), special_flags=pygame.BLEND_MULT)
            self.sp_glow.append(s.convert())

    def _build_effect_frames(self) -> None:
        self.flame_levels: dict[int, list[list[pygame.Surface]]] = {}
        for f in list(range(5)) + [-1, 5]:
            frames = self.assets.flames(f)
            levels = []
            for k in (1.0, 0.62, 0.32):
                lv = []
                for fr in frames:
                    s = fr.copy()
                    v = int(255 * k)
                    m = pygame.Surface(s.get_size())
                    m.fill((v, v, v))
                    s.blit(m, (0, 0), special_flags=pygame.BLEND_MULT)
                    lv.append(s)
                levels.append(lv)
            self.flame_levels[f] = levels
        self.ring_frames: dict[int, list[pygame.Surface]] = {}
        for f in list(range(5)) + [-1]:
            ring = self.assets.ring(f)
            fr = []
            for i in range(8):
                k = i / 7
                sc = 0.7 + 0.8 * k
                img = pygame.transform.smoothscale(ring, (int(ring.get_width() * sc), int(ring.get_height() * sc)))
                v = int(255 * (1 - k) ** 1.3)
                m = pygame.Surface(img.get_size())
                m.fill((v, v, v))
                img.blit(m, (0, 0), special_flags=pygame.BLEND_MULT)
                fr.append(img)
            self.ring_frames[f] = fr
        self.strike_glow = radial_glow(60, (70, 70, 110), 2.2)
        # perde butonlari
        bw = int(LANE_W * 0.92)
        self.buttons = [(self.assets.button(f, False, bw), self.assets.button(f, True, bw)) for f in range(5)]

    # ------------------------------------------------------------------ olaylar
    def on_hit(self, mask: int, sp: bool, t: float) -> None:
        pr = self.proj
        y = pr.y(0)
        if mask == 0:
            self.hit_time[5] = t
            self.hit_sp[5] = sp
            for p in LANE_P:
                self._burst(pr.x(p, 0), y, OPEN_COLOR if not sp else SP_COLOR, 6)
            return
        for f in range(5):
            if mask >> f & 1:
                self.hit_time[f] = t
                self.hit_sp[f] = sp
                self._burst(pr.x(LANE_P[f], 0), y, SP_COLOR if sp else FRET_COLORS[f], 10)

    def on_sp_activate(self, t: float) -> None:
        self.sp_flash = t
        for _ in range(40):
            p = self.rng.choice((-1.0, 1.0))
            z = self.rng.uniform(0, self.proj.z_far * 0.8)
            x, y = self.proj.x(p, z), self.proj.y(z)
            self.particles.append(Particle(x, y, self.rng.uniform(-60, 60), self.rng.uniform(-160, -20),
                                           self.rng.uniform(0.3, 0.7), SP_COLOR, 3))

    def _burst(self, x, y, color, n) -> None:
        rng = self.rng
        for _ in range(n):
            a = rng.uniform(-math.pi * 0.92, -math.pi * 0.08)
            sp = rng.uniform(140, 420)
            self.particles.append(Particle(x + rng.uniform(-14, 14), y - 6, math.cos(a) * sp, math.sin(a) * sp,
                                           rng.uniform(0.18, 0.42), lighten(color, 0.45), rng.choice((2, 3, 3, 4))))
        if len(self.particles) > 400:
            del self.particles[:len(self.particles) - 400]

    # ------------------------------------------------------------------ cizim
    def update(self, dt: float) -> None:
        self.time += dt
        keep = []
        g = 900.0
        for p in self.particles:
            p.life -= dt
            if p.life <= 0:
                continue
            p.vy += g * dt
            p.x += p.vx * dt
            p.y += p.vy * dt
            keep.append(p)
        self.particles = keep

    def draw(self, surf: pygame.Surface, st) -> None:
        """st: GameplayState benzeri nesne (vt, notes, engine, beat_lines, times, max_sus, ...)."""
        pr = self.proj
        vt = st.visual_time
        eng = st.engine
        sp_active = eng.sp_active
        # otoban katmani: zemin + cizgiler + kuyruklar + gem'ler, sonra uzak uc alfa ile sonumlenir
        lay = self.layer
        r = self.layer_rect
        lay.fill((0, 0, 0, 0), r)
        lay.blit(self.board, r.topleft, pygame.Rect(r.x, 0, r.w, r.h), special_flags=pygame.BLEND_RGBA_MAX)
        self._draw_beatlines(lay, st, vt)
        self._draw_strike_bar(lay, st)
        self._draw_notes(lay, st, vt, sp_active)
        lay.blit(self.fade_mask, r.topleft, special_flags=pygame.BLEND_RGBA_MULT)
        surf.blit(lay, r.topleft, r)
        if sp_active:
            beat = st.beat_phase
            lvl = 3 if beat < 0.15 else 2 if beat < 0.45 else 1
            surf.blit(self.sp_glow[lvl], (0, self.board_top), special_flags=pygame.BLEND_ADD)
            self._draw_bolts(surf, st)
        self._draw_buttons(surf, st)
        self._draw_flames(surf, st)
        self._draw_particles(surf)

    def _draw_beatlines(self, surf, st, vt) -> None:
        pr = self.proj
        lines = st.beat_times
        i0 = bisect.bisect_left(lines, vt + Z_NEAR / pr.speed)
        i1 = bisect.bisect_right(lines, vt + pr.visible_time)
        kinds = st.beat_kinds
        for i in range(i0, i1):
            k = kinds[i]
            z = (lines[i] - vt) * pr.speed
            s = CAM_D / (CAM_D + z)
            y = pr.hor + (STRIKE_Y - pr.hor) * s
            x0 = CX - HW * s * 0.995
            x1 = CX + HW * s * 0.995
            if k == 0:
                col = (150, 150, 185)
                th = max(1, int(5 * s))
            elif k == 1:
                col = (88, 88, 118)
                th = max(1, int(3 * s))
            else:
                if s < 0.45:
                    continue
                col = (46, 46, 64)
                th = 1
            if st.engine.sp_active:
                col = lerp_color(col, (80, 170, 255), 0.5)
            pygame.draw.line(surf, col, (x0, y), (x1, y), th)

    def _draw_strike_bar(self, surf, st) -> None:
        pr = self.proj
        y = pr.y(0)
        x0, x1 = pr.x(-1.0, 0), pr.x(1.0, 0)
        pygame.draw.line(surf, (20, 20, 28), (x0, y + 3), (x1, y + 3), 9)
        col = (90, 200, 255) if st.engine.sp_active else (200, 200, 220)
        pygame.draw.line(surf, col, (x0, y), (x1, y), 3)

    # ---- notalar
    def _style_for(self, note, state, eng, sp_active, phrase_ok) -> str:
        if state == NOTE_MISSED:
            return "miss"
        if sp_active:
            return "sp"
        if note.sp_phrase >= 0 and phrase_ok[note.sp_phrase]:
            return "star"
        return "normal"

    def _draw_notes(self, surf, st, vt, sp_active) -> None:
        pr = self.proj
        eng = st.engine
        notes = st.notes
        times = st.times
        state = eng.note_state
        phrase_ok = eng.sp_phrase_ok
        t_lo = vt + Z_NEAR / pr.speed
        t_hi = vt + pr.visible_time
        i0 = bisect.bisect_left(times, t_lo - st.max_sus)
        i1 = bisect.bisect_right(times, t_hi)
        sustaining = eng.sustaining
        # kuyruklar (uzaktan yakina)
        for i in range(i1 - 1, i0 - 1, -1):
            n = notes[i]
            if not n.has_sustain:
                continue
            end = st.sus_end[i]
            if end < t_lo or end <= n.time:
                continue
            self._draw_tail(surf, st, i, n, end, vt, state[i], sp_active, phrase_ok, i in sustaining)
        # gem'ler (uzaktan yakina)
        gems = self.assets.gems
        for i in range(i1 - 1, i0 - 1, -1):
            n = notes[i]
            if n.time < t_lo:
                break
            stt = state[i]
            if stt == NOTE_HIT:
                continue
            z = (n.time - vt) * pr.speed
            if z > pr.z_far + 0.2:
                continue
            s = CAM_D / (CAM_D + z)
            y = pr.hor + (STRIKE_Y - pr.hor) * s
            style = self._style_for(n, stt, eng, sp_active, phrase_ok)
            kind = "tap" if n.type == NoteType.TAP else "hopo" if n.type == NoteType.HOPO else "strum"
            if n.mask == 0:
                w = int(HW * 2 * s * 0.97)
                img, ay = gems.get(-1, kind, "star" if style == "star" else style, w)
                surf.blit(img, (CX - img.get_width() // 2, y - ay))
                continue
            gw = GEM_W * s * (0.86 if kind != "strum" else 1.0)
            if style == "star":
                gw *= 1.12
            m = n.mask
            for f in range(5):
                if m >> f & 1:
                    img, ay = gems.get(f, kind, style, int(gw))
                    x = CX + LANE_P[f] * HW * s
                    surf.blit(img, (x - img.get_width() // 2, y - ay))

    def _tail_colors(self, fret, state, sp_active, star, held, dropped):
        if state == NOTE_MISSED or dropped:
            return (70, 70, 78), (110, 110, 120)
        if sp_active:
            base = SP_BLUE
        elif star:
            base = (150, 225, 255)
        else:
            base = OPEN_COLOR if fret < 0 else FRET_COLORS[fret]
        if held:
            return lighten(base, 0.15), lighten(base, 0.7)
        return scale_color(base, 0.72), lighten(base, 0.2)

    def _draw_tail(self, surf, st, i, n, end, vt, state, sp_active, phrase_ok, held) -> None:
        pr = self.proj
        dropped = st.dropped.get(i, False) or (state == NOTE_HIT and not held and end > vt + 0.03)
        if state == NOTE_HIT and held:
            z0 = 0.0
        else:
            z0 = (n.time - vt) * pr.speed
        z1 = (end - vt) * pr.speed
        z0 = max(z0, Z_NEAR)
        z1 = min(z1, pr.z_far + 0.3)
        if z1 <= z0 + 0.01:
            return
        star = n.sp_phrase >= 0 and phrase_ok[n.sp_phrase]
        wob = held and st.engine.whammy_active
        segs = max(2, min(36, int((z1 - z0) / 0.3) + 2))
        frets = [f for f in range(5) if n.mask >> f & 1] if n.mask else [-1]
        tt = self.time
        for f in frets:
            outer_c, inner_c = self._tail_colors(f, state, sp_active, star, held, dropped)
            if f < 0:
                p_c, half = 0.0, 0.62
            else:
                p_c, half = LANE_P[f], 0.075
            left, right, il, ir = [], [], [], []
            for k in range(segs + 1):
                z = z0 + (z1 - z0) * k / segs
                s = CAM_D / (CAM_D + z)
                y = pr.hor + (STRIKE_Y - pr.hor) * s
                xc = CX + p_c * HW * s
                if wob:
                    xc += math.sin(z * 3.2 - tt * 22.0) * 7.0 * s * min(1.0, z * 2 + 0.2)
                elif held:
                    xc += math.sin(z * 5.0 - tt * 30.0) * 1.2 * s
                hw = half * HW * s
                left.append((xc - hw, y))
                right.append((xc + hw, y))
                ih = hw * 0.42
                il.append((xc - ih, y))
                ir.append((xc + ih, y))
            pygame.draw.polygon(surf, (12, 12, 18), [(x - 2, y) for x, y in left] + [(x + 2, y) for x, y in right[::-1]])
            pygame.draw.polygon(surf, outer_c, left + right[::-1])
            pygame.draw.polygon(surf, inner_c, il + ir[::-1])

    # ---- butonlar ve efektler
    def _draw_buttons(self, surf, st) -> None:
        pr = self.proj
        y = pr.y(0)
        held = st.engine.held_mask
        now = st.visual_time
        for f in range(5):
            pressed = bool(held >> f & 1)
            (img, ay) = self.buttons[f][1 if pressed else 0]
            x = pr.x(LANE_P[f], 0)
            age = now - self.hit_time[f]
            dy = 0
            if 0 <= age < 0.12:
                dy = -int(6 * (1 - age / 0.12))
            surf.blit(img, (x - img.get_width() // 2, y - ay + dy))

    def _draw_flames(self, surf, st) -> None:
        pr = self.proj
        y = pr.y(0)
        now = st.visual_time
        eng = st.engine
        sus_lanes = set()
        open_sus = False
        for idx in eng.sustaining:
            m = st.notes[idx].mask
            if m == 0:
                open_sus = True
            for f in range(5):
                if m >> f & 1:
                    sus_lanes.add(f)
        fi = int(self.time * 30)
        for f in range(6):
            age = now - self.hit_time[f]
            lanes = [f] if f < 5 else list(range(5))
            key = f if f < 5 else -1
            if 0 <= age < 0.14:
                rings = self.ring_frames[key]
                img = rings[min(len(rings) - 1, int(age / 0.14 * len(rings)))]
                for ln in lanes:
                    x = pr.x(LANE_P[ln], 0)
                    surf.blit(img, (x - img.get_width() // 2, y - img.get_height() // 2), special_flags=pygame.BLEND_ADD)
            if 0 <= age < 0.26:
                lvl = 0 if age < 0.09 else 1 if age < 0.17 else 2
                fkey = 5 if self.hit_sp[f] else key
                fr = self.flame_levels[fkey][lvl]
                img = fr[(fi + f * 3) % len(fr)]
                for ln in lanes:
                    x = pr.x(LANE_P[ln], 0)
                    surf.blit(img, (x - img.get_width() // 2, y - img.get_height() + 22), special_flags=pygame.BLEND_ADD)
        sp = eng.sp_active
        for f in sus_lanes:
            fr = self.flame_levels[5 if sp else f][0]
            img = fr[(fi + f * 4) % len(fr)]
            x = pr.x(LANE_P[f], 0)
            surf.blit(img, (x - img.get_width() // 2, y - img.get_height() + 22), special_flags=pygame.BLEND_ADD)
            if self.rng.random() < 0.35:
                c = SP_COLOR if sp else FRET_COLORS[f]
                self.particles.append(Particle(x + self.rng.uniform(-10, 10), y - 8, self.rng.uniform(-70, 70),
                                               self.rng.uniform(-330, -120), self.rng.uniform(0.15, 0.35),
                                               lighten(c, 0.5), 2))
        if open_sus:
            fr = self.flame_levels[-1][2]
            img = fr[fi % len(fr)]
            for p in LANE_P:
                x = pr.x(p, 0)
                surf.blit(img, (x - img.get_width() // 2, y - img.get_height() + 22), special_flags=pygame.BLEND_ADD)

    def _draw_particles(self, surf) -> None:
        sparks = self.assets.sparks
        for p in self.particles:
            k = p.life / p.max
            r = max(1, int(p.r * (0.4 + 0.6 * k)))
            img = sparks.get(r * 2, p.color)
            surf.blit(img, (p.x - r * 2, p.y - r * 2), special_flags=pygame.BLEND_ADD)

    def _draw_bolts(self, surf, st) -> None:
        pr = self.proj
        now = self.time
        if now >= self._bolt_next:
            self._bolt_next = now + self.rng.uniform(0.08, 0.35)
            side = self.rng.choice((-1.08, 1.08))
            za = self.rng.uniform(0.2, pr.z_far * 0.6)
            zb = za + self.rng.uniform(1.0, 3.5)
            pts = []
            n = 9
            for k in range(n + 1):
                z = za + (zb - za) * k / n
                jitter = self.rng.uniform(-0.05, 0.05) if 0 < k < n else 0
                pts.append((pr.x(side + jitter, z), pr.y(z) + self.rng.uniform(-4, 4)))
            self.bolts.append((now + 0.09, pts))
        alive = []
        for until, pts in self.bolts:
            if now <= until:
                pygame.draw.lines(surf, (120, 210, 255), False, pts, 4)
                pygame.draw.lines(surf, (240, 250, 255), False, pts, 2)
                alive.append((until, pts))
        self.bolts = alive
        age = st.visual_time - self.sp_flash
        if 0 <= age < 0.5:
            k = 1 - age / 0.5
            y = pr.y(age * pr.z_far * 2)
            w = HW * pr.s(age * pr.z_far * 2)
            pygame.draw.line(surf, lerp_color((40, 90, 160), (220, 245, 255), k), (CX - w, y), (CX + w, y),
                             max(2, int(10 * k)))
