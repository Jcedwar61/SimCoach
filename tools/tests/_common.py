"""Shared helpers for SimCoach's tests: load sim_coach.py in a throwaway settings folder and count failures."""
import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))


def load(path=None):
    """Import sim_coach.py as module `sc`. APPDATA points at a temporary folder first, so a test never touches
    the real %APPDATA%\\SimCoach (settings, references) or Documents\\SimCoach Reports."""
    os.environ["APPDATA"] = tempfile.mkdtemp(prefix="simcoach-test-appdata-")
    path = path or os.environ.get("SIMCOACH_PY") or os.path.join(REPO, "sim_coach.py")
    spec = importlib.util.spec_from_file_location("sc", path)
    sc = importlib.util.module_from_spec(spec)
    sys.modules["sc"] = sc
    spec.loader.exec_module(sc)
    sc.REPORT_DIR = tempfile.mkdtemp(prefix="simcoach-test-reports-")
    sc.save_config = lambda cfg: None
    return sc


_failures = []


def check(ok, what):
    print(("ok   " if ok else "FAIL ") + what, flush=True)
    if not ok:
        _failures.append(what)
    return ok


def done():
    """Exit 0 when every check passed, 1 otherwise."""
    print(f"{'PASSED' if not _failures else f'FAILED ({len(_failures)})'}", flush=True)
    sys.exit(1 if _failures else 0)


def headless_coach(sc, cfg=None, overlay=None):
    """A Coach + Crew with a silent voice whose 'idle' follows the queued speech length."""
    cfg = cfg or sc.load_config()
    voice = sc.Voice(cfg, enabled=False)
    voice.idle = lambda now, v=voice: now >= v.busy_until
    ov = overlay or sc.NullOverlay()
    coach = sc.Coach(cfg, voice, ov, tempfile.mkdtemp(prefix="simcoach-test-refs-"))
    coach.crew = sc.Crew(cfg, voice, ov, coach=coach)
    return cfg, voice, coach
