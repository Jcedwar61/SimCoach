# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = [
#   "numpy",
#   "pygame>=2.5",
#   "edge-tts>=6.1",
#   "gTTS>=2.5",
#   "kokoro-onnx>=0.4",
#   "openai>=1.60",
#   "psutil",
#   "pywin32; sys_platform == 'win32'",
# ]
# ///
"""SimCast - live TV-style commentary of the sim race you're driving in (Windows 10/11).

A two-person booth (play-by-play and analyst, plus a pit-lane reporter) commentates the whole race: the start,
overtakes, battles, pit stops, fastest laps, cars in trouble and the finish, for every car on the grid, not
just yours. Stands alone: SimCoach doesn't need to be installed (the two can run side by side).

  SimCast.exe / SimCast.bat   the SimCast window
  --demo                      start with the demo race (no sim needed)
  --console                   no window: commentary in the console
  --test [--laps N]           a whole demo race, silently, on a fast clock: prints the commentary
  --no-voice                  text only
  --setup                     download the packages and exit (the installer runs this)
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def _crash_logging(log):
    """Anything that goes wrong, in any thread, ends up in simcast.log (there's no console to see it in)."""
    import traceback

    def hook(t, v, tb):
        log("".join(traceback.format_exception(t, v, tb)))
    sys.excepthook = hook
    threading.excepthook = lambda a: hook(a.exc_type, a.exc_value, a.exc_traceback)


def main(argv=None):
    ap = argparse.ArgumentParser(description="SimCast: live TV-style race commentary for sim racing.")
    ap.add_argument("--demo", action="store_true", help="start with the demo race")
    ap.add_argument("--console", action="store_true", help="no window: print the commentary")
    ap.add_argument("--test", action="store_true", help="silent demo race on a fast clock; print the commentary")
    ap.add_argument("--setup", action="store_true", help="check the packages load, then exit")
    ap.add_argument("--laps", type=int, default=None)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--no-voice", action="store_true")
    args = ap.parse_args(argv)

    from simcast.audio import wine_numpy_guard
    wine_numpy_guard()                      # Linux/Steam Deck: keeps an old Wine from crashing on NumPy
    from simcast import app as app_mod

    if args.setup:
        import importlib
        for mod in ("edge_tts", "gtts", "openai", "pygame", "tkinter"):   # installed by uv by the time this runs
            importlib.import_module(mod)
        from simcast.audio import kokoro_usable
        print("Kokoro voices: " + ("ready to use" if kokoro_usable() else
                                   "not available here (the other voices are)"))
        print("SimCast is ready.")
        return 0

    if args.test:
        cast = app_mod.headless_run(laps=args.laps or 6, seed=args.seed, log=lambda m: None)
        for t, ln in cast.audio.spoken:
            name = cast.config().get(f"{ln.who}_name", ln.who)
            print(f"{int(t // 60):2d}:{int(t % 60):02d}  {name:>6}  {ln.text}")
        print(f"\n{len(cast.audio.spoken)} lines, {cast.events_seen} race moments, errors: {list(cast.errors) or 'none'}")
        return 1 if cast.errors else 0

    _crash_logging(app_mod.file_log)
    app_mod.file_log(f"SimCast {app_mod.APP_VERSION} starting (Python {sys.version.split()[0]}, {sys.platform})")
    cfg = app_mod.load_config()
    cast = app_mod.SimCast(cfg, log=print if args.console else app_mod.file_log)
    if args.no_voice:
        cast.cfg["tts"] = "off"
        cast.save_enabled = False

    if not args.console:
        from simcast.gui import SimCastWindow
        SimCastWindow(cast, start_demo=args.demo).run()
        return 0

    print(f"SimCast {app_mod.APP_VERSION}: waiting for a sim... (Ctrl+C to quit)")
    if args.demo:
        cast.start_demo(args.laps)
    stop = threading.Event()
    loop = threading.Thread(target=cast.run, args=(stop,), daemon=True, name="simcast-loop")
    loop.start()
    try:
        while loop.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    stop.set()
    return 0


if __name__ == "__main__":
    sys.exit(main())
