"""Kalibrasyon (ek-01 §1.6): 120 BPM metronom, oyuncu her tikta strum/space'e basar.

- Ses gecisi: tik izi bellek ici WAV olarak mixer.music ile calinir -> oyundaki ayni Conductor saati
  (ses saati hizalamasi dahil). >= 16 gecerli vurus; audio offset = hatalarin MEDYANI; std sapma > 25 ms ise
  "tutarsiz, tekrar" (Clone Hero ortalama kullanir; medyan tek kacan vurusa dayanikli).
- Goruntu gecisi (istege bagli, sessiz): hedef cizgiye inen isaretler; video offset = medyan hata
  (VisualTime = SongTime + video_offset; olculen = ekran + girdi gecikmesi).
"""
from __future__ import annotations

import math
import statistics

import numpy as np
import pygame

from ..audio import Conductor, wav_bytes
from ..config import FRET_COLORS
from ..engine import InputKind
from ..render.assets import GOLD, NEON_CYAN, NEON_ORANGE, NEON_PINK, TEXT, TEXT_DIM, W, lerp_color
from ..render.ui import MenuList, SynthBackground, draw_hints, draw_panel
from ..settings_store import save_settings
from .base import Scene

BPM = 120.0
BEAT = 60.0 / BPM
COUNT_IN = 4
TAP_BEATS = 20
FIRST = 1.0            # ilk tik (s)
MIN_TAPS = 16
MAX_STDEV = 0.025
MATCH_WINDOW = 0.20


