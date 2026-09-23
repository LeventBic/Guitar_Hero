"""Oyun sahnesi: Conductor + GuitarEngine + highway/HUD; geri sayim, duraklatma, basarisizlik, bitis."""
from __future__ import annotations

import dataclasses
import math

import pygame

from ..audio import Conductor
from ..engine import EvType, GuitarEngine, InputEvent, InputKind, autoplay_inputs
from ..engine.rules import sustain_ends
from ..i18n import diff_name, section_label, t, upper
from ..render.assets import GOLD, H, NEON_ORANGE, NEON_PINK, TEXT, TEXT_DIM, W
from ..render.highway import HighwayRenderer
from ..render.hud import HUD
from ..render.ui import MenuList, StageBackground, draw_hints, draw_panel, fade_overlay
from .base import Scene

LEAD_IN = 2.7
COUNT_TICKS = (-2.4, -1.6, -0.8)
END_PAD = 2.2


class GameplayScene(Scene):
    blocks_import = True

    def __init__(self, app, info, difficulty: str, *, autoplay: bool = False, sim: bool = False,
                 video: bool | None = None):
        super().__init__(app)
        self.info = info
        self.difficulty = difficulty
        self.autoplay = autoplay
        self.sim = sim
        s = app.settings
        self.chart = app.library.chart(info.folder)
        if self.chart is None:
            raise RuntimeError(app.library.chart_error(info.folder) or f"cannot load {info.folder}")
        self.track = self.chart.track(difficulty)
        if self.track is None or not self.track.notes:
            raise RuntimeError(f"difficulty {difficulty} not in chart")
        self.cfg = dataclasses.replace(s.engine)
        self.engine = GuitarEngine(self.chart, self.track, self.cfg)
        cinfo = self.chart.info
        stems = cinfo.stems or info.stems
        self.conductor = Conductor(app.audio, stems, chart_offset=self.chart.offset,
                                   audio_offset=s.audio.audio_offset_ms / 1000.0,
                                   video_offset=s.video.video_offset_ms / 1000.0,
                                   lead_in=LEAD_IN, sim=sim)
        self.conductor.load()
        self.conductor.set_volume(s.audio.master_volume)
        self.notes = self.track.notes
        self.times = [n.time for n in self.notes]
        self.sus_end, _ = sustain_ends(self.notes)
        self.max_sus = max([e - n.time for n, e in zip(self.notes, self.sus_end)] + [0.0]) + 0.1
        last = max([self.sus_end[i] for i in range(len(self.notes))] + [n.time for n in self.notes] + [0.0])
        self.last_note_end = last
        self.end_trigger = last + END_PAD
        self.song_length = max(last + 1.0, self.chart.end_time,
                               (cinfo.song_length_ms or info.song_length_ms) / 1000.0 if (cinfo.song_length_ms or info.song_length_ms) else 0)
        bl = self.chart.tempo_map.beat_lines(self.end_trigger + 8)
        self.beat_times = [b.time for b in bl]
        self.beat_kinds = [b.kind for b in bl]
        self.sections = sorted(self.chart.sections, key=lambda x: x.time)
        self.section_i = 0
        self.section_marks = [x.time / self.song_length for x in self.sections if self.song_length > 0]
        self.title = cinfo.name or info.name
        self.artist = cinfo.artist or info.artist
        self.diff_label = upper(diff_name(difficulty)) + ("  -  " + t("common.bot") if autoplay else "")
        self.window = self.cfg.window_back
        self.lead_in = LEAD_IN
        self.bot_events = autoplay_inputs(self.track, self.cfg) if autoplay else []
        self.bot_i = 0
        # solo'lar
        self.solos = []
        for so in self.track.solos:
            if so.first_note >= 0 and so.last_note >= so.first_note:
                idxs = (so.first_note, so.last_note)
            else:
                ii = [i for i, n in enumerate(self.notes) if so.start_time <= n.time <= so.end_time]
                idxs = (ii[0], ii[-1]) if ii else (-1, -2)
            self.solos.append(idxs)
        self.cur_solo = None
        # render
        album = app.assets.album(cinfo.album_art or info.album_art, 512)
        self.stage = StageBackground(album)
        self.video = None
        if (not sim if video is None else video) and s.extra.get("bg_video", True):
            from ..video import open_background
            self.video = open_background(info.folder, f"{self.artist} - {self.title}", (W, H),
                                         start_offset_ms=cinfo.video_start_ms or info.video_start_ms)
        self.video_dim = pygame.Surface((W, H))
        self.highway = HighwayRenderer(app.assets, s)
        self.hud = HUD(app.assets, s)
        self.dropped: dict[int, bool] = {}
        self.display_score = 0
        self.rock_active = not self.cfg.no_fail
        self.show_debug = s.video.show_debug
        self.song_time = -LEAD_IN
        self.visual_time = -LEAD_IN
        self.beat_phase = 0.0
        self.beat_index = 0
        self.fps = 0.0
        self.frame_ms = 0.0
        self.drift = 0.0
        self.anchored = False
        self.audio_offset_ms = s.audio.audio_offset_ms
        self.video_offset_ms = s.video.video_offset_ms
        self.sp_ready_prev = False
        self.tick_i = 0
        self.state = "play"          # play | ending | failed | done
        self.end_clock = 0.0
        self.fail_clock = 0.0
        self.sp_phrases_done = 0
        self.result: dict | None = None
        self.done = False

    # ------------------------------------------------------------------ yasam dongusu
    def enter(self) -> None:
        self.app.audio.stop_preview(0)
        self.conductor.start()
        self.song_time = self.conductor.frame_time
        self.visual_time = self.conductor.visual_time()

    def video_time(self) -> float:
        """Arka plan videosu saati: hazir klipler (dongu) geri sayimda da akar; sarkinin kendi videosu ses dosyasinin
        konumunu izler (Clone Hero gibi): chart saati + chart.offset (.chart Offset + song.ini delay)."""
        return self.visual_time + (self.lead_in if self.video.loop else self.chart.offset)

    def exit(self) -> None:
        self.conductor.stop()
        if self.video is not None:
            self.video.close()
            self.video = None

    def resume(self) -> None:
        pass

    def restart(self) -> None:
        self.conductor.stop()
        self.app.replace(GameplayScene(self.app, self.info, self.difficulty, autoplay=self.autoplay, sim=self.sim))

    # ------------------------------------------------------------------ girdi
    def push_input(self, gi) -> None:
        if self.state != "play":
            return
        if self.autoplay:
            return
        t = self.conductor.song_time(gi.pc)
        self.engine.push(InputEvent(t, gi.kind, gi.fret, gi.value))

    def on_game(self, gi) -> None:
        self.push_input(gi)

    def on_menu(self, action: str) -> None:
        if action in ("PAUSE", "START") and self.state == "play":
            self.open_pause()

    def open_pause(self) -> None:
        if self.state != "play":
            return
        self.conductor.pause()
        self.app.push(PauseScene(self.app, self))

    # ------------------------------------------------------------------ guncelleme
    def update(self, dt: float) -> None:
        super().update(dt)
        c = self.conductor
        if self.sim:
            c.advance(dt)
        now = c.update()
        self.song_time = now
        self.visual_time = c.visual_time()
        self.show_debug = self.app.settings.video.show_debug
        self.fps = self.app.fps
        self.frame_ms = self.app.frame_ms
        self.drift = c.drift
        self.anchored = c.anchored
        # geri sayim
        pos = c.audio_pos()
        while self.tick_i < len(COUNT_TICKS) and pos >= COUNT_TICKS[self.tick_i]:
            if pos - COUNT_TICKS[self.tick_i] < 0.3:
                self.sfx("countdown_tick", 0.9)
                self.hud.popup(str(3 - self.tick_i), 110, (255, 255, 255), dur=0.75, y=320)
            self.tick_i += 1
        if self.state in ("play", "ending"):
            if self.autoplay:
                ev = self.bot_events
                lim = now + 0.03
                while self.bot_i < len(ev) and ev[self.bot_i].time <= lim:
                    self.engine.push(ev[self.bot_i])
                    self.bot_i += 1
            self.engine.update(now)
            self._handle_events(self.engine.pop_events())
        # beat
        tm = self.chart.tempo_map
        bp = tm.beat_position(max(0.0, self.visual_time))
        self.beat_index = int(bp)
        self.beat_phase = bp - self.beat_index
        # bolumler
        while self.section_i < len(self.sections) and self.sections[self.section_i].time <= self.visual_time:
            sec = self.sections[self.section_i]
            if self.visual_time - sec.time < 1.0:
                self.hud.banner(upper(section_label(sec.name)), dur=2.0, y=150)
            self.section_i += 1
        # SP hazir
        eng = self.engine
        ready = eng.sp_meter >= self.cfg.sp_activation_min - 1e-9 and not eng.sp_active
        if ready and not self.sp_ready_prev:
            self.sfx("sp_ready", 0.9)
            self.hud.popup(t("game.sp_ready"), 30, (140, 220, 255), dur=1.2, y=420)
        self.sp_ready_prev = ready
        # skor animasyonu
        diff = eng.score - self.display_score
        if diff > 0:
            self.display_score += max(1, int(math.ceil(diff * min(1.0, dt * 14))))
        else:
            self.display_score = eng.score
        self.highway.update(dt)
        self.hud.update(dt)
        # bitis
        if self.state == "play" and now >= self.end_trigger:
            self.state = "ending"
            self.end_clock = 0.0
            if eng.notes_missed == 0 and eng.overstrums == 0:
                self.hud.popup(t("game.full_combo"), 64, GOLD, dur=2.0, y=300)
            self.sfx("crowd_cheer", 0.8)
            self.conductor.fadeout(1800)
        if self.state == "ending":
            self.end_clock += dt
            if self.end_clock >= 1.9 or self.sim:
                self.finish()
        if self.state == "failed":
            self.fail_clock += dt

    def _handle_events(self, events) -> None:
        eng = self.engine
        hud = self.hud
        for ev in events:
            ty = ev.type
            if ty == EvType.HIT:
                self.highway.on_hit(ev.mask, eng.sp_active, self.visual_time)
                hud.on_hit_offset(ev.offset)
                self.conductor.set_guitar_muted(False)
                if eng.combo >= 50 and eng.combo % 50 == 0:
                    hud.popup(t("game.streak", n=eng.combo), 46, NEON_ORANGE, dur=1.5, y=300)
                if self.cur_solo is not None:
                    a, b = self.solos[self.cur_solo]
                    if a <= ev.note <= b:
                        hud.solo["hits"] += 1
            elif ty == EvType.MISS:
                self.conductor.set_guitar_muted(True)
            elif ty == EvType.OVERSTRUM:
                self.conductor.set_guitar_muted(True)
                self.sfx("miss_buzz", 0.8)
            elif ty == EvType.SUSTAIN_END:
                if ev.value < 0.5:
                    self.dropped[ev.note] = True
            elif ty == EvType.SP_PHRASE_COMPLETE:
                self.sp_phrases_done += 1
                self.sfx("sp_phrase_complete", 0.9)
            elif ty == EvType.SP_ACTIVATED:
                self.sfx("sp_activate", 1.0)
                self.highway.on_sp_activate(self.visual_time)
                hud.popup(t("game.sp"), 58, (120, 220, 255), dur=1.3, y=300)
            elif ty == EvType.SP_ENDED:
                self.sfx("sp_deactivate", 0.8)
            elif ty == EvType.MULTIPLIER_CHANGED:
                hud.on_mult()
            elif ty == EvType.SOLO_START:
                idx = None
                for k, (a, b) in enumerate(self.solos):
                    if a <= ev.note <= b:
                        idx = k
                        break
                if idx is None and self.solos:
                    idx = min(len(self.solos) - 1, sum(1 for s in self.track.solos if s.start_time <= ev.time + 1e-6) - 1)
                self.cur_solo = idx
                if idx is not None:
                    a, b = self.solos[idx]
                    hud.solo = {"hits": 0, "total": max(0, b - a + 1)}
                hud.popup(t("game.solo"), 50, NEON_ORANGE, dur=1.6, y=250)
            elif ty == EvType.SOLO_END:
                pct = ev.value
                if pct >= 99.999:
                    key, col = "game.solo_perfect", GOLD
                elif pct >= 90:
                    key, col = "game.solo_awesome", (120, 230, 255)
                elif pct >= 75:
                    key, col = "game.solo_great", (120, 240, 140)
                elif pct >= 50:
                    key, col = "game.solo_good", TEXT
                else:
                    key, col = "game.solo_messy", (240, 120, 120)
                hud.popup(f"{t(key)}  {int(pct)}%", 48, col, dur=2.2, y=250)
                hud.solo = None
                self.cur_solo = None
            elif ty == EvType.FAILED:
                self.fail()

    def fail(self) -> None:
        if self.state == "failed":
            return
        self.state = "failed"
        self.fail_clock = 0.0
        self.conductor.fadeout(900)
        self.sfx("fail_sound", 1.0)
        if self.sim:
            self.finish(failed=True)
            return
        self.app.push(FailScene(self.app, self))

    def stats(self, failed: bool = False) -> dict:
        eng = self.engine
        return {
            "title": self.title, "artist": self.artist, "difficulty": self.difficulty,
            "score": eng.score, "stars": eng.stars(), "notes_hit": eng.notes_hit, "total": eng.total_notes,
            "missed": eng.notes_missed, "max_combo": eng.max_combo, "overstrums": eng.overstrums,
            "sp_done": self.sp_phrases_done, "sp_total": len(self.track.sp_phrases),
            "offsets": list(eng.hit_offsets), "failed": failed, "autoplay": self.autoplay,
            "fc": eng.max_combo == eng.total_notes and eng.overstrums == 0 and eng.notes_missed == 0,
            "info": self.info, "album": self.chart.info.album_art or self.info.album_art,
            "progress": min(1.0, max(0.0, self.song_time / max(1e-6, self.last_note_end))),
        }

    def finish(self, failed: bool = False) -> None:
        if self.done:
            return
        self.done = True
        self.result = self.stats(failed)
        if self.sim:
            return
        from .results import ResultsScene
        self.app.replace(ResultsScene(self.app, self.result))

    # ------------------------------------------------------------------ cizim
    def draw(self, surf: pygame.Surface) -> None:
        frame = None
        if self.video is not None:
            vt = self.video_time()
            frame = self.video.frame(vt)
        if frame is not None:
            surf.blit(frame, (0, 0))
            # otoban okunabilir kalsin: karart (SP'de hafif mavi), ritimde cok hafif nabiz
            pulse = max(0.0, 1.0 - self.beat_phase * 4.0)
            k = int(92 + 18 * pulse)
            self.video_dim.fill((k - 18, k - 8, k + 30) if self.engine.sp_active else (k, k, k + 6))
            surf.blit(self.video_dim, (0, 0), special_flags=pygame.BLEND_MULT)
        else:
            self.stage.draw(surf, self.beat_phase, self.beat_index, self.engine.sp_active)
        self.highway.draw(surf, self)
        self.hud.draw(surf, self)


