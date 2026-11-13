"""Pace against the target and the consistency score: the numbers, the advice, what the coach says after a best
lap, the voice commands, and the saved session history and report."""
import re

from _common import check, done, headless_coach, load

sc = load()

c = sc.consistency_of([100.0, 100.2, 100.1, 100.3, 100.15])
check(c and c["label"] == "very consistent" and c["laps"] == 5 and c["off"] == 0, f"tight laps: {c and c['label']}")
c = sc.consistency_of([100.0, 101.6, 100.3, 101.9, 100.9])
check(c and c["label"] in ("a bit up and down", "inconsistent") and c["off"] == 0, f"spread laps: {c and c['label']}")
c = sc.consistency_of([100.0, 100.3, 100.2, 112.0])
check(c and c["off"] == 1 and c["laps"] == 3 and c["label"] == "very consistent", "one ruined lap is set aside, not averaged in")
check(sc.consistency_of([100.0, 100.5]) is None, "fewer than three laps: no score")
c = sc.consistency_of([151.7, 146.9, 144.5, 143.0, 142.4, 142.8])
check(c and c["off"] == 2 and c["label"] in ("consistent", "very consistent"),
      f"a driver getting quicker through the session isn't called inconsistent ({c and c['label']})")
check("consistency first" in sc.pace_advice(104.0, {"pct": 1.5}), "inconsistent: work on consistency first")
check("focus corners" in sc.pace_advice(102.0, {"pct": 0.3}), "consistent and close: the time is in the focus corners")
check("technique" in sc.pace_advice(106.0, {"pct": 0.4}), "consistent but off the pace: technique")
check(sc.pace_advice(None, None) == "", "nothing to go on: no advice")


def drive(game, track, length, car, lap_times, profile="Spa"):
    """Laps of the given times (the starter profile, scaled) so the coach sees real lap completions."""
    cfg = sc.load_config()
    cfg.update(driver_name="Sam", shared_refs=False, talk_level=1)
    cfg, voice, coach = headless_coach(sc, cfg)
    said = []
    voice.log = lambda m: said.append(m)
    prof = sc.starter_reference(profile, "gt3")["ref"]
    base = sc.starter_reference(profile, "gt3")["best_time"]
    d, t, lap_t, last, dt, n = 0.0, 0.0, 0.0, 0.0, 1 / 60, 0
    while n < len(lap_times):
        k = base / lap_times[n]
        b = min(sc.BINS - 1, int(d / length * sc.BINS))
        v = max(10.0, prof["speed"][b] * k)
        coach.update(sc.Frame(game, track, car, n, d / length, v, prof["thr"][b], prof["brk"][b], 0.0, 3, 6000.0, lap_t, last,
                              False, False, fuel=50.0, fuel_cap=100.0, track_len=length, session="practice"), t)
        t += dt
        lap_t += dt
        d += v / 3.6 * dt
        if d >= length:
            d -= length
            n, last, lap_t = n + 1, lap_t, 0.0
    for _ in range(30):
        coach.update(sc.Frame(game, track, car, n, d / length, 100.0, 1.0, 0.0, 0.0, 3, 6000.0, lap_t, last, False, False,
                              fuel=50.0, fuel_cap=100.0, track_len=length, session="practice"), t)
        t += dt
    return cfg, voice, coach, said


