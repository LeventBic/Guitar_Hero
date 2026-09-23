"""Sarki ekleme ekrani: surukle-birak alani + bicim rehberi, arka planda ice aktarma kuyrugu ve ilerleme paneli.

Modlar
- "drop": birakma alani, kabul edilen bicimler, gelen kutusu (Songs\\_Import) dugmeleri
- "work": kuyruk arka plan is parcaciginda islenir (sarki adi, asama, ilerleme cubugu, dosya basina sonuc)
- "done": PLAY NOW / SONG LIST / IMPORT MORE
"""
from __future__ import annotations

import math
import os
import threading
import time

import pygame

from ..i18n import stage, t
from ..render.assets import NEON_CYAN, NEON_ORANGE, NEON_PINK, NEON_PURPLE, TEXT, TEXT_DIM, W
from ..render.ui import SynthBackground, draw_hints, draw_panel, fade_overlay
from .base import Scene

FORMATS = ("MP3", "OGG", "WAV", "FLAC", "OPUS")
OK_COL = (90, 230, 120)
ERR_COL = (255, 110, 110)


def _fit(img: pygame.Surface, max_w: int) -> pygame.Surface:
    """Yazi kutusuna sigmiyorsa yatayda sikistir (uzun ceviriler icin)."""
    if img.get_width() <= max_w or max_w <= 10:
        return img
    return pygame.transform.smoothscale(img, (max_w, img.get_height()))


class Job:
    def __init__(self, kind: str, path: str, *, from_inbox: bool = False):
        self.kind = kind              # audio | folder | rechart
        self.path = path
        self.from_inbox = from_inbox
        base = os.path.basename(os.path.normpath(path))
        self.name = base if kind != "audio" else os.path.splitext(base)[0]
        self.status = "queued"        # queued | running | ok | error | skipped
        self.message = ""
        self.msg_key = ""             # i18n anahtari (varsa cizimde cevrilir)
        self.msg_params: dict = {}
        self.stage = ""
        self.progress = 0.0
        self.result = ""
        self.ai = False               # gitar kalibrasyonu (yapay zeka) ile isleniyor
        self.info: dict = {}          # importer'in doldurdugu {'mode', 'notice', 'timings'}
        self.started = 0.0
        self.finished = 0.0
        self.eta = -1.0               # yumusatilmis kalan sure tahmini (s)


def _jobs_for(paths, from_inbox=False) -> list[Job]:
    from ..importer import collect_audio_files, is_song_folder
    jobs = []
    for p in collect_audio_files(paths):
        jobs.append(Job("folder" if is_song_folder(p) else "audio", p, from_inbox=from_inbox))
    return jobs