# ---------------------------------------------------------------------------- duraklatma

class PauseScene(Scene):
    opaque = False
    blocks_import = True

    def __init__(self, app, game: GameplayScene):
        super().__init__(app)
        self.game = game
        self.menu = MenuList(["pause.resume", "pause.restart", "pause.settings", "pause.quit"], W // 2, 318, spacing=54,
                             size=32)

    def on_game(self, gi) -> None:
        # perde birakma/basmalari motora ilet (duraklatmada basili kalan perde takilmasin)
        if gi.kind in (InputKind.FRET_DOWN, InputKind.FRET_UP):
            if not self.game.autoplay:
                t = self.game.conductor.song_time(gi.pc)
                self.game.engine.push(InputEvent(t, gi.kind, gi.fret, gi.value))

    def on_menu(self, action: str) -> None:
        if action == "UP":
            self.menu.move(-1)
            self.sfx("menu_move")
        elif action == "DOWN":
            self.menu.move(1)
            self.sfx("menu_move")
        elif action in ("BACK", "PAUSE"):
            self._resume()
        elif action == "CONFIRM":
            i = self.menu.index
            self.sfx("menu_select")
            if i == 0:
                self._resume()
            elif i == 1:
                self.app.pop()
                self.game.restart()
            elif i == 2:
                from .settings import SettingsScene
                self.app.push(SettingsScene(self.app, in_game=True))
            else:
                self.app.pop()
                self.game.conductor.stop()
                self.app.back_to_songlist()

    def _resume(self) -> None:
        self.app.pop()
        self.game.conductor.resume()

    def update(self, dt: float) -> None:
        super().update(dt)
        self.menu.update(dt)

    def draw(self, surf: pygame.Surface) -> None:
        fade_overlay(surf, 170, (6, 4, 16))
        draw_panel(surf, (W // 2 - 280, 150, 560, 400), border=NEON_PINK, fill=(14, 13, 11, 200))
        img = self.assets.text.glow(t("pause.title"), 72, (255, 204, 124), glow_color=NEON_PINK)
        surf.blit(img, (W // 2 - img.get_width() // 2, 170))
        sub = self.assets.text.render(f"{self.game.title}  -  {self.game.artist}", 22, TEXT_DIM)
        surf.blit(sub, (W // 2 - sub.get_width() // 2, 262))
        self.menu.draw(surf, self.assets, 460)
        draw_hints(surf, self.assets, [("key.updown", "hint.select"), ("Enter", "hint.confirm"), ("Esc", "hint.resume")])


class FailScene(Scene):
    opaque = False
    blocks_import = True

    def __init__(self, app, game: GameplayScene):
        super().__init__(app)
        self.game = game
        self.menu = MenuList(["fail.retry", "fail.results", "pause.quit"], W // 2, 400, spacing=60, size=32)

    def on_menu(self, action: str) -> None:
        if self.t < 0.8:
            return
        if action == "UP":
            self.menu.move(-1)
            self.sfx("menu_move")
        elif action == "DOWN":
            self.menu.move(1)
            self.sfx("menu_move")
        elif action == "CONFIRM":
            self.sfx("menu_select")
            i = self.menu.index
            self.app.pop()
            if i == 0:
                self.game.restart()
            elif i == 1:
                self.game.finish(failed=True)
            else:
                self.game.conductor.stop()
                self.app.back_to_songlist()

    def update(self, dt: float) -> None:
        super().update(dt)
        self.menu.update(dt)

    def draw(self, surf: pygame.Surface) -> None:
        k = min(1.0, self.t / 0.8)
        fade_overlay(surf, int(190 * k), (30, 0, 8))
        img = self.assets.text.glow(t("fail.title"), 84, (255, 80, 90), glow_color=(255, 20, 40))
        y = 200 - int((1 - k) * 60)
        surf.blit(img, (W // 2 - img.get_width() // 2, y))
        g = self.game
        prog = g.song_time / max(1e-6, g.last_note_end)
        sub = self.assets.text.render(t("fail.progress", p=int(max(0, min(1, prog)) * 100)), 24, TEXT_DIM)
        surf.blit(sub, (W // 2 - sub.get_width() // 2, 310))
        if self.t >= 0.8:
            self.menu.draw(surf, self.assets, 460)
