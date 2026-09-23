"""Ayarlar: oynanis, ses, goruntu, tus atama (tusa basarak), kontrolcu eslemesi. Tamamen klavyeyle gezilir."""
from __future__ import annotations

import math

import pygame

from ..config import KeyConfig
from ..input import CONTROLLER_HELP, key_label
from ..render.assets import NEON_CYAN, NEON_ORANGE, NEON_PINK, NEON_PURPLE, TEXT, TEXT_DIM, W
from ..render.ui import SynthBackground, draw_hints, draw_panel
from ..settings_store import save_settings
from .base import Scene

ROW_H = 40
VISIBLE = 13

KEY_ACTIONS = [
    ("fret:0", "Green fret"), ("fret:1", "Red fret"), ("fret:2", "Yellow fret"), ("fret:3", "Blue fret"),
    ("fret:4", "Orange fret"), ("strum_up", "Strum up"), ("strum_down", "Strum down"),
    ("open_strum", "Open strum"), ("star_power", "Star Power"), ("whammy", "Whammy"),
    ("start", "Start / Pause"), ("pause", "Pause / Back"),
]
FPS_CHOICES = [60, 120, 144, 240, 360, 0]
BUFFER_CHOICES = [256, 512, 1024, 2048]


class SettingsScene(Scene):
    def __init__(self, app, in_game: bool = False):
        super().__init__(app)
        # in_game: duraklatma menusunden acildi -> calan sarkiyi bozacak satirlar (ses tamponu, kalibrasyon) gizli
        self.in_game = in_game
        self.bg = SynthBackground()
        self.index = 1
        self.scroll = 0.0
        self.binding: str | None = None
        self.msg = ""
        self.msg_t = 0.0
        self.orig_buffer = app.settings.audio.buffer
        self.rows = self._rows()

    # --------------------------------------------------------------- satirlar
    def _rows(self):
        s = self.app.settings
        v, a = s.video, s.audio
        R = []
        R.append(("header", "GAMEPLAY"))
        R.append(("num", "Note speed", lambda: v.note_speed, lambda x: setattr(v, "note_speed", x), 0.1, 0.5, 3.0,
                  lambda x: f"{x:.1f}x"))
        R.append(("num", "Highway length", lambda: v.highway_length, lambda x: setattr(v, "highway_length", x), 0.05,
                  0.6, 1.5, lambda x: f"{x:.2f}x"))
        R.append(("bool", "No Fail", lambda: s.engine.no_fail, lambda x: setattr(s.engine, "no_fail", x)))
        R.append(("bool", "Timing meter", lambda: bool(s.extra.get("show_timing", True)),
                  lambda x: s.extra.__setitem__("show_timing", x)))
        R.append(("header", "AUDIO"))
        R.append(("num", "Master volume", lambda: a.master_volume, lambda x: setattr(a, "master_volume", x), 0.05, 0.0,
                  1.0, lambda x: f"{int(round(x * 100))}%"))
        R.append(("num", "SFX volume", lambda: a.sfx_volume, lambda x: setattr(a, "sfx_volume", x), 0.05, 0.0, 1.0,
                  lambda x: f"{int(round(x * 100))}%"))
        R.append(("num", "Audio offset", lambda: a.audio_offset_ms, lambda x: setattr(a, "audio_offset_ms", int(x)), 1,
                  -500, 500, lambda x: f"{int(x):+d} ms"))
        if not self.in_game:
            R.append(("choice", "Audio buffer", lambda: a.buffer, lambda x: setattr(a, "buffer", x), BUFFER_CHOICES,
                      lambda x: f"{x} samples"))
        R.append(("header", "VIDEO"))
        R.append(("num", "Video offset", lambda: v.video_offset_ms, lambda x: setattr(v, "video_offset_ms", int(x)), 1,
                  -500, 500, lambda x: f"{int(x):+d} ms"))
        R.append(("bool", "Fullscreen", lambda: v.fullscreen, lambda x: self._fullscreen(x)))
        R.append(("bool", "Show FPS / debug (F3)", lambda: v.show_debug, lambda x: setattr(v, "show_debug", x)))
        R.append(("choice", "FPS limit", lambda: v.fps_limit, lambda x: setattr(v, "fps_limit", x), FPS_CHOICES,
                  lambda x: "Unlimited" if x == 0 else f"{x}"))
        if not self.in_game:
            R.append(("action", "Calibrate audio / video", self._calibrate))
        R.append(("header", "CONTROLS  (Enter, then press a key)"))
        for key, label in KEY_ACTIONS:
            R.append(("key", label, key))
        R.append(("action", "Reset keys to default", self._reset_keys))
        R.append(("header", ""))
        R.append(("action", "Back", self._back))
        return R

    def _fullscreen(self, x: bool) -> None:
        if bool(x) != bool(self.app.settings.video.fullscreen):
            self.app.toggle_fullscreen(save=False)

    def _calibrate(self) -> None:
        from .calibration import CalibrationScene
        self.app.push(CalibrationScene(self.app))

    def _reset_keys(self) -> None:
        self.app.settings.keys = KeyConfig()
        self.app.input.rebuild_keymap()
        self._flash("Keys reset to defaults")

    def _back(self) -> None:
        s = self.app.settings
        save_settings(s)
        if s.audio.buffer != self.orig_buffer and not self.in_game:
            self.app.audio.reinit()
        self.sfx("menu_back")
        self.app.pop()

    def _flash(self, msg: str) -> None:
        self.msg = msg
        self.msg_t = 2.5

    # --------------------------------------------------------------- tuslar
    def _get_keys(self, key: str) -> tuple:
        k = self.app.settings.keys
        if key.startswith("fret:"):
            return k.frets[int(key[5:])]
        return getattr(k, key)

    def _set_keys(self, key: str, names: tuple) -> None:
        k = self.app.settings.keys
        if key.startswith("fret:"):
            i = int(key[5:])
            fr = list(k.frets)
            fr[i] = tuple(names)
            k.frets = tuple(fr)
        else:
            setattr(k, key, tuple(names))

    def _bind(self, key: str, name: str) -> None:
        # ayni tus baska eylemdeyse oradan cikar
        for other, _lab in KEY_ACTIONS:
            if other == key:
                continue
            cur = self._get_keys(other)
            if name in cur:
                rest = tuple(n for n in cur if n != name)
                if not rest:
                    old = self._get_keys(key)
                    rest = (old[0],) if old and old[0] != name else ()
                self._set_keys(other, rest)
        cur = self._get_keys(key)
        alts = tuple(n for n in cur[1:] if n != name)
        self._set_keys(key, (name,) + alts)
        self.app.input.rebuild_keymap()
        save_settings(self.app.settings)
        self._flash(f"Bound {key_label(name)}")

    def on_key(self, ev: pygame.event.Event) -> None:
        if self.binding is None:
            self.capture_keys = False
            return
        if ev.key == pygame.K_ESCAPE:
            self._flash("Cancelled")
        elif ev.key in (pygame.K_F3, pygame.K_F11):
            return
        else:
            name = pygame.key.name(ev.key)
            if name:
                self._bind(self.binding, name)
        self.binding = None
        self.capture_keys = False

    # --------------------------------------------------------------- gezinme
    def _selectable(self, i: int) -> bool:
        return self.rows[i][0] != "header"

    def on_menu(self, action: str) -> None:
        if action == "BACK":
            self._back()
            return
        if action in ("UP", "DOWN"):
            d = -1 if action == "UP" else 1
            i = self.index
            for _ in range(len(self.rows)):
                i = (i + d) % len(self.rows)
                if self._selectable(i):
                    break
            self.index = i
            self.sfx("menu_move", 0.7)
            return
        row = self.rows[self.index]
        kind = row[0]
        if kind == "num" and action in ("LEFT", "RIGHT"):
            _, _lab, get, set_, step, lo, hi, _fmt = row
            v = get() + (step if action == "RIGHT" else -step)
            v = max(lo, min(hi, round(v, 3)))
            set_(v)
            self.sfx("menu_move", 0.5)
            if _lab == "Master volume" or _lab == "SFX volume":
                self.sfx("menu_select", 0.8)
        elif kind == "bool" and action in ("LEFT", "RIGHT", "CONFIRM"):
            row[3](not row[2]())
            self.sfx("menu_move")
        elif kind == "choice" and action in ("LEFT", "RIGHT", "CONFIRM"):
            _, _lab, get, set_, choices, _fmt = row
            cur = get()
            i = choices.index(cur) if cur in choices else 0
            i = (i + (-1 if action == "LEFT" else 1)) % len(choices)
            set_(choices[i])
            self.sfx("menu_move")
        elif kind == "action" and action == "CONFIRM":
            self.sfx("menu_select")
            row[2]()
        elif kind == "key" and action == "CONFIRM":
            self.binding = row[2]
            self.capture_keys = True
            self.sfx("menu_select")

    def update(self, dt: float) -> None:
        super().update(dt)
        self.bg.update(dt)
        self.msg_t = max(0.0, self.msg_t - dt)
        target = min(max(0, self.index - VISIBLE // 2), max(0, len(self.rows) - VISIBLE))
        self.scroll += (target - self.scroll) * min(1.0, dt * 14)

    def draw(self, surf: pygame.Surface) -> None:
        a = self.assets
        tc = a.text
        self.bg.draw(surf, 0.1)
        shade = pygame.Surface((W, 720), pygame.SRCALPHA)
        shade.fill((4, 2, 14, 165))
        surf.blit(shade, (0, 0))
        head = tc.glow("SETTINGS", 42, (255, 130, 215), glow_color=NEON_PINK, radius=8)
        surf.blit(head, (40, 14))
        panel = pygame.Rect(30, 80, 720, ROW_H * VISIBLE + 20)
        draw_panel(surf, panel, border=NEON_PURPLE)
        clip = surf.get_clip()
        surf.set_clip(pygame.Rect(panel.x + 4, panel.y + 6, panel.w - 8, 10 + VISIBLE * ROW_H - 2))
        first = int(self.scroll)
        for i in range(first, min(len(self.rows), first + VISIBLE + 2)):
            row = self.rows[i]
            y = panel.y + 10 + (i - self.scroll) * ROW_H
            r = pygame.Rect(panel.x + 10, int(y), panel.w - 20, ROW_H - 4)
            kind = row[0]
            sel = i == self.index
            if kind == "header":
                if row[1]:
                    h = tc.render(row[1], 16, NEON_CYAN, "ui", True)
                    surf.blit(h, (r.x + 8, r.y + 12))
                    pygame.draw.line(surf, (60, 54, 100), (r.x + 8 + h.get_width() + 12, r.centery + 4),
                                     (r.right - 8, r.centery + 4), 1)
                continue
            if sel:
                k = 0.5 + 0.5 * math.sin(self.t * 5)
                hl = pygame.Surface(r.size, pygame.SRCALPHA)
                pygame.draw.rect(hl, (255, 60, 170, 55 + int(35 * k)), (0, 0, *r.size), border_radius=8)
                pygame.draw.rect(hl, (255, 100, 200, 220), (0, 0, *r.size), 2, border_radius=8)
                surf.blit(hl, r.topleft)
            lab = tc.render(row[1], 20, TEXT if sel else (200, 200, 215), "ui", sel)
            surf.blit(lab, (r.x + 16, r.centery - lab.get_height() // 2))
            val = ""
            if kind == "num":
                val = row[7](row[2]())
            elif kind == "bool":
                val = "ON" if row[2]() else "OFF"
            elif kind == "choice":
                val = row[5](row[2]())
            elif kind == "key":
                if self.binding == row[2]:
                    val = "press a key...  (Esc cancels)" if int(self.t * 3) % 2 == 0 else ""
                else:
                    val = "  /  ".join(key_label(n) for n in self._get_keys(row[2])) or "-"
            if val:
                col = NEON_ORANGE if sel else TEXT
                vs = tc.render(f"<  {val}  >" if sel and kind in ("num", "choice", "bool") else val, 20, col, "ui", True)
                surf.blit(vs, (r.right - vs.get_width() - 16, r.centery - vs.get_height() // 2))
        surf.set_clip(clip)
        # sag panel: aciklama / kontrolcu
        side = pygame.Rect(780, 80, 470, ROW_H * VISIBLE + 20)
        draw_panel(surf, side, border=NEON_CYAN)
        y = side.y + 18
        t = tc.render("CONTROLLER MAPPING", 18, NEON_CYAN, "ui", True)
        surf.blit(t, (side.x + 20, y))
        y += 34
        for lab, val in CONTROLLER_HELP:
            l = tc.render(lab, 15, TEXT_DIM)
            v = tc.render(val, 15, TEXT)
            surf.blit(l, (side.x + 20, y))
            surf.blit(v, (side.x + 20, y + 18))
            y += 42
        y += 6
        pads = self.app.input.pad_names()
        t = tc.render("CONNECTED", 16, NEON_CYAN, "ui", True)
        surf.blit(t, (side.x + 20, y))
        y += 26
        for n in (pads or ["No controller detected (hot-plug supported)"])[:3]:
            v = tc.render(n[:48], 15, TEXT if pads else TEXT_DIM)
            surf.blit(v, (side.x + 20, y))
            y += 22
        if self.msg_t > 0:
            m = tc.render(self.msg, 20, NEON_ORANGE, "ui", True)
            surf.blit(m, (W // 2 - m.get_width() // 2, 646))
        draw_hints(surf, a, [("Up/Down", "Select"), ("Left/Right", "Change"), ("Enter", "Toggle / Bind"),
                             ("Esc", "Save & back")])
