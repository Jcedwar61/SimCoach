"""Race-start coaching: grid reminder and start review for different launches; silent for rolling starts/practice."""
from _common import check, done, headless_coach, load

sc = load()
GO = 60.0   # seconds on the grid: the engineer intro and setup briefing (~40 s) play first; a reminder that
#             would only fit after lights-out is skipped on purpose


def run(kind, session="race"):
    cfg, voice, coach = headless_coach(sc)
    said = []
    voice.log = lambda m: said.append(m)
    t, pct, spd, pos, L, rolling = 0.0, 0.985, 0.0, 6, 4000.0, kind == "rolling"
    if rolling:
        spd = 90.0
    for _ in range(60 * 90):
        t += 1 / 60
        moving = rolling or t >= GO
        if moving and not rolling:
            spd = min(spd + 6 / 60, 12) if (kind == "bog" and t - GO < 3.6) else min(spd + (20 if kind == "bog" else 32) / 60, 230)
        thr = 0.3 if (kind == "lift" and GO + 0.5 < t < GO + 1) else (1.0 if moving else 0.0)
        wheels = [spd * 1.6] * 4 if (kind == "spin" and GO < t < GO + 2 and spd > 5) else [spd] * 4
        pct = (pct + spd / 3.6 / 60 / L) % 1.0
        if moving and t > GO + 5:
            pos = 9 if kind == "bog" else 4
        f = sc.Frame("AC", "Test Ring", "Test Car", 0, pct, spd, thr, 0.0, 0.0, 1, 5000.0, t, 0.0, False, False,
                     fuel=50.0, fuel_cap=60.0, session=session, position=pos, cars=20, race_laps=10, wheel_kmh=wheels)
        coach.update(f, t)
    return " | ".join(m for m in said if "On the grid" in m or "Start review" in m)


r = run("clean")
check("On the grid" in r and "Clean launch" in r and "P4 after turn one, up 2" in r, "clean launch")
check("Too much wheelspin" in run("spin"), "wheelspin")
r = run("bog")
check("bogged down" in r and "down 3" in r, "bog-down, places lost")
check("came off the throttle" in run("lift"), "lift in the launch")
check(run("rolling") == "", "rolling start: silent")
check(run("clean", session="practice") == "", "practice: silent")
done()
