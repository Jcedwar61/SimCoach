"""Lap debriefs: short by default (Chatty keeps the full version); no roasting or corner blame for laps with
traffic or yellow flags; calmer default coach for new installs."""
import threading

from _common import check, done, headless_coach, load

sc = load()
check(sc.DEFAULT_CONFIG["coach_personality"] == "mansell" and sc.DEFAULT_CONFIG["crew_updates"] == "important",
      "new installs: Composed coach, important-only crew reports")


class Practice(sc.SimReader):
    def read(self):
        fr = super().read()
        if fr is not None:
            fr.session, fr.race_laps, fr.race_over, fr.position = "practice", 0, False, 0
        return fr


def run(talk=1, personality="apex", traffic_laps=(), traffic_now=False):
    cfg = sc.load_config()
    cfg.update(driver_name="Sam", talk_level=talk, coach_personality=personality)
    cfg, voice, coach = headless_coach(sc, cfg)
    said = []
    voice.log = lambda m: said.append(m)
    lap_msgs, n = [], {"lap": 0}
    orig_fin, orig_ctx = coach.finish_lap, coach._note_lap_context

    def fin(lap_time, now):
        n["lap"] += 1
        if n["lap"] in traffic_laps:
            coach.lap.ctx_traffic_s = 5.0
        before = len(said)
        orig_fin(lap_time, now)
        lap_msgs.extend((n["lap"], m) for m in said[before:] if m.startswith("COACH: 1 0"))

    def ctx(f, now):
        orig_ctx(f, now)
        if traffic_now:
            coach._traffic_now = True
    coach.finish_lap, coach._note_lap_context = fin, ctx
    sc.coach_loop(coach, [Practice(laps=9)], threading.Event(), test=True)
    corner_calls = [m for m in said if " lost. " in m and m.startswith("COACH: Turn")]
    return lap_msgs, corner_calls


normal, calls_n = run(talk=1)
chatty, calls_c = run(talk=2)
avg = lambda msgs: sum(m.count(". ") + m.count("! ") + 1 for _, m in msgs) / max(1, len(msgs))
check(avg(normal) < avg(chatty), f"normal debriefs are shorter ({avg(normal):.1f} vs {avg(chatty):.1f} sentences)")
check(len(calls_n) <= len(calls_c), f"fewer corner callouts at normal talk level ({len(calls_n)} vs {len(calls_c)})")
msgs, _ = run(talk=1, traffic_laps=range(3, 10))
traffic = [m for k, m in msgs if k >= 3]
check(traffic and not any("what on earth" in m for m in traffic), "no roasting on traffic laps")
check(any("held up in traffic" in m for m in traffic), "traffic laps say why they don't count")
check(not any("Next lap, isolate" in m for k, m in msgs if k >= 3 and "held up" in m), "no coaching blame on an excused lap")
_, calls_t = run(talk=2, traffic_now=True)
check(calls_t == [], "no corner-loss callouts while stuck in traffic")
done()
