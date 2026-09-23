"""Guitar Hero (eski adi RIFF) - 5 perdeli ritim oyunu. Giris noktasi.

Kullanim:
  python main.py                              oyun (ana menu)
  python main.py --song <klasor|ad> [--diff expert] [--autoplay]   dogrudan oyuna gir
  python main.py --smoke [--song ..] [--diff ..]    headless, simule saat, bot: full combo degilse cikis kodu 1
  python main.py --screenshot out.png --at 42.5 --song .. [--diff ..]   oyun karesi (bot durumu o ana kadar)
  python main.py --screenshot-menu out.png          baslik + sarki listesi + diger menu ekranlari
  python main.py --import sarki.mp3 [--smoke]       headless: ses dosyasini ekle (otomatik chart), istenirse bot oynasin
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="GuitarHero", description="Guitar Hero - 5-fret rhythm game")
    p.add_argument("--song", help="song folder path or song name")
    p.add_argument("--diff", default=None, help="easy / medium / hard / expert (default: expert or hardest)")
    p.add_argument("--autoplay", action="store_true", help="bot plays the song")
    p.add_argument("--smoke", action="store_true", help="headless full-song bot run(s); exit 0 only on full combo")
    p.add_argument("--smoke-fps", type=float, default=30.0, help="simulated frames per second for --smoke")
    p.add_argument("--screenshot", metavar="PNG", help="render a gameplay frame to PNG (needs --at)")
    p.add_argument("--at", type=float, default=10.0, help="song time (s) for --screenshot")
    p.add_argument("--screenshot-menu", metavar="PNG", help="render title/song list/menu screens to PNG(s)")
    p.add_argument("--scale", type=float, default=1.0, help="scale factor for saved screenshots")
    p.add_argument("--no-bot", action="store_true", help="--screenshot without autoplay (notes get missed)")
    p.add_argument("--quit-after", type=float, default=0.0, help="quit the game after N seconds (testing)")
    p.add_argument("--fps", type=int, default=None, help="override FPS limit for this run (0 = unlimited)")
    p.add_argument("--import", dest="import_paths", nargs="+", metavar="PATH",
                   help="headless: import audio files / folders into Songs (auto-chart); with --smoke the bot "
                        "then plays the imported songs")
    return p.parse_args(argv)


def _pick_diff(chart, want):
    from gh.library import available_difficulties
    diffs = available_difficulties(chart)
    if not diffs:
        raise SystemExit("song has no playable 5-fret guitar track")
    if want and want.lower() in diffs:
        return want.lower()
    if want:
        print(f"difficulty '{want}' not available, using {diffs[-1]}", file=sys.stderr)
    return diffs[-1]


def run_headless(args) -> int:
    from gh import headless
    app = headless.make_app()
    imported: list[str] = []
    if args.import_paths:
        res = headless.import_files(app, args.import_paths)
        for r in res:
            extra = ""
            if r["mode"]:
                extra = f"  [mode {r['mode']}"
                if r["notice"]:
                    extra += f", {r['notice']}"
                if r["timings"]:
                    extra += f", {r['timings'].get('total', 0.0):.1f}s"
                extra += "]"
            print(f"{'OK  ' if r['ok'] else 'FAIL'} {r['name']}: {r['folder'] or r['message']}{extra}")
        imported = [r["folder"] for r in res if r["ok"]]
        if not imported:
            return 1
    if args.smoke:
        songs = [args.song] if args.song else (imported or [None])
        results = []
        for song in songs:
            results += headless.smoke_all(app, song, args.diff.lower() if args.diff else None, args.smoke_fps)
        if not results:
            print("no songs found")
            return 1
        ok_all = True
        for r in results:
            ok_all &= r["ok"]
            print(f"{'OK  ' if r['ok'] else 'FAIL'} {r['song']:<28} {r['diff']:<7} score {r['score']:>8,}  "
                  f"stars {r['stars']:.2f}  notes {r['hit']}/{r['total']}  combo {r['max_combo']}  "
                  f"miss {r['missed']} over {r['overstrums']}  ({r['frames']} frames, {r['seconds']:.1f}s)"
                  + (f"  audio: {r['load_errors']}" if r["load_errors"] else ""))
        print("SMOKE PASSED" if ok_all else "SMOKE FAILED")
        return 0 if ok_all else 1
    if args.screenshot_menu:
        files = headless.screenshot_menus(app, args.screenshot_menu, args.scale)
        for f in files:
            print("wrote", f)
    if args.screenshot:
        app.library.scan()
        info = app.library.find(args.song) if args.song else (app.library.songs[0] if app.library.songs else None)
        if info is None:
            print("song not found")
            return 1
        diff = _pick_diff(app.library.chart(info.folder), args.diff)
        headless.screenshot_gameplay(app, info, diff, args.at, args.screenshot, args.scale, autoplay=not args.no_bot)
        print("wrote", args.screenshot)
    return 0


def run_game(args) -> int:
    import pygame
    from gh.settings_store import load_settings
    settings = load_settings()
    a = settings.audio
    pygame.mixer.pre_init(a.sample_rate, -16, 2, a.buffer)
    pygame.init()
    from gh.app import App
    from gh.scenes import GameplayScene, TitleScene
    app = App(settings)
    app.quit_after = args.quit_after
    saved_fps = settings.video.fps_limit
    if args.fps is not None:
        settings.video.fps_limit = max(0, args.fps)
    app.push(TitleScene(app))
    if not args.song:
        app.check_inbox()          # Songs/_Import'ta bekleyen ses dosyalari: once ice aktar
    if args.song:
        app.library.scan()
        info = app.library.find(args.song)
        if info is None:
            print(f"song not found: {args.song}", file=sys.stderr)
        else:
            diff = _pick_diff(app.library.chart(info.folder), args.diff)
            app.push(GameplayScene(app, info, diff, autoplay=args.autoplay))
    try:
        app.run()
    finally:
        if args.fps is not None:
            settings.video.fps_limit = saved_fps
            from gh.settings_store import save_settings
            save_settings(settings)
    if args.quit_after and app.total_frames:
        el = max(1e-6, time.perf_counter() - app.run_start)
        print(f"frames {app.total_frames} in {el:.1f}s = {app.total_frames / el:.1f} fps avg, "
              f"update+draw+flip {app.total_render_ms / app.total_frames:.2f} ms/frame, "
              f"audio {'ok' if app.audio.ok else 'OFF: ' + app.audio.error}, driver {pygame.display.get_driver()}")
    pygame.quit()
    return 0


def write_crash_log(exc: BaseException) -> str:
    from gh.config import user_root
    path = os.path.join(user_root(), "riff_crash.log")
    try:
        import datetime
        import platform
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"==== Guitar Hero crash {datetime.datetime.now().isoformat()} ====\n")
            fh.write(f"python {sys.version}\nplatform {platform.platform()}\nargv {sys.argv}\n")
            try:
                import pygame
                fh.write(f"pygame {pygame.version.ver} SDL {pygame.get_sdl_version()}\n")
            except Exception:
                pass
            fh.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
            fh.write("\n")
    except OSError:
        pass
    return path


def main(argv=None) -> int:
    args = parse_args(argv)
    headless_mode = bool(args.smoke or args.screenshot or args.screenshot_menu or args.import_paths)
    try:
        return run_headless(args) if headless_mode else run_game(args)
    except SystemExit:
        raise
    except KeyboardInterrupt:
        return 130
    except BaseException as exc:
        path = write_crash_log(exc)
        if sys.stderr is not None:
            traceback.print_exc()
        if getattr(sys, "frozen", False) and sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(None, f"Guitar Hero crashed. Details were written to:\n{path}",
                                                 "Guitar Hero", 0x10)
            except Exception:
                pass
        return 1


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()       # PyInstaller exe: olasi alt surec calisanlari icin (gitar kalibrasyonu)
    sys.exit(main())