class CalibrationScene(Scene):
    def __init__(self, app):
        super().__init__(app)
        self.bg = SynthBackground()
        self.phase = "intro"           # intro | audio | audio_result | visual_intro | visual | visual_result
        self.conductor: Conductor | None = None
        self.clicks = [FIRST + i * BEAT for i in range(COUNT_IN + TAP_BEATS)]
        self.taps: list[float] = []
        self.errors: list[float] = []
        self.result_ok = False
        self.result_msg = ""
        self.value_ms = 0
        self.menu: MenuList | None = None
        self.song_t = -1.0
        self.last_click_i = -1
        self.flash_t = -10.0
        self.tap_flash = -10.0

    def enter(self) -> None:
        self.app.audio.stop_preview(200)

    def exit(self) -> None:
        if self.conductor is not None:
            self.conductor.stop()

    # ------------------------------------------------------------ gecisler
    def _click_track(self) -> "io.BytesIO":
        audio = self.app.audio
        sr = audio.sr
        hi = audio.sfx_array("metronome_hi")
        lo = audio.sfx_array("metronome_lo")
        if hi is None or lo is None:
            n = int(sr * 0.04)
            t = np.arange(n) / sr
            tone = (np.sin(2 * np.pi * 1500 * t) * np.exp(-t * 90) * 20000).astype(np.int16)
            hi = lo = np.stack([tone, tone], axis=1)
        ch = hi.shape[1] if hi.ndim == 2 else 1
        total = int(sr * (self.clicks[-1] + 1.0))
        buf = np.zeros((total, ch), dtype=np.int32)
        for i, c in enumerate(self.clicks):
            src = hi if i % 4 == 0 else lo
            s0 = int(round(c * sr))
            n = min(len(src), total - s0)
            buf[s0:s0 + n] += src[:n].reshape(n, -1)[:, :ch]
        buf = np.clip(buf, -32768, 32767).astype(np.int16)
        return wav_bytes(buf, sr)

    def _start_audio(self) -> None:
        self.taps.clear()
        self.errors.clear()
        if self.conductor is not None:
            self.conductor.stop()
        music = self._click_track() if self.app.audio.ok else None
        self.conductor = Conductor(self.app.audio, {}, music_file=music, lead_in=0.4)
        self.conductor.load()
        self.conductor.set_volume(max(0.3, self.app.settings.audio.master_volume))
        self.conductor.start()
        self.phase = "audio"
        self.last_click_i = -1

    def _start_visual(self) -> None:
        self.taps.clear()
        self.errors.clear()
        if self.conductor is not None:
            self.conductor.stop()
        self.conductor = Conductor(None, {}, lead_in=0.4)   # yalnizca saat (sessiz)
        self.conductor.start()
        self.phase = "visual"
        self.last_click_i = -1

    def _finish_pass(self) -> None:
        errs = []
        for tp in self.taps:
            j = min(range(COUNT_IN - 1, len(self.clicks)), key=lambda k: abs(self.clicks[k] - tp))
            e = tp - self.clicks[j]
            if abs(e) <= MATCH_WINDOW:
                errs.append(e)
        self.errors = errs
        audio = self.phase == "audio"
        if self.conductor is not None:
            self.conductor.stop()
        if len(errs) < MIN_TAPS:
            self.result_ok = False
            self.result_msg = f"Only {len(errs)} valid taps (need {MIN_TAPS}). Tap on every click!"
        else:
            med = statistics.median(errs)
            sd = statistics.pstdev(errs)
            if sd > MAX_STDEV:
                self.result_ok = False
                self.result_msg = f"Inconsistent taps (stdev {sd * 1000:.1f} ms > {MAX_STDEV * 1000:.0f} ms). Try again."
            else:
                self.result_ok = True
                self.value_ms = int(round(med * 1000))
                self.result_msg = f"stdev {sd * 1000:.1f} ms over {len(errs)} taps"
        if audio:
            self.phase = "audio_result"
            items = ["SAVE & CALIBRATE VIDEO", "SAVE & FINISH", "RETRY", "CANCEL"] if self.result_ok else ["RETRY", "CANCEL"]
        else:
            self.phase = "visual_result"
            items = ["SAVE & FINISH", "RETRY", "CANCEL"] if self.result_ok else ["RETRY", "CANCEL"]
        self.menu = MenuList(items, W // 2, 440, spacing=50, size=28)

    # ------------------------------------------------------------ girdi
    def on_game(self, gi) -> None:
        if self.phase not in ("audio", "visual") or self.conductor is None:
            return
        if gi.kind in (InputKind.STRUM, InputKind.OPEN_STRUM):
            t = self.conductor.song_time(gi.pc)
            self.taps.append(t)
            self.tap_flash = self.t

    def on_menu(self, action: str) -> None:
        s = self.app.settings
        if self.phase in ("audio", "visual"):
            if action == "BACK":
                self.conductor.stop()
                self.phase = "intro" if self.phase == "audio" else "visual_intro"
            return
        if self.phase in ("intro", "visual_intro"):
            if action == "CONFIRM":
                self.sfx("menu_select")
                if self.phase == "intro":
                    self._start_audio()
                else:
                    self._start_visual()
            elif action == "BACK":
                self.sfx("menu_back")
                self.app.pop()
            elif action == "OPTION" and self.phase == "intro":
                self.phase = "visual_intro"
            return
        # sonuc menusu
        if self.menu is None:
            return
        if action == "UP":
            self.menu.move(-1)
            self.sfx("menu_move")
        elif action == "DOWN":
            self.menu.move(1)
            self.sfx("menu_move")
        elif action == "BACK":
            self.app.pop()
        elif action == "CONFIRM":
            self.sfx("menu_select")
            item = self.menu.items[self.menu.index]
            if item == "RETRY":
                if self.phase == "audio_result":
                    self._start_audio()
                else:
                    self._start_visual()
            elif item == "CANCEL":
                self.app.pop()
            elif item.startswith("SAVE"):
                if self.phase == "audio_result":
                    s.audio.audio_offset_ms = self.value_ms
                else:
                    s.video.video_offset_ms = self.value_ms
                s.extra["calibrated"] = True
                save_settings(s)
                if item == "SAVE & CALIBRATE VIDEO":
                    self.phase = "visual_intro"
                else:
                    self.app.pop()

    # ------------------------------------------------------------ dongu
    def update(self, dt: float) -> None:
        super().update(dt)
        self.bg.update(dt)
        if self.menu is not None:
            self.menu.update(dt)
        if self.phase in ("audio", "visual") and self.conductor is not None:
            self.song_t = self.conductor.update()
            while self.last_click_i + 1 < len(self.clicks) and self.song_t >= self.clicks[self.last_click_i + 1]:
                self.last_click_i += 1
                self.flash_t = self.t - (self.song_t - self.clicks[self.last_click_i])
            if self.song_t > self.clicks[-1] + 0.7:
                self._finish_pass()

    def draw(self, surf: pygame.Surface) -> None:
        a = self.assets
        tc = a.text
        self.bg.draw(surf, 0.0)
        shade = pygame.Surface((W, 720), pygame.SRCALPHA)
        shade.fill((4, 2, 14, 170))
        surf.blit(shade, (0, 0))
        head = tc.glow("CALIBRATION", 42, (255, 130, 215), glow_color=NEON_PINK, radius=8)
        surf.blit(head, (W // 2 - head.get_width() // 2, 18))
        s = self.app.settings
        cur = tc.render(f"current:  audio {s.audio.audio_offset_ms:+d} ms   video {s.video.video_offset_ms:+d} ms",
                        18, TEXT_DIM)
        surf.blit(cur, (W // 2 - cur.get_width() // 2, 84))
        panel = pygame.Rect(W // 2 - 420, 120, 840, 520)
        draw_panel(surf, panel, border=NEON_CYAN)
        p = self.phase
        if p == "intro":
            self._text_block(surf, panel, [
                ("AUDIO CALIBRATION", 30, NEON_CYAN),
                ("You will hear a metronome at 120 BPM.", 22, TEXT),
                (f"After {COUNT_IN} count-in clicks, press STRUM (Up/Down) or SPACE", 22, TEXT),
                ("exactly on every click. Listen - don't watch.", 22, TEXT),
                (f"At least {MIN_TAPS} taps are needed; the median error becomes the audio offset.", 18, TEXT_DIM),
                ("Use headphones / your normal speakers and play volume.", 18, TEXT_DIM),
            ])
            draw_hints(surf, a, [("Enter", "Start"), ("Tab", "Skip to video"), ("Esc", "Back")])
        elif p == "visual_intro":
            self._text_block(surf, panel, [
                ("VIDEO CALIBRATION", 30, NEON_CYAN),
                ("No sound this time. Markers fall onto the target line.", 22, TEXT),
                ("Press STRUM or SPACE exactly when a marker hits the line.", 22, TEXT),
                ("This measures display + input delay (video offset).", 18, TEXT_DIM),
            ])
            draw_hints(surf, a, [("Enter", "Start"), ("Esc", "Back")])
        elif p in ("audio", "visual"):
            self._draw_run(surf, panel)
            draw_hints(surf, a, [("Strum / Space", "Tap"), ("Esc", "Abort")])
        else:
            what = "AUDIO" if p == "audio_result" else "VIDEO"
            if self.result_ok:
                lines = [(f"{what} OFFSET", 26, NEON_CYAN), (f"{self.value_ms:+d} ms", 72, GOLD),
                         (self.result_msg, 18, TEXT_DIM)]
            else:
                lines = [("CALIBRATION FAILED", 30, (255, 110, 110)), (self.result_msg, 20, TEXT)]
            self._text_block(surf, panel, lines, top=34)
            if self.errors:
                self._draw_scatter(surf, pygame.Rect(panel.x + 120, panel.y + 212, panel.w - 240, 40))
            self.menu.draw(surf, a, 440)
            draw_hints(surf, a, [("Up/Down", "Select"), ("Enter", "Confirm")])

    def _text_block(self, surf, panel, lines, top=None) -> None:
        y = panel.y + (top if top is not None else 60)
        for text, size, col in lines:
            img = self.assets.text.render(text, size, col, "ui", size >= 26)
            surf.blit(img, (W // 2 - img.get_width() // 2, y))
            y += img.get_height() + 14

    def _draw_scatter(self, surf, r) -> None:
        pygame.draw.line(surf, (90, 86, 120), (r.x, r.centery), (r.right, r.centery), 1)
        pygame.draw.line(surf, (200, 200, 220), (r.centerx, r.y), (r.centerx, r.bottom), 1)
        for e in self.errors:
            x = r.centerx + max(-1.0, min(1.0, e / MATCH_WINDOW)) * r.w / 2
            pygame.draw.line(surf, NEON_ORANGE, (x, r.y + 8), (x, r.bottom - 8), 2)
        for ms in (-200, -100, 0, 100, 200):
            x = r.centerx + ms / 1000 / MATCH_WINDOW * r.w / 2
            img = self.assets.text.render(f"{ms:+d}" if ms else "0", 12, TEXT_DIM)
            surf.blit(img, (x - img.get_width() // 2, r.bottom + 2))

    def _draw_run(self, surf, panel) -> None:
        tc = self.assets.text
        t = self.song_t
        n_valid = 0
        for tp in self.taps:
            if any(abs(tp - c) <= MATCH_WINDOW for c in self.clicks[COUNT_IN - 1:]):
                n_valid += 1
        beat_i = self.last_click_i
        if self.phase == "audio":
            # nabiz: tikla birlikte parlayan halka
            age = self.t - self.flash_t
            k = math.exp(-max(0.0, age) * 7.0) if beat_i >= 0 else 0.0
            cx, cy = W // 2, panel.y + 230
            r = int(70 + 30 * k)
            col = lerp_color((60, 50, 100), NEON_PINK if beat_i % 4 == 0 else NEON_CYAN, k)
            pygame.draw.circle(surf, col, (cx, cy), r, 6)
            pygame.draw.circle(surf, lerp_color((20, 16, 40), col, k * 0.6), (cx, cy), r - 10)
            if beat_i < COUNT_IN - 1:
                txt = str(COUNT_IN - 1 - beat_i) if beat_i >= 0 else "Get ready..."
                img = tc.render(txt, 48 if beat_i >= 0 else 26, TEXT, "title", True)
            else:
                img = tc.render("TAP!", 44, TEXT, "title", True)
            surf.blit(img, (cx - img.get_width() // 2, cy - img.get_height() // 2))
        else:
            # dusen isaretler -> hedef cizgi
            line_y = panel.y + 380
            x0, x1 = W // 2 - 260, W // 2 + 260
            pygame.draw.line(surf, (230, 230, 245), (x0, line_y), (x1, line_y), 4)
            speed = 320.0
            for i, c in enumerate(self.clicks):
                dy = (c - t) * speed
                y = line_y - dy
                if panel.y + 20 < y < line_y + 30:
                    col = FRET_COLORS[i % 5]
                    pygame.draw.ellipse(surf, col, (W // 2 - 44, y - 16, 88, 32))
                    pygame.draw.ellipse(surf, (255, 255, 255), (W // 2 - 44, y - 16, 88, 32), 3)
            age = self.t - self.flash_t
            if 0 <= age < 0.15 and beat_i >= 0:
                k = 1 - age / 0.15
                pygame.draw.line(surf, lerp_color((230, 230, 245), NEON_CYAN, k), (x0 - 20, line_y), (x1 + 20, line_y),
                                 int(4 + 10 * k))
        # tap gostergesi
        age = self.t - self.tap_flash
        if 0 <= age < 0.12:
            pygame.draw.circle(surf, (255, 255, 255), (panel.right - 50, panel.y + 50), 14)
        prog = tc.render(f"taps: {n_valid} / {MIN_TAPS}+", 22, GOLD if n_valid >= MIN_TAPS else TEXT, "ui", True)
        surf.blit(prog, (panel.x + 30, panel.bottom - 50))
        remain = max(0, len(self.clicks) - 1 - beat_i)
        rm = tc.render(f"{remain} clicks left", 18, TEXT_DIM)
        surf.blit(rm, (panel.right - rm.get_width() - 30, panel.bottom - 46))