cfg, voice, coach, said = drive("ACC", "spa", 7004, "Porsche 911 GT3 R (992)", [146.0, 143.0, 142.6, 142.9, 141.2])
tg = coach.target()
check(tg and abs(tg[0] - 136.434) < 0.01 and tg[2] == "gt3", f"target for ACC GT3 at Spa ({tg})")
best = min(coach.session_clean_times())
pace = coach.pace_pct(best)
check(pace and 102.5 < pace < 104.5, f"pace {pace:.1f}% of the target")
text = " ".join(said)
m = re.search(r"That's (\d+\.\d) percent of a quick GT3 lap", text)
check(bool(m), "a new best lap is followed by the pace against the target")
conv = sc.Conversation(cfg, coach, voice, sc.NullOverlay(), log=lambda m: None)
ans = conv.local("what's the target time") or ""
check("The target is 2 16.4" in ans and "percent" in ans, f"'what's the target time' -> {ans[:90]}")
ans = conv.local("how consistent am I") or ""
check("clean laps vary by about" in ans, f"'how consistent am I' -> {ans[:90]}")
coach.end_session()
sess = coach.past_sessions()
check(sess and sess[-1].get("pace_pct") and abs(sess[-1]["pace_pct"] - pace) < 0.05 and sess[-1].get("target"),
      "session history keeps the pace and target")
rep = open(coach.last_report, encoding="utf-8").read()
check("Pace vs target" in rep and f"{pace:.1f}%" in rep and "Where you are:" in rep, "report shows pace, target and the verdict")
check("<th>Pace vs target</th><th>Consistency</th>" in rep, "progress table has the pace and consistency trend")
s = coach.summary()
check(s.get("target_lap_s") and s.get("pace_pct_of_target") and s.get("consistency"), "the AI's summary includes them")

cfg, voice, coach, said = drive("AC EVO", "Some Unknown Track", 4000, "Mazda MX-5 Cup", [100.0, 99.5, 99.0])
check(coach.target() is None and coach.pace_pct(99.0) is None, "no benchmark: no target")
check("percent of" not in " ".join(said), "and nothing said about it")
ans = sc.Conversation(cfg, coach, voice, sc.NullOverlay(), log=lambda m: None).local("what's the target time") or ""
check("don't have a target" in ans, "asked anyway: says there's none")

# crew banter: no praise for the pace while the driver is well off it
crew = sc.Crew(sc.load_config(), sc.Voice(sc.load_config(), enabled=False), sc.NullOverlay(), coach=None)
picked = []
crew.chatter = lambda role, event, facts, now, **k: picked.append((event, facts))
crew.on = lambda r: True
crew.voice.idle = lambda now: True
crew.voice.on_straight.set()
crew.spot = {"left": False, "right": False}
crew.last_spoken = crew.last_chat = -1000.0
f = sc.Frame("ACC", "spa", "Porsche 911 GT3 R (992)", 3, 0.3, 200.0, 1.0, 0.0, 0.0, 5, 7000.0, 40.0, 142.0, False, False)


class _C:
    def target(self):
        return (136.4, False, "gt3")


crew.coach = _C()
crew.lap_times = [151.7, 146.9, 144.5]
crew.banter(f, 1000.0)
check(picked and picked[-1][0] == "quiet_slow" and picked[-1][1].get("pace_pct_of_quick_lap") == 105.9,
      f"well off the target: encouraging, not 'pace is solid' ({picked[-1:]})")
crew.lap_times = [137.6, 137.2, 137.4]
crew.last_spoken = crew.last_chat = -1000.0
crew.banter(f, 2000.0)
check(picked[-1][0] == "quiet", "close to the target and their best: normal banter")
check(all("pace" not in x.lower() or "speed follows" in x.lower() for x in sc.CANNED["quiet_slow"]["strategist"]),
      "the strategist's lines for that moment don't praise the pace")

# the report's setup sheet shows the fuel actually used once laps have measured it
sheet = {"items": [("Fuel", "Fuel load", "40 litres"), ("Fuel", "Use per lap", "About 2.4 litres (a guess until SimCoach has timed a lap)"),
                   ("Tyres", "Hot pressures", "27.0 to 27.4 psi")], "source": "Built-in advisor", "made": "now"}
out = sc.sheet_with_measured_fuel(sheet, 2.93, "ACC")
check(out["items"][1][2] == "2.9 litres (measured this session)" and out["items"][0] == sheet["items"][0],
      "measured fuel replaces the guess")
check(sc.sheet_with_measured_fuel(sheet, None, "ACC") is sheet, "no measurement yet: the sheet is unchanged")
done()
