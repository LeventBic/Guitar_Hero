"""Sarki listesi (album kapagi, bilgi, onizleme sesi) ve zorluk / secenek secimi."""
from __future__ import annotations

import math
import os

import pygame

from ..config import DIFFICULTIES
from ..i18n import diff_name, t, upper
from ..library import available_difficulties, fmt_time, song_roots
from ..render.assets import NEON_CYAN, NEON_ORANGE, NEON_PINK, NEON_PURPLE, TEXT, TEXT_DIM, W
from ..render.ui import SynthBackground, draw_hints, draw_panel, fade_overlay
from ..settings_store import save_settings
from .base import Scene

ROW_H = 58
VISIBLE = 9
DIFF_COLORS = {"easy": (80, 220, 110), "medium": (245, 205, 40), "hard": (250, 140, 40), "expert": (240, 70, 80)}


class SongListScene(Scene):
    def __init__(self, app, select_folder: str | None = None):
        super().__init__(app)
        self.bg = SynthBackground()
        self.songs = app.library.scan()
        self.index = 0
        self.chart = None
        self.diffs: list[str] = []
        self._loaded_for = None
        self._select(select_folder or app.settings.extra.get("last_song", ""))
        self.scroll = float(max(0, self.index - VISIBLE // 2))
        self.dwell = 0.0
        self.preview_started = False

    def _select(self, folder: str | None) -> None:
        if not folder:
            return
        key = os.path.normcase(os.path.realpath(folder))
        for i, s in enumerate(self.songs):
            if os.path.normcase(os.path.realpath(s.folder)) == key:
                self.index = i
                return

    def refresh(self, select_folder: str | None = None) -> None:
        """Kutuphaneyi yeniden tara (ice aktarma / yeniden chart'lama sonrasi) ve istenen sarkiyi sec."""
        cur = self.sel.folder if self.sel else None
        if select_folder:
            self.app.library.invalidate(select_folder)
        self.songs = self.app.library.scan()
        self.index = min(self.index, max(0, len(self.songs) - 1))
        self._select(cur)
        self._select(select_folder)
        self._loaded_for = None
        self.chart = None
        self.diffs = []
        self._load_selected()
        self.scroll = float(min(max(0, self.index - VISIBLE // 2), max(0, len(self.songs) - VISIBLE)))

    def open_difficulty(self) -> None:
        self._load_selected()
        if self.sel is None or not self.diffs:
            return
        self.app.settings.extra["last_song"] = self.sel.folder
        self.app.push(DifficultyScene(self.app, self))

    def enter(self) -> None:
        self._load_selected()
        if self.app.check_inbox():          # Songs/_Import'ta yeni dosya varsa once onlari ekle
            self.preview_started = True

    def resume(self) -> None:
        self.dwell = 0.0
        self.preview_started = False

    def on_shortcut(self, key: int) -> None:
        if key == pygame.K_d:
            from .setlists import SetlistScene
            self.sfx("menu_select")
            self.app.audio.stop_preview(150)
            self.app.push(SetlistScene(self.app))
            return
        if key == pygame.K_i:
            from .importer import ImportScene
            self.sfx("menu_select")
            self.app.audio.stop_preview(150)
            self.app.push(ImportScene(self.app))
        elif key == pygame.K_r and self.sel is not None:
            s = self.sel
            if not s.auto_chart:
                self.sfx("miss_buzz", 0.5)
                return
            from .importer import ConfirmScene, ImportScene
            self.sfx("menu_select")
            folder = s.folder

            def go():
                self.app.audio.stop_preview(150)
                self.app.push(ImportScene(self.app, rechart=folder))

            self.app.push(ConfirmScene(self.app, "songs.rechart_title",
                                       [s.name, "songs.rechart_line1", "songs.rechart_line2"], go))

    def exit(self) -> None:
        self.app.audio.stop_preview(300)

    @property
    def sel(self):
        return self.songs[self.index] if self.songs else None

    def _load_selected(self) -> None:
        s = self.sel
        if s is None or self._loaded_for == s.folder:
            return
        self._loaded_for = s.folder
        self.chart = self.app.library.chart(s.folder)
        self.diffs = available_difficulties(self.chart)

    def on_menu(self, action: str) -> None:
        if action == "BACK":
            self.sfx("menu_back")
            self.app.pop()
            return
        if action == "OPTION":
            from .settings import SettingsScene
            self.sfx("menu_select")
            self.app.audio.stop_preview(150)
            self.preview_started = False
            self.dwell = 0.0
            self.app.push(SettingsScene(self.app))
            return
        if not self.songs:
            return
        if action in ("UP", "DOWN", "LEFT", "RIGHT"):
            d = {"UP": -1, "DOWN": 1, "LEFT": -VISIBLE, "RIGHT": VISIBLE}[action]
            if action in ("UP", "DOWN"):
                self.index = (self.index + d) % len(self.songs)
            elif self._multi_setlist():
                self.index = self._setlist_jump(-1 if action == "LEFT" else 1)
            else:
                self.index = max(0, min(len(self.songs) - 1, self.index + d))
            self.sfx("menu_move", 0.8)
            self.dwell = 0.0
            self.preview_started = False
            self.app.audio.stop_preview(250)
        elif action == "CONFIRM":
            self._load_selected()
            if not self.diffs:
                self.sfx("miss_buzz", 0.5)
                return
            self.sfx("menu_select")
            self.app.settings.extra["last_song"] = self.sel.folder
            self.app.push(DifficultyScene(self.app, self))

    def _multi_setlist(self) -> bool:
        return len({s.setlist for s in self.songs}) > 1

    def _setlist_jump(self, d: int) -> int:
        """Sol / sag: onceki / sonraki setlist'in ilk sarkisi (setlist ortasindaysa once kendi basina)."""
        cur = self.songs[self.index].setlist
        start = self.index
        while start > 0 and self.songs[start - 1].setlist == cur:
            start -= 1
        if d < 0:
            if self.index != start:
                return start
            if start == 0:
                return self._setlist_start(len(self.songs) - 1)
            return self._setlist_start(start - 1)
        i = self.index
        while i < len(self.songs) and self.songs[i].setlist == cur:
            i += 1
        return i if i < len(self.songs) else 0

    def _setlist_start(self, i: int) -> int:
        cur = self.songs[i].setlist
        while i > 0 and self.songs[i - 1].setlist == cur:
            i -= 1
        return i

    def update(self, dt: float) -> None:
        super().update(dt)
        self.bg.update(dt)
        target = min(max(0, self.index - VISIBLE // 2), max(0, len(self.songs) - VISIBLE))
        self.scroll += (target - self.scroll) * min(1.0, dt * 14)
        self.dwell += dt
        if self.dwell > 0.18:
            self._load_selected()
        if self.dwell > 0.45 and not self.preview_started and self.sel is not None and self.app.top is self:
            self.preview_started = True
            s = self.sel
            path = s.stems.get("preview") or s.stems.get("song") or next(iter(s.stems.values()), "")
            start = s.preview_start_ms / 1000.0 if s.preview_start_ms > 0 else 20.0
            self.app.audio.play_preview(path, start)

    def _auto_badge(self, surf, right: int, y: int, mode: str = "") -> int:
        """Sag kenari `right` olan kucuk rozet: 'GITAR' (ayristirilan gitardan chart) ya da 'OTO' (miksten);
        rozetin sol kenarini dondurur."""
        guitar = mode == "guitar"
        img = self.assets.text.render(t("songs.guitar" if guitar else "songs.auto"), 13, (20, 14, 30), "ui", True)
        r = pygame.Rect(0, y, img.get_width() + 14, 22)
        r.right = right
        pygame.draw.rect(surf, NEON_ORANGE if guitar else NEON_CYAN, r, border_radius=6)
        surf.blit(img, (r.x + 7, r.centery - img.get_height() // 2))
        return r.x - 10

    def draw(self, surf: pygame.Surface) -> None:
        a = self.assets
        tc = a.text
        self.bg.draw(surf, 0.2)
        shade = pygame.Surface((W, 720), pygame.SRCALPHA)
        shade.fill((4, 2, 14, 150))
        surf.blit(shade, (0, 0))
        head = tc.glow(t("songs.title"), 42, (255, 214, 140), glow_color=NEON_PINK, radius=8)
        surf.blit(head, (40, 14))
        if self.songs and self._multi_setlist():
            cur = self.sel.setlist
            n_in = sum(1 for x in self.songs if x.setlist == cur)
            grp = tc.render(upper(cur or t("songs.my_songs")), 20, NEON_CYAN, "ui", True)
            cnt = tc.render(t("songs.count_group", n=n_in, total=len(self.songs)), 16, TEXT_DIM)
            surf.blit(grp, (620 - grp.get_width(), 22))
            surf.blit(cnt, (620 - cnt.get_width(), 48))
        else:
            cnt = tc.render(t("songs.count", n=len(self.songs)), 18, TEXT_DIM)
            surf.blit(cnt, (620 - cnt.get_width(), 38))
        if not self.songs:
            draw_panel(surf, (140, 200, 1000, 260))
            m1 = tc.render(t("songs.none"), 34, TEXT, "ui", True)
            surf.blit(m1, (W // 2 - m1.get_width() // 2, 250))
            roots = song_roots()
            m2 = tc.render(t("songs.none_hint"), 20, TEXT_DIM)
            surf.blit(m2, (W // 2 - m2.get_width() // 2, 320))
            for i, r in enumerate(roots[:2]):
                m3 = tc.render(os.path.abspath(r), 18, NEON_CYAN)
                surf.blit(m3, (W // 2 - m3.get_width() // 2, 356 + i * 26))
            m4 = tc.render(t("songs.none_drop"), 20, NEON_ORANGE)
            surf.blit(m4, (W // 2 - m4.get_width() // 2, 420))
            draw_hints(surf, a, [("I", "hint.import_songs"), ("Esc", "hint.back")])
            return
        # liste
        list_rect = pygame.Rect(30, 80, 600, ROW_H * VISIBLE + 16)
        draw_panel(surf, list_rect, border=NEON_PURPLE)
        clip = surf.get_clip()
        surf.set_clip(list_rect.inflate(-6, -6))
        first = int(self.scroll)
        for i in range(first, min(len(self.songs), first + VISIBLE + 2)):
            s = self.songs[i]
            y = list_rect.y + 8 + (i - self.scroll) * ROW_H
            sel = i == self.index
            row = pygame.Rect(list_rect.x + 8, int(y), list_rect.w - 16, ROW_H - 6)
            if i > 0 and self.songs[i - 1].setlist != s.setlist:
                # setlist siniri: ince kehribar cizgi + setlist adi (sagda, kucuk)
                ly = int(y) - 4
                pygame.draw.line(surf, NEON_CYAN, (row.x + 6, ly), (row.right - 6, ly), 1)
                tag = tc.render(s.setlist or t("songs.my_songs"), 12, NEON_CYAN, "ui", True)
                tb = pygame.Rect(row.right - tag.get_width() - 18, ly - 8, tag.get_width() + 12, 16)
                pygame.draw.rect(surf, (24, 20, 16), tb, border_radius=6)
                surf.blit(tag, (tb.x + 6, tb.y + 1))
            if sel:
                k = 0.5 + 0.5 * math.sin(self.t * 4)
                hl = pygame.Surface(row.size, pygame.SRCALPHA)
                pygame.draw.rect(hl, (255, 118, 30, 70 + int(30 * k)), (0, 0, *row.size), border_radius=10)
                pygame.draw.rect(hl, (255, 176, 72, 230), (0, 0, *row.size), 2, border_radius=10)
                surf.blit(hl, row.topleft)
            n = tc.render(s.name, 24, (255, 255, 255) if sel else TEXT, "ui", True)
            ar = tc.render(s.artist, 16, NEON_CYAN if sel else TEXT_DIM)
            right = row.right - 14
            if s.song_length_ms:
                ln = tc.render(fmt_time(s.song_length_ms / 1000), 18, TEXT_DIM)
                surf.blit(ln, (right - ln.get_width(), row.y + 16))
                right -= ln.get_width() + 12
            if s.auto_chart:
                right = self._auto_badge(surf, right, row.y + 15, s.auto_chart_mode)
            maxw = right - (row.x + 14) - 8
            if n.get_width() > maxw > 40:
                n = n.subsurface((0, 0, maxw, n.get_height()))
            surf.blit(n, (row.x + 14, row.y + 3))
            surf.blit(ar, (row.x + 14, row.y + 31))
        surf.set_clip(clip)
        # detay paneli
        s = self.sel
        det = pygame.Rect(660, 80, 590, 590)
        draw_panel(surf, det, border=NEON_CYAN)
        art = a.album(s.album_art, 250)
        ax, ay = det.x + 24, det.y + 24
        if art is not None:
            surf.blit(art, (ax, ay))
        else:
            pygame.draw.rect(surf, (39, 34, 29), (ax, ay, 250, 250), border_radius=8)
            q = a.logo(230) or tc.glow("GH", 60, (255, 206, 120), glow_color=NEON_PINK)
            surf.blit(q, (ax + 125 - q.get_width() // 2, ay + 125 - q.get_height() // 2))
        pygame.draw.rect(surf, (200, 200, 230), (ax - 2, ay - 2, 254, 254), 2, border_radius=4)
        tx = ax + 272
        wmax = det.right - tx - 16
        y = ay
        for text, size, col, bold in ((s.name, 30, TEXT, True), (s.artist, 22, NEON_CYAN, False)):
            img = tc.render(text, size, col, "ui", bold)
            if img.get_width() > wmax:
                img = pygame.transform.smoothscale(img, (wmax, int(img.get_height() * wmax / img.get_width())))
            surf.blit(img, (tx, y))
            y += img.get_height() + 6
        y += 8
        meta = []
        if s.album:
            meta.append(("songs.album", s.album))
        if s.year:
            meta.append(("songs.year", s.year))
        if s.genre:
            meta.append(("songs.genre", s.genre))
        auto = "  " + t("songs.auto_suffix") if s.auto_chart and "auto" not in (s.charter or "").lower() else ""
        meta.append(("songs.charter", (s.charter or t("common.unknown")) + auto))
        if s.song_length_ms:
            meta.append(("songs.length", fmt_time(s.song_length_ms / 1000)))
        lab_w = max(80, max(tc.render(upper(t(k)), 14, TEXT_DIM, "ui", True).get_width() for k, _v in meta) + 12)
        for lab, val in meta:
            l = tc.render(upper(t(lab)), 14, TEXT_DIM, "ui", True)
            v = tc.render(str(val), 18, TEXT)
            surf.blit(l, (tx, y + 3))
            surf.blit(v, (tx + lab_w, y))
            y += 28
        if s.diff_guitar >= 0:
            l = tc.render(t("songs.intensity"), 14, TEXT_DIM, "ui", True)
            surf.blit(l, (tx, y + 3))
            for k in range(6):
                c = NEON_ORANGE if k < s.diff_guitar else (61, 54, 46)
                pygame.draw.circle(surf, c, (tx + max(90, lab_w + 10) + k * 20, y + 11), 7)
        # zorluklar
        y2 = ay + 280
        l = tc.render(t("songs.difficulties"), 16, TEXT_DIM, "ui", True)
        surf.blit(l, (ax, y2))
        y2 += 28
        x = ax
        for d in DIFFICULTIES:
            have = d in self.diffs
            col = DIFF_COLORS[d] if have else (73, 64, 54)
            chip = tc.render(upper(diff_name(d)), 18, (15, 12, 25) if have else (100, 96, 120), "ui", True)
            r = pygame.Rect(x, y2, chip.get_width() + 24, 32)
            pygame.draw.rect(surf, col, r, border_radius=16)
            surf.blit(chip, (r.x + 12, r.y + 6))
            x = r.right + 10
        if self.chart is not None:
            y3 = y2 + 52
            for d in self.diffs:
                tr = self.chart.tracks[d]
                name = tc.render(diff_name(d), 18, TEXT_DIM, "ui", True)
                txt = t("songs.track_line", notes=len(tr.notes), sp=len(tr.sp_phrases)) + (
                    "   " + t("songs.solo", n=len(tr.solos)) if tr.solos else "")
                img = tc.render(txt, 18, TEXT_DIM, "ui")
                surf.blit(name, (ax, y3))
                surf.blit(img, (ax + 90, y3))
                y3 += 26
        elif self._loaded_for == s.folder:
            err = self.app.library.chart_error(s.folder)
            img = tc.render(t("songs.chart_error", err=err)[:70], 16, (255, 120, 120))
            surf.blit(img, (ax, y2 + 52))
        # on izleme gostergesi
        if self.preview_started:
            for k in range(5):
                h = 6 + 10 * abs(math.sin(self.t * 6 + k * 1.3))
                pygame.draw.rect(surf, NEON_PINK, (det.right - 60 + k * 8, det.bottom - 24 - h, 5, h))
        hints = [("key.updown", "hint.move")]
        if self._multi_setlist():
            hints.append(("key.leftright", "hint.setlist"))
        hints += [("key.enter_green", "hint.select"), ("Tab", "hint.settings"), ("I", "hint.import"),
                  ("D", "hint.setlists")]
        if s.auto_chart:
            hints.append(("R", "hint.rechart"))
        hints.append(("key.esc_red", "hint.back"))
        draw_hints(surf, a, hints)


class DifficultyScene(Scene):
    """Zorluk + secenekler (No Fail, not hizi, bot)."""
    opaque = False

    def __init__(self, app, songlist: SongListScene):
        super().__init__(app)
        self.sl = songlist
        self.info = songlist.sel
        self.diffs = list(songlist.diffs)
        last = app.settings.extra.get("last_difficulty", "expert")
        self.index = self.diffs.index(last) if last in self.diffs else len(self.diffs) - 1
        self.rows = [("diff", d) for d in self.diffs] + [("opt", "nofail"), ("opt", "speed"), ("opt", "bot")]

    def on_menu(self, action: str) -> None:
        s = self.app.settings
        kind, val = self.rows[self.index]
        if action == "BACK":
            self.sfx("menu_back")
            save_settings(s)
            self.app.pop()
        elif action == "UP":
            self.index = (self.index - 1) % len(self.rows)
            self.sfx("menu_move")
        elif action == "DOWN":
            self.index = (self.index + 1) % len(self.rows)
            self.sfx("menu_move")
        elif action in ("LEFT", "RIGHT", "CONFIRM", "OPTION"):
            if kind == "diff":
                if action == "CONFIRM":
                    self._start(val)
                return
            d = -1 if action == "LEFT" else 1
            if val == "nofail":
                s.engine.no_fail = not s.engine.no_fail
            elif val == "speed":
                if action == "CONFIRM":
                    d = 1
                v = round(s.video.note_speed + 0.1 * d, 2)
                if v > 3.0:
                    v = 0.5
                s.video.note_speed = max(0.5, min(3.0, v))
            elif val == "bot":
                s.extra["autoplay"] = not s.extra.get("autoplay", False)
            self.sfx("menu_move")

    def _start(self, diff: str) -> None:
        s = self.app.settings
        s.extra["last_difficulty"] = diff
        save_settings(s)
        self.sfx("menu_select")
        from .gameplay import GameplayScene
        # yukleme ekrani bir frame goster
        surf = self.app.screen
        fade_overlay(surf, 200, (4, 2, 12))
        img = self.assets.text.glow(t("diffsel.loading"), 48, (255, 214, 140), glow_color=NEON_PINK)
        surf.blit(img, (W // 2 - img.get_width() // 2, 330))
        if not self.app.headless:
            pygame.display.flip()
        try:
            game = GameplayScene(self.app, self.info, diff, autoplay=bool(s.extra.get("autoplay")))
        except Exception as exc:
            self.error = str(exc)
            self.sfx("miss_buzz")
            return
        self.app.pop()
        self.app.push(game)

    def update(self, dt: float) -> None:
        super().update(dt)

    def draw(self, surf: pygame.Surface) -> None:
        a = self.assets
        tc = a.text
        fade_overlay(surf, 150, (4, 2, 12))
        panel = pygame.Rect(W // 2 - 300, 110, 600, 520)
        draw_panel(surf, panel, border=NEON_PINK)
        ti = tc.render(self.info.name, 30, TEXT, "ui", True)
        surf.blit(ti, (W // 2 - ti.get_width() // 2, panel.y + 20))
        ar = tc.render(self.info.artist, 18, NEON_CYAN)
        surf.blit(ar, (W // 2 - ar.get_width() // 2, panel.y + 58))
        s = self.app.settings
        y = panel.y + 100
        for i, (kind, val) in enumerate(self.rows):
            sel = i == self.index
            if kind == "opt" and self.rows[i - 1][0] == "diff":
                y += 16
                pygame.draw.line(surf, (89, 78, 67), (panel.x + 40, y - 10), (panel.right - 40, y - 10), 1)
            r = pygame.Rect(panel.x + 30, y, panel.w - 60, 46)
            if sel:
                k = 0.5 + 0.5 * math.sin(self.t * 5)
                hl = pygame.Surface(r.size, pygame.SRCALPHA)
                pygame.draw.rect(hl, (255, 118, 30, 60 + int(40 * k)), (0, 0, *r.size), border_radius=10)
                pygame.draw.rect(hl, (255, 176, 72, 230), (0, 0, *r.size), 2, border_radius=10)
                surf.blit(hl, r.topleft)
            if kind == "diff":
                col = DIFF_COLORS[val]
                pygame.draw.circle(surf, col, (r.x + 26, r.centery), 9)
                lab = tc.render(upper(diff_name(val)), 28 if sel else 26, (255, 255, 255) if sel else TEXT, "title", True)
                surf.blit(lab, (r.x + 48, r.centery - lab.get_height() // 2))
                chart = self.sl.chart
                if chart is not None:
                    n = tc.render(t("diffsel.notes", n=len(chart.tracks[val].notes)), 18, TEXT_DIM)
                    surf.blit(n, (r.right - n.get_width() - 16, r.centery - n.get_height() // 2))
            else:
                names = {"nofail": "diffsel.no_fail", "speed": "diffsel.speed", "bot": "diffsel.bot"}
                if val == "nofail":
                    v = t("common.on") if s.engine.no_fail else t("common.off")
                elif val == "speed":
                    v = f"{s.video.note_speed:.1f}x"
                else:
                    v = t("common.on") if s.extra.get("autoplay") else t("common.off")
                lab = tc.render(t(names[val]), 22, TEXT if sel else TEXT_DIM, "ui", True)
                surf.blit(lab, (r.x + 20, r.centery - lab.get_height() // 2))
                vs = tc.render(f"<  {v}  >" if sel else v, 22, NEON_ORANGE if sel else TEXT, "ui", True)
                surf.blit(vs, (r.right - vs.get_width() - 16, r.centery - vs.get_height() // 2))
            y += 52
        err = getattr(self, "error", "")
        if err:
            e = tc.render(err[:80], 16, (255, 120, 120))
            surf.blit(e, (W // 2 - e.get_width() // 2, panel.bottom - 30))
        draw_hints(surf, a, [("key.updown", "hint.select"), ("key.leftright", "hint.change"),
                             ("key.enter_green", "hint.play"), ("key.esc_red", "hint.back")])
