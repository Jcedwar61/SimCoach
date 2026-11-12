"""Practice drills over simulated practice laps, including the report table."""
import threading

from _common import check, done, headless_coach, load

sc = load()


class Practice(sc.SimReader):
    def read(self):
        fr = super().read()
        if fr is not None:
            fr.session, fr.race_laps, fr.race_over, fr.position = "practice", 0, False, 0
        return fr


cfg, voice, coach = headless_coach(sc)
cfg["driver_name"] = "Sam"
said = []
voice.log = lambda m: said.append(m)
conv = sc.Conversation(cfg, coach, voice, sc.NullOverlay())
check("clean lap first" in conv.local("practice turn 2"), "drill refused before corners are mapped")
orig, n = coach.finish_lap, {"laps": 0}


def fl(lap_time, now):
    orig(lap_time, now)
    n["laps"] += 1
    if n["laps"] == 2:
        r = conv.local("work on turn three for three laps")
        check(r.startswith("Drill on. Turn 3 for the next 3 laps"), f"drill starts: {r[:60]}")
        check([ci for ci, _ in coach.focus] == [2], "focus locked on turn 3")


coach.finish_lap = fl
sc.coach_loop(coach, [Practice(laps=8)], threading.Event(), test=True)
check(any("Drill lap 1 of 3, Turn 3" in m for m in said), "per-lap drill call")
check(any("Drill done, Turn 3, 3 laps" in m for m in said), "drill summary at the end")
check(len(coach.drills_done) == 1 and coach.drills_done[0]["laps"] == 3, "drill recorded")
check(conv.local("stop the drill") == "There's no drill running.", "stop with no drill")
check("only mapped" in conv.local("practice turn 40"), "unknown corner refused")
check(conv.local("drill turn 2").startswith("Drill on. Turn 2 for the next 5 laps"), "default 5 laps")
check("stopped before a clean lap" in conv.local("cancel the drill"), "drill stopped early")
html = open(coach.end_session(), encoding="utf-8").read()
check("Practice drills" in html and "<td>Turn 3</td><td>3 of 3</td>" in html, "report has the drills table")
done()