class ImportScene(Scene):
    def __init__(self, app, paths=None, *, from_inbox: bool = False, rechart: str | None = None):
        super().__init__(app)
        self.bg = SynthBackground()
        self.jobs: list[Job] = []
        self.mode = "drop"
        self.worker: threading.Thread | None = None
        self.cancel = False
        self.sel = 0
        self.note = ""                # tek satirlik bilgi (ornek: 'no audio files in the drop')
        self.note_t = 0.0
        self.started_at = 0.0
        self.imported_any = False
        if rechart:
            self._add([Job("rechart", rechart)])
        elif paths:
            jobs = _jobs_for(paths, from_inbox)
            if jobs:
                self._add(jobs)
            else:
                self._say(t("imp.no_audio"))

    # ------------------------------------------------------------------ kuyruk
    def _say(self, text: str) -> None:
        self.note = text
        self.note_t = self.t

    def _add(self, jobs: list[Job]) -> None:
        known = {os.path.normcase(os.path.abspath(j.path)) for j in self.jobs if j.status in ("queued", "running")}
        for j in jobs:
            if os.path.normcase(os.path.abspath(j.path)) not in known:
                self.jobs.append(j)
        if any(j.status == "queued" for j in self.jobs):
            self.mode = "work"
            self.sel = 0
            self._ensure_worker()

    def _ensure_worker(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            return
        self.cancel = False
        self.cancel_event = threading.Event()
        self.started_at = time.perf_counter()
        self.worker = threading.Thread(target=self._run, name="riff-import", daemon=True)
        self.worker.start()

    def _run(self) -> None:
        from ..ai.runtime import Cancelled
        from ..importer import ImportFailed, ai_available, import_audio, import_song_folder, rechart_song, songs_dir
        root = songs_dir()
        use_ai = bool(self.app.settings.extra.get("guitar_ai", True))
        ai_ok = use_ai and ai_available()[0]
        while True:
            job = next((j for j in self.jobs if j.status == "queued"), None)
            if job is None or self.cancel:
                break
            job.status = "running"
            job.stage = "Starting"
            job.ai = ai_ok and job.kind in ("audio", "rechart")
            job.started = time.perf_counter()

            def prog(f, text, job=job):
                job.progress = f
                job.stage = text

            try:
                if job.kind == "audio":
                    job.result = import_audio(job.path, root, prog, use_ai=use_ai, cancel=self.cancel_event,
                                              info=job.info)
                elif job.kind == "folder":
                    job.result = import_song_folder(job.path, root, prog)
                else:
                    job.result = rechart_song(job.path, prog, use_ai=use_ai, cancel=self.cancel_event, info=job.info)
                job.status = "ok"
                job.progress = 1.0
                if job.info.get("notice"):
                    job.msg_key = job.info["notice"]
                if job.from_inbox:
                    try:
                        os.remove(job.path)
                    except OSError:      # silinemedi (kilitli): bu oturumda tekrar otomatik eklenmesin
                        try:
                            self.app.inbox_failed.add((os.path.normcase(job.path), os.path.getmtime(job.path)))
                        except OSError:
                            pass
            except Cancelled:
                job.status, job.message = "skipped", "cancelled"
            except ImportFailed as exc:
                job.status, job.message = "error", str(exc)
                job.msg_key, job.msg_params = exc.key, dict(exc.params)
            except Exception as exc:  # beklenmeyen hata: yine de kuyruk devam etsin
                job.status, job.message = "error", f"{type(exc).__name__}: {exc}"
            job.finished = time.perf_counter()
            if job.status == "error" and job.from_inbox:
                try:
                    self.app.inbox_failed.add((os.path.normcase(job.path), os.path.getmtime(job.path)))
                except OSError:
                    pass
        if self.cancel:
            for j in self.jobs:
                if j.status == "queued":
                    j.status, j.message = "skipped", "cancelled"

    @property
    def busy(self) -> bool:
        return self.worker is not None and self.worker.is_alive()

    def wait(self, timeout: float = 900.0) -> None:
        """Testler/headless: is parcacigi bitene kadar bekle."""
        if self.worker is not None:
            self.worker.join(timeout)
        self.update(0.0)

    # ------------------------------------------------------------------ yasam dongusu
    def enter(self) -> None:
        self.app.audio.stop_preview(300)

    def on_drop(self, paths) -> None:
        jobs = _jobs_for(paths)
        if not jobs:
            self._say(t("imp.no_audio"))
            self.sfx("miss_buzz", 0.5)
            return
        self.sfx("menu_select")
        self._add(jobs)

    def _buttons(self) -> list[tuple[str, str]]:
        if self.mode == "drop":
            n = self._inbox_count()
            return [("open", t("imp.btn_open")), ("inbox", t("imp.btn_now_n", n=n) if n else t("imp.btn_now")),
                    ("back", t("imp.btn_back"))]
        if self.mode == "done":
            b = []
            if self._last_ok() is not None:
                b.append(("play", t("imp.btn_play")))
            b += [("list", t("imp.btn_list")), ("more", t("imp.btn_more"))]
            return b
        return [("cancel", t("imp.btn_cancel"))]

    def _last_ok(self) -> Job | None:
        oks = [j for j in self.jobs if j.status == "ok" and j.result]
        return oks[-1] if oks else None

    def update(self, dt: float) -> None:
        super().update(dt)
        self.bg.update(dt)
        self._update_eta(dt)
        if self.mode == "work" and not self.busy and not any(j.status in ("queued", "running") for j in self.jobs):
            self.mode = "done"
            self.sel = 0
            ok = any(j.status == "ok" for j in self.jobs)
            self.imported_any = self.imported_any or ok
            if ok:
                self.app.library.scan()
                for j in self.jobs:
                    if j.status == "ok" and j.result:
                        self.app.library.invalidate(j.result)
            self.sfx("sp_phrase_complete" if ok else "miss_buzz", 0.7)

    # ------------------------------------------------------------------ girdi
    def on_menu(self, action: str) -> None:
        btns = self._buttons()
        if action in ("LEFT", "UP"):
            self.sel = (self.sel - 1) % len(btns)
            self.sfx("menu_move")
        elif action in ("RIGHT", "DOWN"):
            self.sel = (self.sel + 1) % len(btns)
            self.sfx("menu_move")
        elif action == "CONFIRM":
            self._activate(btns[min(self.sel, len(btns) - 1)][0])
        elif action == "BACK":
            if self.mode == "work":
                self._activate("cancel")
            elif self.mode == "done":
                self._activate("list" if self.imported_any else "back")
            else:
                self._activate("back")

    def _activate(self, what: str) -> None:
        if what == "back":
            self.sfx("menu_back")
            self.app.pop()
        elif what == "open":
            self.sfx("menu_select")
            from ..importer import inbox_dir
            path = inbox_dir(create=True)
            if not self.app.headless and hasattr(os, "startfile"):
                try:
                    os.startfile(path)  # noqa: S606 - kullanicinin kendi klasoru
                except OSError as exc:
                    self._say(t("imp.open_failed", err=exc))
            self._say(t("imp.opened", path=path))
        elif what == "inbox":
            files = self.app.inbox_pending(include_failed=True)
            if not files:
                self.sfx("miss_buzz", 0.5)
                self._say(t("imp.inbox_empty"))
                return
            self.sfx("menu_select")
            self._inbox_t = -9.0
            self._add(_jobs_for(files, from_inbox=True))
        elif what == "cancel":
            if any(j.status in ("queued", "running") for j in self.jobs):
                # Esc: gecerli sarki de durdurulur (ayristirma parca aralarinda iptal edilir, yarim klasor
                # olusturulmaz), kuyruktakiler atlanir
                self.cancel = True
                ev = getattr(self, "cancel_event", None)
                if ev is not None:
                    ev.set()
                self.sfx("menu_back")
                self._say(t("imp.cancelling"))
        elif what == "play":
            job = self._last_ok()
            if job is None:
                return
            self.sfx("menu_select")
            sl = self.app.open_songlist(job.result)
            sl.open_difficulty()
        elif what == "list":
            self.sfx("menu_select")
            job = self._last_ok()
            self.app.open_songlist(job.result if job else None)
        elif what == "more":
            self.sfx("menu_select")
            self.jobs = [j for j in self.jobs if j.status in ("queued", "running")]
            self.mode = "drop"
            self.sel = 0

    # ------------------------------------------------------------------ cizim
    def draw(self, surf: pygame.Surface) -> None:
        a = self.assets
        tc = a.text
        self.bg.draw(surf, 0.25)
        shade = pygame.Surface((W, 720), pygame.SRCALPHA)
        shade.fill((4, 2, 14, 160))
        surf.blit(shade, (0, 0))
        head = tc.glow(t("imp.title"), 42, (255, 130, 215), glow_color=NEON_PINK, radius=8)
        surf.blit(head, (40, 14))
        if self.mode == "drop":
            self._draw_drop(surf)
        else:
            self._draw_work(surf)
        self._draw_buttons(surf)
        if self.note and self.t - self.note_t < 6.0:
            img = tc.render(self.note[:110], 17, NEON_ORANGE, "ui", True)
            surf.blit(img, (W // 2 - img.get_width() // 2, 646))
        hints = [("key.leftright", "hint.select"), ("key.enter_green", "hint.ok")]
        hints.append(("key.esc_red", "hint.cancel" if self.mode == "work" else "hint.back"))
        draw_hints(surf, a, hints)

    def _dashed_rect(self, surf, rect, color, dash=18, gap=12, width=3, phase=0.0) -> None:
        r = pygame.Rect(rect)
        per = 2 * (r.w + r.h)
        step = dash + gap
        off = phase % step
        d = -off
        while d < per:
            a0, a1 = max(0.0, d), min(per, d + dash)
            if a1 > a0:
                p0, p1 = self._perim(r, a0), self._perim(r, a1)
                # koseden gecen parca: iki cizgi
                c = self._corner_between(r, a0, a1)
                if c is not None:
                    pygame.draw.line(surf, color, p0, c, width)
                    pygame.draw.line(surf, color, c, p1, width)
                else:
                    pygame.draw.line(surf, color, p0, p1, width)
            d += step

    @staticmethod
    def _perim(r, d):
        if d <= r.w:
            return (r.x + d, r.y)
        d -= r.w
        if d <= r.h:
            return (r.right, r.y + d)
        d -= r.h
        if d <= r.w:
            return (r.right - d, r.bottom)
        d -= r.w
        return (r.x, r.bottom - d)

    @staticmethod
    def _corner_between(r, a0, a1):
        for c, pt in ((r.w, (r.right, r.y)), (r.w + r.h, (r.right, r.bottom)),
                      (2 * r.w + r.h, (r.x, r.bottom))):
            if a0 < c < a1:
                return pt
        return None

    def _draw_note_icon(self, surf, cx, cy, col, s=1.0) -> None:
        pygame.draw.ellipse(surf, col, (cx - 34 * s, cy + 18 * s, 30 * s, 22 * s))
        pygame.draw.ellipse(surf, col, (cx + 16 * s, cy + 8 * s, 30 * s, 22 * s))
        pygame.draw.line(surf, col, (cx - 6 * s, cy + 28 * s), (cx - 6 * s, cy - 30 * s), max(2, int(5 * s)))
        pygame.draw.line(surf, col, (cx + 44 * s, cy + 18 * s), (cx + 44 * s, cy - 40 * s), max(2, int(5 * s)))
        pygame.draw.polygon(surf, col, [(cx - 6 * s, cy - 30 * s), (cx + 44 * s, cy - 40 * s),
                                         (cx + 44 * s, cy - 26 * s), (cx - 6 * s, cy - 16 * s)])

    def _draw_drop(self, surf) -> None:
        tc = self.assets.text
        zone = pygame.Rect(60, 86, 720, 440)
        flash = max(0.0, 1.0 - (time.perf_counter() - self.app.drop_flash) / 0.8) if self.app.drop_flash else 0.0
        fill = pygame.Surface(zone.size, pygame.SRCALPHA)
        k = 0.5 + 0.5 * math.sin(self.t * 2.2)
        pygame.draw.rect(fill, (40 + int(60 * flash), 14, 70, 150 + int(60 * flash)), (0, 0, *zone.size),
                         border_radius=22)
        surf.blit(fill, zone.topleft)
        col = tuple(int(c1 + (c2 - c1) * max(k * 0.5, flash)) for c1, c2 in zip(NEON_PINK, (255, 255, 255)))
        self._dashed_rect(surf, zone.inflate(-10, -10), col, phase=self.t * 40)
        # ikon: zipla + asagi ok
        bob = 6 * math.sin(self.t * 3.0)
        cx, cy = zone.centerx, zone.y + 130 + int(bob)
        self._draw_note_icon(surf, cx - 10, cy, (255, 150, 220))
        ay = zone.y + 210 + int(bob)
        pygame.draw.polygon(surf, NEON_CYAN, [(cx - 22, ay), (cx + 22, ay), (cx, ay + 22)])
        t1 = tc.glow(t("imp.drop_here"), 36, (255, 235, 250), "ui", True, glow_color=NEON_PINK, radius=6)
        surf.blit(t1, (cx - t1.get_width() // 2, zone.y + 250))
        t2 = tc.render(t("imp.drop_many"), 20, TEXT_DIM, "ui")
        surf.blit(t2, (cx - t2.get_width() // 2, zone.y + 312))
        t3 = tc.render(t("imp.drop_auto"), 20, NEON_CYAN, "ui")
        surf.blit(t3, (cx - t3.get_width() // 2, zone.y + 344))
        t4 = tc.render(t("imp.drop_anywhere"), 16, TEXT_DIM, "ui")
        surf.blit(t4, (cx - t4.get_width() // 2, zone.y + 392))
        # rehber paneli
        side = pygame.Rect(810, 86, 430, 440)
        draw_panel(surf, side, border=NEON_CYAN)
        x, y = side.x + 24, side.y + 20
        surf.blit(tc.render(t("imp.formats"), 16, TEXT_DIM, "ui", True), (x, y))
        y += 30
        cxp = x
        for f in FORMATS:
            chip = tc.render(f, 18, (15, 12, 25), "ui", True)
            r = pygame.Rect(cxp, y, chip.get_width() + 22, 32)
            pygame.draw.rect(surf, NEON_CYAN, r, border_radius=16)
            surf.blit(chip, (r.x + 11, r.y + 6))
            cxp = r.right + 8
        y += 52
        surf.blit(tc.render(t("imp.recommended"), 16, TEXT_DIM, "ui", True), (x, y))
        y += 28
        tips = [("imp.tip1", True), ("imp.tip2", True), ("imp.tip3", True), ("imp.tip3b", False),
                ("imp.tip4", True), ("imp.tip4b", False)]
        for key, bullet in tips:
            if bullet:
                pygame.draw.circle(surf, NEON_PINK, (x + 6, y + 11), 4)
            img = tc.render(t(key), 19, TEXT, "ui")
            if img.get_width() > side.right - x - 36:
                img = pygame.transform.smoothscale(img, (side.right - x - 36, img.get_height()))
            surf.blit(img, (x + 20, y))
            y += 28
        y += 10
        surf.blit(_fit(tc.render(t("imp.folder_title"), 16, TEXT_DIM, "ui", True), side.right - x - 16), (x, y))
        y += 26
        disp = os.path.join("Songs", "_Import")
        surf.blit(tc.render(disp, 19, NEON_ORANGE, "mono"), (x, y))
        y += 26
        n = self._inbox_count()
        msg = t("imp.folder_waiting", n=n) if n else t("imp.folder_empty")
        surf.blit(_fit(tc.render(msg, 17, TEXT_DIM, "ui"), side.right - x - 16), (x, y))

    def _inbox_count(self) -> int:
        """Gelen kutusu dosya sayisi (her karede diski taramamak icin 1 s onbellek)."""
        now = time.perf_counter()
        if now - getattr(self, "_inbox_t", -9.0) > 1.0:
            self._inbox_t = now
            self._inbox_n = len(self.app.inbox_pending(include_failed=True))
        return self._inbox_n

    def _draw_work(self, surf) -> None:
        tc = self.assets.text
        panel = pygame.Rect(90, 86, 1100, 470)
        draw_panel(surf, panel, border=NEON_PURPLE)
        total = max(1, len(self.jobs))
        done = sum(1 for j in self.jobs if j.status in ("ok", "error", "skipped"))
        cur = next((j for j in self.jobs if j.status == "running"), None)
        x, y = panel.x + 30, panel.y + 22
        if self.mode == "done":
            nok = sum(1 for j in self.jobs if j.status == "ok")
            nerr = sum(1 for j in self.jobs if j.status == "error")
            title = t("imp.done_title", n=nok) + (t("imp.done_failed", n=nerr) if nerr else "")
            img = tc.glow(title, 34, (235, 255, 240) if nok else (255, 210, 210), "ui", True,
                          glow_color=OK_COL if nok else ERR_COL, radius=6)
            surf.blit(img, (x - 6, y - 6))
            y += 56
            sub = t("imp.done_sub") if nok else t("imp.done_none")
            surf.blit(tc.render(sub, 20, TEXT_DIM, "ui"), (x, y))
            y += 40
        elif cur is not None and cur.ai:
            y = self._draw_calibration(surf, panel, cur, done, total)
        else:
            name = cur.name if cur else (self.jobs[done].name if done < len(self.jobs) else "")
            img = tc.render(name, 30, TEXT, "ui", True)
            if img.get_width() > panel.w - 60:
                img = pygame.transform.smoothscale(img, (panel.w - 60, int(img.get_height() * (panel.w - 60) / img.get_width())))
            surf.blit(img, (x, y))
            y += 44
            stage_txt = (stage(cur.stage) if cur else t("imp.waiting")) + "..."
            surf.blit(tc.render(stage_txt, 20, NEON_CYAN, "ui"), (x, y))
            pos = self.jobs.index(cur) + 1 if cur else min(done + 1, total)
            cnt = tc.render(t("imp.song_n", i=pos, n=total), 18, TEXT_DIM, "ui")
            surf.blit(cnt, (panel.right - 30 - cnt.get_width(), y + 2))
            y += 36
            # ilerleme cubugu (sarki) + toplam
            bar = pygame.Rect(x, y, panel.w - 60, 26)
            pygame.draw.rect(surf, (30, 24, 54), bar, border_radius=13)
            frac = cur.progress if cur else 0.0
            if frac > 0:
                fr = bar.copy()
                fr.w = max(26, int(bar.w * frac))
                pygame.draw.rect(surf, NEON_PINK, fr, border_radius=13)
                shine = pygame.Surface((fr.w, 8), pygame.SRCALPHA)
                shine.fill((255, 255, 255, 60))
                surf.blit(shine, (fr.x, fr.y + 3))
                # hareketli parilti
                sx = fr.x + int((self.t * 260) % max(fr.w, 1))
                pygame.draw.line(surf, (255, 220, 250), (sx, fr.y + 4), (sx, fr.bottom - 5), 3)
            pygame.draw.rect(surf, (255, 120, 210), bar, 2, border_radius=13)
            pct = tc.render(f"{int(frac * 100)}%", 16, TEXT, "ui", True)
            surf.blit(pct, (bar.centerx - pct.get_width() // 2, bar.y + 3))
            y += 34
            tot = pygame.Rect(x, y, panel.w - 60, 6)
            pygame.draw.rect(surf, (30, 24, 54), tot, border_radius=3)
            ov = (done + frac) / total
            if ov > 0:
                pygame.draw.rect(surf, NEON_CYAN, (tot.x, tot.y, max(6, int(tot.w * ov)), 6), border_radius=3)
            y += 26
        # is listesi
        rows = 7 if self.mode == "done" else (2 if (cur is not None and cur.ai) else 6)
        idx_cur = next((i for i, j in enumerate(self.jobs) if j.status in ("running", "queued")), len(self.jobs) - 1)
        first = max(0, min(idx_cur - 2, len(self.jobs) - rows))
        for j in self.jobs[first:first + rows]:
            icon, col = {"ok": ("OK", OK_COL), "error": ("X", ERR_COL), "running": ("..", NEON_CYAN),
                         "queued": ("-", TEXT_DIM), "skipped": ("-", TEXT_DIM)}[j.status]
            chip = pygame.Rect(x, y + 2, 38, 24)
            pygame.draw.rect(surf, col, chip, 2, border_radius=8)
            ic = tc.render(icon, 15, col, "ui", True)
            surf.blit(ic, (chip.centerx - ic.get_width() // 2, chip.centery - ic.get_height() // 2))
            nm = tc.render(j.name[:60], 19, TEXT if j.status != "queued" else TEXT_DIM, "ui", j.status == "running")
            surf.blit(nm, (x + 52, y + 2))
            if j.status in ("error", "skipped") and j.message:
                txt = t("imp.cancelled") if j.status == "skipped" else (
                    t(j.msg_key, **j.msg_params) if j.msg_key else j.message)
                msg = tc.render(txt[:95], 16, ERR_COL if j.status == "error" else TEXT_DIM, "ui")
                surf.blit(msg, (x + 52, y + 26))
                y += 20
            elif j.status == "ok" and j.result:
                msg = tc.render(t("imp.added", name=os.path.basename(j.result)[:70]), 16, OK_COL, "ui")
                surf.blit(msg, (panel.right - 30 - msg.get_width(), y + 4))
                mode = j.info.get("mode")
                note = t(j.msg_key) if j.msg_key else (t("imp.guitar_ok") if mode == "guitar" else "")
                if note:
                    col = NEON_ORANGE if mode == "guitar" else (255, 200, 120)
                    surf.blit(_fit(tc.render(note, 16, col, "ui"), panel.w - 110), (x + 52, y + 26))
                    y += 20
            y += 34
            if y > panel.bottom - 30:
                break

    # ------------------------------------------------------------------ gitar kalibrasyonu paneli
    @staticmethod
    def _stage_index(stage_text: str) -> int:
        from ..ai.pipeline import STAGES
        if stage_text in STAGES:
            return STAGES.index(stage_text)
        if stage_text in ("Starting", "Reading tags", "Decoding audio", ""):
            return -1
        return len(STAGES)                     # dosyalar yaziliyor / bitti

    @staticmethod
    def _fmt_s(s: float) -> str:
        s = max(0, int(round(s)))
        return f"{s // 60}:{s % 60:02d}"

    def _update_eta(self, dt: float) -> None:
        cur = next((j for j in self.jobs if j.status == "running"), None)
        if cur is None or not cur.ai or not cur.started:
            return
        el = time.perf_counter() - cur.started
        f = cur.progress
        if f < 0.04 or el < 2.0:
            return
        raw = el * (1.0 - f) / max(f, 1e-3)
        cur.eta = raw if cur.eta < 0 else cur.eta + (raw - cur.eta) * min(1.0, dt * 0.8)
        cur.eta = max(0.0, cur.eta)

    def _draw_calibration(self, surf, panel: pygame.Rect, cur: Job, done: int, total: int) -> int:
        """GITAR KALIBRASYONU: asama listesi, hareketli dalga + perde gem'leri, ilerleme cubugu, gecen/kalan sure."""
        from ..ai.pipeline import STAGES
        from ..config import FRET_COLORS
        tc = self.assets.text
        x, y = panel.x + 30, panel.y + 16
        name = tc.render(cur.name, 24, TEXT, "ui", True)
        cnt = tc.render(t("imp.song_n", i=self.jobs.index(cur) + 1, n=total), 17, TEXT_DIM, "ui")
        surf.blit(_fit(name, panel.w - 90 - cnt.get_width()), (x, y))
        surf.blit(cnt, (panel.right - 30 - cnt.get_width(), y + 4))
        y += 34
        k = 0.5 + 0.5 * math.sin(self.t * 3.0)
        title = tc.glow(t("imp.cal_title"), 36, (255, 215, 150), "title", True, glow_color=NEON_ORANGE,
                        radius=5 + int(3 * k))
        surf.blit(title, (x - 6, y - 6))
        el = time.perf_counter() - cur.started if cur.started else 0.0
        rem = t("imp.remaining", t=self._fmt_s(cur.eta)) if cur.eta >= 0 else t("imp.estimating")
        tim = tc.render(f"{t('imp.elapsed', t=self._fmt_s(el))}    {rem}", 19, NEON_CYAN, "ui", True)
        surf.blit(tim, (panel.right - 30 - tim.get_width(), y + 12))
        y += 52
        surf.blit(_fit(tc.render(t("imp.cal_sub"), 17, TEXT_DIM, "ui"), panel.w - 60), (x, y))
        y += 30
        # asamalar (sol)
        idx = self._stage_index(cur.stage)
        row_h = 31
        for i, key in enumerate(STAGES):
            ry = y + i * row_h
            cx, cy = x + 12, ry + 12
            label = tc.render(stage(key) + ("..." if i == idx else ""), 19,
                              TEXT if i <= idx else TEXT_DIM, "ui", i == idx)
            if i < idx:
                pygame.draw.circle(surf, OK_COL, (cx, cy), 10)
                pygame.draw.lines(surf, (15, 30, 15), False, [(cx - 5, cy), (cx - 1, cy + 4), (cx + 5, cy - 4)], 3)
            elif i == idx:
                rr = 9 + int(3 * k)
                pygame.draw.circle(surf, NEON_ORANGE, (cx, cy), rr, 3)
                a = self.t * 5.0
                pygame.draw.circle(surf, (255, 230, 180), (int(cx + 6 * math.cos(a)), int(cy + 6 * math.sin(a))), 3)
            else:
                pygame.draw.circle(surf, (70, 62, 100), (cx, cy), 9, 2)
            surf.blit(label, (x + 34, ry + 1))
        if idx < 0:
            surf.blit(tc.render(t("imp.cal_prep") + "...", 16, TEXT_DIM, "ui"), (x + 34, y + 5 * row_h))
        # hareketli gorsel (sag): kayan dalga formu + nabiz atan 5 perde gem'i
        box = pygame.Rect(x + 520, y - 4, panel.right - 30 - (x + 520), 5 * row_h + 6)
        bg = pygame.Surface(box.size, pygame.SRCALPHA)
        pygame.draw.rect(bg, (18, 12, 36, 220), (0, 0, *box.size), border_radius=12)
        mid = box.h * 0.36
        n = 64
        bw = box.w / n
        for i in range(n):
            ph = i * 0.41 + self.t * 7.0
            amp = (0.35 + 0.65 * abs(math.sin(ph * 0.37))) * abs(math.sin(ph)) * (0.55 + 0.45 * math.sin(i * 0.13 + self.t))
            h = max(2, int(amp * mid * 0.9))
            lit = abs((i / n) - ((self.t * 0.35) % 1.0)) < 0.06
            col = (255, 170, 90, 230) if lit else (120, 90, 200, 170)
            pygame.draw.rect(bg, col, (int(i * bw) + 1, int(mid - h), max(1, int(bw) - 2), 2 * h), border_radius=2)
        gy = int(box.h * 0.8)
        for i in range(5):
            gx = int(box.w * (i + 0.5) / 5)
            pulse = max(0.0, math.sin(self.t * 4.0 - i * 1.1))
            r = int(15 + 5 * pulse)
            c = FRET_COLORS[i]
            pygame.draw.circle(bg, (*c, 90), (gx, gy), r + 6)
            pygame.draw.circle(bg, (*c, 255), (gx, gy), r)
            pygame.draw.circle(bg, (255, 255, 255, 120 + int(120 * pulse)), (gx, gy), max(3, r // 3))
        surf.blit(bg, box.topleft)
        pygame.draw.rect(surf, (140, 100, 220), box, 2, border_radius=12)
        y += 5 * row_h + 14
        # ilerleme cubugu
        bar = pygame.Rect(x, y, panel.w - 60, 26)
        pygame.draw.rect(surf, (30, 24, 54), bar, border_radius=13)
        frac = cur.progress
        if frac > 0:
            fr = bar.copy()
            fr.w = max(26, int(bar.w * frac))
            pygame.draw.rect(surf, NEON_ORANGE, fr, border_radius=13)
            shine = pygame.Surface((fr.w, 8), pygame.SRCALPHA)
            shine.fill((255, 255, 255, 60))
            surf.blit(shine, (fr.x, fr.y + 3))
            sx = fr.x + int((self.t * 260) % max(fr.w, 1))
            pygame.draw.line(surf, (255, 240, 210), (sx, fr.y + 4), (sx, fr.bottom - 5), 3)
        pygame.draw.rect(surf, (255, 190, 110), bar, 2, border_radius=13)
        pct = tc.render(f"{int(frac * 100)}%", 16, TEXT, "ui", True)
        surf.blit(pct, (bar.centerx - pct.get_width() // 2, bar.y + 3))
        y += 34
        if total > 1:
            tot = pygame.Rect(x, y, panel.w - 60, 6)
            pygame.draw.rect(surf, (30, 24, 54), tot, border_radius=3)
            ov = (done + frac) / total
            pygame.draw.rect(surf, NEON_CYAN, (tot.x, tot.y, max(6, int(tot.w * ov)), 6), border_radius=3)
        return y + 18

    def _draw_buttons(self, surf) -> None:
        tc = self.assets.text
        btns = self._buttons()
        imgs = [tc.render(lab, 22, (255, 255, 255) if i == self.sel else TEXT_DIM, "title", True)
                for i, (_k, lab) in enumerate(btns)]
        widths = [im.get_width() + 56 for im in imgs]
        total = sum(widths) + 24 * (len(btns) - 1)
        x = W // 2 - total // 2
        y = 578
        for i, (im, w) in enumerate(zip(imgs, widths)):
            r = pygame.Rect(x, y, w, 52)
            s = pygame.Surface(r.size, pygame.SRCALPHA)
            if i == self.sel:
                k = 0.5 + 0.5 * math.sin(self.t * 4)
                pygame.draw.rect(s, (255, 60, 170, 70 + int(40 * k)), (0, 0, *r.size), border_radius=12)
                pygame.draw.rect(s, (255, 110, 200, 240), (0, 0, *r.size), 2, border_radius=12)
            else:
                pygame.draw.rect(s, (20, 16, 40, 200), (0, 0, *r.size), border_radius=12)
                pygame.draw.rect(s, (110, 90, 160, 200), (0, 0, *r.size), 2, border_radius=12)
            surf.blit(s, r.topleft)
            surf.blit(im, (r.centerx - im.get_width() // 2, r.centery - im.get_height() // 2))
            x += w + 24


class ConfirmScene(Scene):
    """Evet/hayir onayi (alttaki sahnenin ustunde)."""
    opaque = False

    def __init__(self, app, title: str, lines: list[str], on_yes, yes: str = "common.yes", no: str = "common.no"):
        super().__init__(app)
        self.title = title
        self.lines = lines
        self.on_yes = on_yes
        self.labels = (yes, no)
        self.sel = 1

    def on_menu(self, action: str) -> None:
        if action in ("LEFT", "RIGHT", "UP", "DOWN"):
            self.sel ^= 1
            self.sfx("menu_move")
        elif action == "CONFIRM":
            if self.sel == 0:
                self.sfx("menu_select")
                self.app.pop()
                self.on_yes()
            else:
                self.sfx("menu_back")
                self.app.pop()
        elif action == "BACK":
            self.sfx("menu_back")
            self.app.pop()

    def draw(self, surf: pygame.Surface) -> None:
        tc = self.assets.text
        fade_overlay(surf, 160, (4, 2, 12))
        panel = pygame.Rect(W // 2 - 330, 220, 660, 280)
        draw_panel(surf, panel, border=NEON_ORANGE)
        ti = tc.render(t(self.title), 30, TEXT, "ui", True)
        surf.blit(ti, (W // 2 - ti.get_width() // 2, panel.y + 24))
        y = panel.y + 78
        for line in self.lines:
            img = tc.render(t(line), 19, TEXT_DIM, "ui")
            surf.blit(img, (W // 2 - img.get_width() // 2, y))
            y += 28
        for i, lab in enumerate(self.labels):
            img = tc.render(t(lab), 24, (255, 255, 255) if i == self.sel else TEXT_DIM, "title", True)
            r = pygame.Rect(0, 0, 180, 50)
            r.center = (W // 2 + (-110 if i == 0 else 110), panel.bottom - 50)
            s = pygame.Surface(r.size, pygame.SRCALPHA)
            if i == self.sel:
                pygame.draw.rect(s, (255, 60, 170, 90), (0, 0, *r.size), border_radius=12)
                pygame.draw.rect(s, (255, 110, 200, 240), (0, 0, *r.size), 2, border_radius=12)
            else:
                pygame.draw.rect(s, (110, 90, 160, 200), (0, 0, *r.size), 2, border_radius=12)
            surf.blit(s, r.topleft)
            surf.blit(img, (r.centerx - img.get_width() // 2, r.centery - img.get_height() // 2))
        draw_hints(surf, self.assets, [("key.leftright", "hint.select"), ("key.enter_green", "hint.ok"),
                                       ("key.esc_red", "hint.cancel")])
