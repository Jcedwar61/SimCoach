# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = [
#   "numpy",
#   "pygame>=2.5",
#   "edge-tts>=6.1",
#   "openai>=1.60",
#   "psutil",
#   "pywin32; sys_platform == 'win32'",
# ]
# ///
"""SimCast - live TV-style commentary of the sim race you're driving in.

A two-person booth (play-by-play and analyst, plus a pit-lane reporter) commentates the whole race: the start,
overtakes, battles, pit stops, fastest laps, cars in trouble and the finish, for every car on the grid, not
just yours. Reads the same sims as SimCoach (and can run alongside it).

  SimCast.bat                 start, open the control page in the browser
  --demo                      start with the demo race (no sim needed)
  --test [--laps N]           a whole demo race, silently, on a fast clock: prints the commentary
  --no-voice                  text only     --no-browser    don't open the page     --port N    page port
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


def main(argv=None):
    ap = argparse.ArgumentParser(description="SimCast: live TV-style race commentary for sim racing.")
    ap.add_argument("--demo", action="store_true", help="start with the demo race")
    ap.add_argument("--test", action="store_true", help="silent demo race on a fast clock; print the commentary")
    ap.add_argument("--laps", type=int, default=None)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--no-voice", action="store_true")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--port", type=int, default=None)
    args = ap.parse_args(argv)

    import sim_coach as sc
    from simcast import app as app_mod

    if args.test:
        cast = app_mod.headless_run(sc, laps=args.laps or 6, seed=args.seed, log=lambda m: None)
        for t, ln in cast.audio.spoken:
            name = cast.config().get(f"{ln.who}_name", ln.who)
            print(f"{int(t // 60):2d}:{int(t % 60):02d}  {name:>6}  {ln.text}")
        print(f"\n{len(cast.audio.spoken)} lines, {cast.events_seen} race moments, errors: {list(cast.errors) or 'none'}")
        return 1 if cast.errors else 0

    from simcast.web import WebUI
    cfg = app_mod.load_config()
    if args.no_voice:
        cfg["tts"] = "off"
    sc.install_crash_logging() if hasattr(sc, "install_crash_logging") else None
    cast = app_mod.SimCast(sc, cfg)
    if args.no_voice:
        cast.save_enabled = False
    web = WebUI(cast)
    if not web.start(args.port or cfg.get("port", 8766), lan=bool(cfg.get("lan"))):
        print("Couldn't start the control page (no free port).")
    else:
        print(f"SimCast {app_mod.APP_VERSION}: control page at {web.url()}  (stream overlay: {web.url()}overlay)")
    if args.demo:
        cast.start_demo(args.laps)
    stop = threading.Event()
    loop = threading.Thread(target=cast.run, args=(stop,), daemon=True, name="simcast-loop")
    loop.start()
    if web.port and cfg.get("open_browser", True) and not args.no_browser:
        try:
            import webbrowser
            webbrowser.open(web.url())
        except Exception:
            pass
    print("Waiting for a sim... (Ctrl+C to quit)")
    try:
        while loop.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    stop.set()
    web.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
