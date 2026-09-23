"""Setlist indirici: hazir Guitar Hero setlist'lerini (assets/setlists.json) Chorus Encore'dan tek tikla indirir.

Satirlar: TUM SETLIST'LER + her oyun (yil sirali). Enter: eksik sarkilari indir (onay), Esc: geri / iptal.
Sarkilar Songs\\<setlist klasoru> altina iner; kurulu olanlar (song.ini chorus_md5) atlanir.
"""
from __future__ import annotations

import os
import shutil

import pygame

from ..i18n import t, upper
from ..library import fmt_time
from ..render.assets import NEON_CYAN, NEON_ORANGE, NEON_PINK, NEON_PURPLE, TEXT, TEXT_DIM, W
from ..render.ui import SynthBackground, draw_hints, draw_panel
from ..setlists import Downloader, fmt_size, load_setlists, pending_jobs
from .base import Scene

ROW_H = 50
VISIBLE = 11
GOOD = (110, 220, 120)


class SetlistScene(Scene):
    def __init__(self, app):
        super().__init__(app)
        from ..importer import songs_dir
        self.bg = SynthBackground()
        self.root = songs_dir()
        self.setlists = load_setlists()
        self.index = 0
        self.scroll = 0.0
        self.mode = "browse"            # browse | download | done
        self.dl: Downloader | None = None
        self.message = ""
        self.changed = False
        self.refresh()

    # ------------------------------------------------------------ durum
    def refresh(self) -> None:
        from ..chorus import installed_md5s
        self.installed = installed_md5s(self.root)

    def rows(self) -> list:
        return [None] + self.setlists          # None = tum setlist'ler

    def _sel_lists(self):
        s = self.rows()[self.index]
        return self.setlists if s is None else [s]

    def _counts(self, lists) -> tuple[int, int, int]:
        """(kurulu, toplam, kalan bayt)"""
        tot = sum(len(s.songs) for s in lists)
        have = sum(1 for s in lists for x in s.songs if x.md5 in self.installed)
        rem = sum(x.size for s in lists for x in s.songs if x.md5 not in self.installed)
        return have, tot, rem

    def _free(self) -> int:
        try:
            os.makedirs(self.root, exist_ok=True)
            return shutil.disk_usage(self.root).free
        except OSError:
            return 0

    # ------------------------------------------------------------ girdi
    def on_menu(self, action: str) -> None:
        if self.mode == "download":
            if action == "BACK" and self.dl is not None and not self.dl.cancel_event.is_set():
                self.dl.cancel()
                self.sfx("menu_back")
            return
        if self.mode == "done":
            if action in ("CONFIRM", "BACK"):
                self.mode = "browse"
                self.sfx("menu_select")
            return
        if action == "BACK":
            self.sfx("menu_back")
            self.app.pop()
        elif action in ("UP", "DOWN"):
            self.index = (self.index + (-1 if action == "UP" else 1)) % len(self.rows())
            self.sfx("menu_move", 0.8)
        elif action == "CONFIRM":
            self._ask_start()

    def _ask_start(self) -> None:
        lists = self._sel_lists()
        have, tot, rem = self._counts(lists)
        if have >= tot:
            self.sfx("miss_buzz", 0.5)
            self.message = t("dl.all_installed")
            return
        need, free = int(rem * 1.1), self._free()
        if free and need > free:
            self.sfx("miss_buzz", 0.5)
            self.message = t("dl.nospace", need=fmt_size(need), free=fmt_size(free))
            return
        from .importer import ConfirmScene
        name = t("dl.all") if len(lists) > 1 else lists[0].name
        self.sfx("menu_select")
        self.app.push(ConfirmScene(self.app, "dl.confirm_title",
                                   [name, t("dl.confirm_line", n=tot - have, size=fmt_size(rem)), "dl.note"],
                                   lambda: self._start(lists)))

    def _start(self, lists) -> None:
        jobs = pending_jobs(lists, self.installed)
        if not jobs:
            return
        self.dl = Downloader(jobs, self.root)
        self.dl.start()
        self.mode = "download"
        self.message = ""

    def exit(self) -> None:
        if self.dl is not None and not self.dl.finished:
            self.dl.cancel()
            self.dl.join(3.0)
        if self.changed:
            below = self.app.stack[-2] if len(self.app.stack) >= 2 else None
            if below is not None and hasattr(below, "refresh") and below is not self:
                try:
                    below.refresh()
                except Exception:
                    pass

    # ------------------------------------------------------------ dongu
    def update(self, dt: float) -> None:
        super().update(dt)
        self.bg.update(dt)
        target = min(max(0, self.index - VISIBLE // 2), max(0, len(self.rows()) - VISIBLE))
        self.scroll += (target - self.scroll) * min(1.0, dt * 14)
        d = self.dl
        if self.mode == "download" and d is not None and d.finished:
            self.changed = self.changed or d.ok > 0
            self.refresh()
            if d.cancelled:
                self.message = t("dl.cancelled", n=d.ok)
            elif d.failed:
                self.message = t("dl.done_failed", n=d.ok, f=len(d.failed))
            else:
                self.message = t("dl.done", n=d.ok)
            self.mode = "done"
            self.sfx("menu_select")

    # ------------------------------------------------------------ cizim
    def draw(self, surf: pygame.Surface) -> None:
        a = self.assets
        tc = a.text
        self.bg.draw(surf, 0.2)
        shade = pygame.Surface((W, 720), pygame.SRCALPHA)
        shade.fill((6, 4, 3, 150))
        surf.blit(shade, (0, 0))
        head = tc.glow(t("dl.title"), 42, (255, 214, 140), glow_color=NEON_PINK, radius=8)
        surf.blit(head, (40, 14))
        have_all, tot_all, rem_all = self._counts(self.setlists)
        sub = tc.render(t("dl.summary", have=have_all, total=tot_all, size=fmt_size(rem_all)), 16, TEXT_DIM)
        surf.blit(sub, (620 - sub.get_width(), 40))
        self._draw_list(surf)
        if self.mode == "browse":
            self._draw_detail(surf)
        else:
            self._draw_progress(surf)
        if self.mode == "download":
            hints = [("key.esc_red", "hint.cancel")]
        elif self.mode == "done":
            hints = [("key.enter_green", "hint.ok")]
        else:
            hints = [("key.updown", "hint.move"), ("key.enter_green", "hint.download"), ("key.esc_red", "hint.back")]
        draw_hints(surf, a, hints)

    def _draw_list(self, surf) -> None:
        tc = self.assets.text
        rect = pygame.Rect(30, 80, 600, ROW_H * VISIBLE + 16)
        draw_panel(surf, rect, border=NEON_PURPLE)
        clip = surf.get_clip()
        surf.set_clip(rect.inflate(-6, -6))
        rows = self.rows()
        first = int(self.scroll)
        for i in range(first, min(len(rows), first + VISIBLE + 2)):
            s = rows[i]
            y = rect.y + 8 + (i - self.scroll) * ROW_H
            row = pygame.Rect(rect.x + 8, int(y), rect.w - 16, ROW_H - 6)
            sel = i == self.index
            if sel:
                hl = pygame.Surface(row.size, pygame.SRCALPHA)
                pygame.draw.rect(hl, (255, 118, 30, 80), (0, 0, *row.size), border_radius=10)
                pygame.draw.rect(hl, (255, 176, 72, 230), (0, 0, *row.size), 2, border_radius=10)
                surf.blit(hl, row.topleft)
            lists = self.setlists if s is None else [s]
            have, tot, rem = self._counts(lists)
            name = upper(t("dl.all")) if s is None else s.name
            n = tc.render(name, 22, (255, 255, 255) if sel else TEXT, "ui", True)
            meta = t("dl.row_meta", year=s.year, n=tot) if s is not None else t("songs.count", n=tot)
            m = tc.render(meta, 14, NEON_CYAN if sel else TEXT_DIM)
            surf.blit(n, (row.x + 14, row.y + 2))
            surf.blit(m, (row.x + 14, row.y + 27))
            if have >= tot:
                st = tc.render(t("dl.complete"), 16, GOOD, "ui", True)
            elif have:
                st = tc.render(f"{have}/{tot} · {fmt_size(rem)}", 16, NEON_ORANGE, "ui", True)
            else:
                st = tc.render(fmt_size(rem), 16, TEXT_DIM, "ui", True)
            surf.blit(st, (row.right - 14 - st.get_width(), row.y + 14))
        surf.set_clip(clip)

    def _detail_rect(self) -> pygame.Rect:
        return pygame.Rect(660, 80, 590, ROW_H * VISIBLE + 16)

    def _draw_detail(self, surf) -> None:
        tc = self.assets.text
        det = self._detail_rect()
        draw_panel(surf, det, border=NEON_CYAN)
        lists = self._sel_lists()
        s = self.rows()[self.index]
        have, tot, rem = self._counts(lists)
        x, y = det.x + 24, det.y + 20
        title = t("dl.all") if s is None else s.name
        surf.blit(tc.render(title, 28, TEXT, "ui", True), (x, y))
        y += 40
        info = [(t("dl.songs_label"), str(tot)), (t("dl.installed_label"), f"{have} / {tot}"),
                (t("dl.remaining_label"), fmt_size(rem)), (t("dl.free_label"), fmt_size(self._free()))]
        for lab, val in info:
            surf.blit(tc.render(upper(lab), 14, TEXT_DIM, "ui", True), (x, y + 3))
            surf.blit(tc.render(val, 18, TEXT), (x + 170, y))
            y += 26
        y += 8
        songs = [(x_.artist, x_.name, x_.md5 in self.installed, x_.length_ms) for sl in lists for x_ in sl.songs]
        for artist, name, ok, ln in songs[:11]:
            col = GOOD if ok else TEXT
            line = tc.render(f"{artist} - {name}", 16, col)
            if line.get_width() > det.w - 110:
                line = line.subsurface((0, 0, det.w - 110, line.get_height()))
            surf.blit(line, (x, y))
            if ln:
                d = tc.render(fmt_time(ln / 1000), 14, TEXT_DIM)
                surf.blit(d, (det.right - 24 - d.get_width(), y + 2))
            y += 22
        if len(songs) > 11:
            surf.blit(tc.render(t("dl.more", n=len(songs) - 11), 14, TEXT_DIM), (x, y))
        note = [t("dl.note"), t("dl.folder", path=self.root)]
        yy = det.bottom - 18 - 20 * len(note)
        if self.message:
            m = tc.render(self.message, 16, NEON_ORANGE, "ui", True)
            surf.blit(m, (x, yy - 26))
        for ln in note:
            img = tc.render(ln, 13, TEXT_DIM)
            if img.get_width() > det.w - 48:
                img = img.subsurface((0, 0, det.w - 48, img.get_height()))
            surf.blit(img, (x, yy))
            yy += 20

    def _bar(self, surf, rect: pygame.Rect, frac: float, col) -> None:
        pygame.draw.rect(surf, (26, 22, 18), rect, border_radius=rect.h // 2)
        if frac > 0:
            fill = rect.copy()
            fill.w = max(rect.h, int(rect.w * min(1.0, frac)))
            pygame.draw.rect(surf, col, fill, border_radius=rect.h // 2)
        pygame.draw.rect(surf, (156, 122, 84), rect, 1, border_radius=rect.h // 2)

    def _draw_progress(self, surf) -> None:
        tc = self.assets.text
        det = self._detail_rect()
        draw_panel(surf, det, border=NEON_ORANGE)
        d = self.dl
        x, y = det.x + 24, det.y + 22
        if d is None:
            return
        n = len(d.jobs)
        head = t("dl.downloading") if self.mode == "download" else t("dl.finished")
        surf.blit(tc.render(head, 28, TEXT, "ui", True), (x, y))
        y += 48
        job = d.current
        if job is not None:
            surf.blit(tc.render(job.setlist.name, 16, NEON_CYAN, "ui", True), (x, y))
            y += 24
            line = tc.render(f"{job.song.artist} - {job.song.name}", 20, TEXT, "ui", True)
            if line.get_width() > det.w - 48:
                line = line.subsurface((0, 0, det.w - 48, line.get_height()))
            surf.blit(line, (x, y))
            y += 34
            tot = d.cur_total or job.song.size or 1
            self._bar(surf, pygame.Rect(x, y, det.w - 48, 16), d.cur_bytes / tot, NEON_CYAN)
            y += 30
        else:
            y += 88
        done = d.index + (1 if d.finished and not d.cancelled else 0)
        surf.blit(tc.render(t("dl.progress", i=min(done, n), n=n), 18, TEXT, "ui", True), (x, y))
        y += 30
        frac = d.bytes_now / d.total_bytes if d.total_bytes else 0.0
        self._bar(surf, pygame.Rect(x, y, det.w - 48, 24), frac, NEON_ORANGE)
        y += 36
        stats = t("dl.bytes", done=fmt_size(d.bytes_now), total=fmt_size(d.total_bytes))
        if self.mode == "download" and d.speed() > 0:
            stats += "  ·  " + t("dl.speed", speed=fmt_size(d.speed()), eta=fmt_time(d.eta()))
        surf.blit(tc.render(stats, 16, TEXT_DIM), (x, y))
        y += 32
        if d.failed:
            surf.blit(tc.render(t("dl.failed_count", n=len(d.failed)), 16, NEON_PINK, "ui", True), (x, y))
            y += 26
        if self.mode == "download" and d.cancel_event.is_set():
            surf.blit(tc.render(t("dl.cancelling"), 18, NEON_ORANGE, "ui", True), (x, y))
        if self.message:
            m = tc.render(self.message, 20, NEON_ORANGE, "ui", True)
            surf.blit(m, (x, det.bottom - 60))
