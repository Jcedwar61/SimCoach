"""SimCast: the race tracker, the commentary booth, the AI booth (with a stand-in model), the web page's API and
the sim readers' whole-field data. Everything runs on a simulated clock with silent audio."""
import json
import os
import re
import struct
import sys
import urllib.error
import urllib.request

from _common import REPO, check, done, load

sc = load()
sys.path.insert(0, REPO)
from simcast import ai as ai_mod                      # noqa: E402
from simcast.app import DEFAULTS, SimCast, headless_run    # noqa: E402
from simcast.audio import SimAudio                    # noqa: E402
from simcast.race import RaceTracker, call_name       # noqa: E402
from simcast.writer import gap_words, lap_time_words, ordinal_words, place  # noqa: E402

# ---------------------------------------------------------------- words
check(call_name("Max Verstappen") == "Verstappen", "call name: surname")
check(call_name("Sam Driver2") == "Driver", "call name: iRacing's trailing digits dropped")
check(call_name("Car 7") == "Car 7", "call name: a numbered car stays whole")
check(call_name("Carlos Sainz Jr.") == "Sainz", "call name: suffix skipped")
check(gap_words(0.5) == "half a second" and gap_words(0.3) == "three tenths", "gaps in tenths")
check(gap_words(1.4) == "one point four seconds" and gap_words(1.5) == "a second and a half", "gaps in seconds")
check(lap_time_words(69.23) == "one oh nine point two", f"lap time words ({lap_time_words(69.23)})")
check(lap_time_words(103.46) == "one forty-three point five", f"lap time words ({lap_time_words(103.46)})")
check(ordinal_words(21) == "twenty-first" and place(2) == "second" and place(12) == "twelfth", "ordinals")

# ---------------------------------------------------------------- tracker, hand-built field
L = 2000.0


def frame(cars, t, session="race", race_laps=10, flag=None):
    """cars: list of dicts with id, name, dist (laps), in_pit, speed, status."""
    order = sorted(cars, key=lambda c: -c["dist"])
    pos = {c["id"]: i + 1 for i, c in enumerate(order)}
    field = [sc.field_entry(c["id"], c["name"], "GT3", pos[c["id"]], int(c["dist"]) if c["dist"] >= 0 else 0,
                            c["dist"] % 1.0, c.get("in_pit", False), None, None, c.get("status"), None,
                            player=c["id"] == 2, speed=c.get("speed")) for c in cars]
    me = next(c for c in cars if c["id"] == 2)
    f = sc.Frame("TEST", "Test Ring", "GT3", int(me["dist"]), me["dist"] % 1.0, 150.0, 1, 0, 0, 4, 7000, 0, 0,
                 False, False, track_len=L, session=session, position=pos[2], cars=len(cars), race_laps=race_laps)
    f.field, f.flag = field, flag
    return f


def run(scenario, until, dt=1 / 30):
    """scenario(t) -> car list; returns all events."""
    tr = RaceTracker(log=lambda m: None)
    evs, t = [], 0.0
    while t < until:
        for e in tr.update(frame(scenario(t), t), t):
            evs.append((t, e))
        t += dt
    return tr, evs


def lapsf(t, lap_s, start=0.0):
    return max(0.0, t - 5.0) / lap_s + start           # stationary for 5 s on the grid, then go


def pass_scn(t):
    return [{"id": 0, "name": "Alex Front", "dist": lapsf(t, 60.0, 0.010), "speed": 0 if t < 5 else 120},
            {"id": 1, "name": "Blake Quick", "dist": lapsf(t, 57.0, 0.005), "speed": 0 if t < 5 else 126},
            {"id": 2, "name": "Me Myself", "dist": lapsf(t, 61.0, 0.0), "speed": 0 if t < 5 else 118}]


tr, evs = run(pass_scn, 200)
kinds = [e.kind for _, e in evs]
check("intro" in kinds and "start" in kinds, "race intro and start")
ov = [e for _, e in evs if e.kind == "overtake"]
check(len(ov) == 1 and ov[0].cars[:2] == (1, 0) and ov[0].data["lead"], f"the quicker car takes the lead ({[e.cars for e in ov]})")
check(tr.cars[1].interval is None and tr.cars[0].interval is not None and tr.cars[0].interval > 0,
      "intervals measured at the timing loops")
check(any(e.kind == "fastest_lap" and e.cars == (1,) for _, e in evs), "fastest lap to the quickest car")


def pit_scn(t):
    cars = pass_scn(t)
    # The leader dives into the pits on lap 2: slow through the lane, and the others go by.
    c0 = cars[0]
    if 70.0 <= t < 95.0:
        c0["in_pit"] = True
        c0["dist"] = lapsf(70.0, 60.0, 0.010) + (t - 70.0) / 400.0
        c0["speed"] = 60
    elif t >= 95.0:
        c0["dist"] = lapsf(70.0, 60.0, 0.010) + 25.0 / 400.0 + (t - 95.0) / 60.0
    cars[1]["dist"] = lapsf(t, 60.5, 0.005)             # no on-track pass in this one
    cars[1]["speed"] = 119
    return cars


tr, evs = run(pit_scn, 150)
kinds = [e.kind for _, e in evs]
check("pit_in" in kinds and "pit_out" in kinds, "pit stop in and out")
check(not [e for _, e in evs if e.kind == "overtake" and 0 in e.cars], "losing places in the pits is not an overtake")


def stop_scn(t):
    cars = pass_scn(t)
    cars[1]["dist"] = lapsf(t, 60.5, 0.005)
    if t > 80:                                          # car 0 stops on track for good
        cars[0]["dist"] = lapsf(80, 60.0, 0.010)
        cars[0]["speed"] = 0
    return cars


tr, evs = run(stop_scn, 110)
check(any(e.kind == "stopped" and e.cars == (0,) for _, e in evs), "a car stopped on track")
check(not [e for _, e in evs if e.kind == "overtake" and len(e.cars) > 1 and e.cars[1] == 0],
      "passing a stopped car is not an overtake")


tr2 = RaceTracker(log=lambda m: None)
tr2_ev = []
t = 0.0
while t < 5 + 61 * 3 + 10:
    tr2_ev += [e.kind for e in tr2.update(frame(pass_scn(t), t, race_laps=3), t)]
    t += 1 / 20
check("final_lap" in tr2_ev and "winner" in tr2_ev and "player_finish" in tr2_ev, "final lap, winner, player's finish")

# ---------------------------------------------------------------- whole demo race through the booth
cast = headless_run(sc, laps=6, seed=5, log=lambda m: None)
spoken = [ln for _, ln in cast.audio.spoken]
text = " ".join(ln.text for ln in spoken)
check(not cast.errors, f"demo race: no errors ({list(cast.errors)})")
check(len(spoken) > 40, f"demo race: plenty said ({len(spoken)} lines)")
check(re.search(r"lights out|green flag|they.re away", text, re.I) is not None, "demo race: the start is called")
check(re.search(r"wins|winner|takes the win", text, re.I) is not None, "demo race: the winner is called")
check("Sam Carter" in text and re.search(r"crossing the line|chequered flag in", text) is not None, "demo race: the player's finish")
mentioned = {c.call for c in cast.tracker.cars.values() if c.call in text}
check(len(mentioned) >= len(cast.tracker.cars) - 1,
      f"demo race: the whole field gets airtime ({len(mentioned)}/{len(cast.tracker.cars)})")
check(not re.search(r"\b(he|she|his|her|him)\b", text, re.I), "demo race: drivers named, never gendered")
dupes = [t for t in set(ln.text for ln in spoken) if sum(1 for ln in spoken if ln.text == t) > 2]
check(not dupes, f"demo race: no line said over and over ({dupes[:2]})")
whos = {ln.who for ln in spoken}
check({"lead", "analyst", "pit"} <= whos, f"demo race: lead, analyst and pit reporter all speak ({whos})")
starts = [t for t, ln in cast.audio.spoken]
check(all(b >= a for a, b in zip(starts, starts[1:])), "demo race: lines never overlap")

# ---------------------------------------------------------------- the AI booth with a stand-in model
calls = []


def fake_chat(cfg, messages, max_tokens=300, timeout=20.0):
    calls.append(messages)
    task = messages[-1]["content"]
    if "quiet moment" in task:
        return json.dumps({"lines": [{"who": "lead", "text": "AI-FILLER: the gaps are tumbling at the front.", "energy": 1},
                                     {"who": "analyst", "text": "AI-FILLER: and the pace is there.", "energy": 1}]})
    if "race is over" in task:
        return '```json\n{"lines": [{"who": "lead", "text": "AI-WRAP: what a race.", "energy": 1}]}\n```'
    if "ANALYST's reaction" in task:
        return json.dumps({"lines": [{"who": "analyst", "text": "AI-REACT: that changes everything.", "energy": 2},
                                     {"who": "nobody", "text": "x" * 500}]})
    return "not json at all"


booth = ai_mod.AIBooth(lambda: dict(DEFAULTS, openai_api_key="test", ai_colour=True), fake_chat, sc._json_reply,
                       log=lambda m: None)
booth.sync = True
cast = headless_run(sc, laps=5, seed=5, booth=booth, log=lambda m: None)
said = [ln.text for _, ln in cast.audio.spoken]
check(any(t.startswith("AI-REACT") for t in said), "AI booth: the analyst reacts to big moments")
check(any(t.startswith("AI-FILLER") for t in said), "AI booth: quiet spells become conversation")
check(any(t.startswith("AI-WRAP") for t in said), "AI booth: the sign-off (from a fenced reply)")
check(not any("xxxx" in t for t in said), "AI booth: an overlong line is dropped")
prompt = calls[0][0]["content"] + calls[0][1]["content"]
check("STANDINGS" in prompt and "Only state facts" in prompt and "Never use he" in prompt,
      "AI booth: the prompt carries the race and the rules")
check(re.search(r"\[Moretti\]", prompt) is not None, "AI booth: drivers listed with their call names")


def broken_chat(cfg, messages, max_tokens=300, timeout=20.0):
    raise RuntimeError("network down")


booth = ai_mod.AIBooth(lambda: dict(DEFAULTS, openai_api_key="test"), broken_chat, sc._json_reply, log=lambda m: None)
booth.sync = True
cast = headless_run(sc, laps=4, seed=5, booth=booth, log=lambda m: None)
said = " ".join(ln.text for _, ln in cast.audio.spoken)
check("that's the result here" in said and not cast.errors, "AI booth down: the built-in booth carries on, wrap-up included")
check(booth.failures >= 3 and booth.disabled_until > 0, "AI booth down: it backs off instead of retrying every few seconds")

# ---------------------------------------------------------------- readers: the whole field
# rFactor 2 / LMU VehicleScoringInfoV01
v = bytearray(584)
struct.pack_into("<i", v, 0, 7)
v[4:4 + 10] = b"Jo Racer\0\0"
v[36:36 + 9] = b"bmw_m4_gt3"[:9]
struct.pack_into("<h", v, 100, 4)
v[103] = 0
struct.pack_into("<d", v, 104, 1500.0)
struct.pack_into("<d", v, 144, 98.4)
struct.pack_into("<d", v, 168, 99.1)
struct.pack_into("<h", v, 192, 1)
v[198], v[199] = 0, 3
v[200:203] = b"GT3"
fe = sc._RF2Family._field([bytes(v)], 4000.0, 7)
check(fe and fe[0]["name"] == "Jo Racer" and fe[0]["position"] == 3 and fe[0]["laps"] == 4 and
      abs(fe[0]["pct"] - 0.375) < 1e-6 and fe[0]["best"] == 98.4 and fe[0]["last"] == 99.1 and fe[0]["player"]
      and fe[0]["cls"] == "GT3", f"rFactor 2 / LMU field ({fe})")

# AMS2
b = bytearray(20700)
struct.pack_into("<i", b, 24, 2)
for k, (nm, pos, laps, dist) in enumerate((("Ann Lead", 1, 5, 900.0), ("Bo Second", 2, 5, 600.0))):
    ob = 28 + k * 100
    b[ob] = 1
    b[ob + 1:ob + 1 + len(nm)] = nm.encode()
    struct.pack_into("<f", b, ob + 80, dist)
    struct.pack_into("<II", b, ob + 84, pos, laps)
    struct.pack_into("<f", b, 9200 + 4 * k, 101.5)
    struct.pack_into("<f", b, 8944 + 4 * k, 100.2)
    struct.pack_into("<I", b, 9776 + 4 * k, 2 if k == 1 else 0)
fe = sc._ams2_field(bytes(b), 2, 0, 3000.0)
check(len(fe) == 2 and fe[0]["name"] == "Ann Lead" and fe[1]["in_pit"] and not fe[0]["in_pit"] and
      fe[0]["last"] == 101.5 and abs(fe[1]["pct"] - 0.2) < 1e-6, f"AMS2 field ({fe})")

# F1 event packet
f1 = sc.F1Reader.__new__(sc.F1Reader)
f1.events = []
hdr = bytearray(29)
for code, tail in ((b"OVTK", bytes([3, 7])), (b"COLL", bytes([1, 2])), (b"SCAR", bytes([1, 0])),
                   (b"FTLP", bytes([4]) + struct.pack("<f", 88.1)), (b"PENA", bytes([1, 2, 5, 255, 5, 3, 0]))):
    f1._event(bytes(hdr) + code + tail + bytes(8))
kinds = [(e["type"], e.get("car"), e.get("other")) for e in f1.events]
check(("overtake", 3, 7) in kinds and ("collision", 1, 2) in kinds and ("fastest_lap", 4, None) in kinds and
      any(e["type"] == "safety_car" and e["kind"] == "sc" and e["phase"] == "deployed" for e in f1.events) and
      any(e["type"] == "penalty" and e["car"] == 5 and e["seconds"] == 5 for e in f1.events), f"F1 events ({kinds})")

# ---------------------------------------------------------------- the web page's API
from simcast.web import WebUI  # noqa: E402
cast = SimCast(sc, dict(DEFAULTS), audio=SimAudio(), log=lambda m: None, booth=False, save=False)
cast._simcoach_t = 1e18
web = WebUI(cast, log=lambda m: None)
check(web.start(port=18766), "web: starts")
base = web.url()


def post(path, body, token=True):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json",
                                          **({"X-SimCast-Token": web.token} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


with urllib.request.urlopen(base, timeout=5) as r:
    page = r.read().decode()
check(web.token in page and "SimCast" in page, "web: the control page carries its token")
check(post("api/settings", {"settings": {"chatter": "chatty"}}, token=False) == 403, "web: no token, no changes")
check(post("api/settings", {"settings": {"chatter": "chatty", "openai_api_key": "sk-secret-123456",
                                         "bogus": 1}}) == 200 and cast.cfg["chatter"] == "chatty",
      "web: settings change with the token")
check(post("api/settings", {"settings": {"chatter": "shouty"}}) == 200 and cast.cfg["chatter"] == "normal",
      "web: a bad value falls back to the default")
with urllib.request.urlopen(base + "state.json", timeout=5) as r:
    st = json.loads(r.read())
check("sk-secret" not in json.dumps(st) and st["settings"]["keys"]["openai_api_key"], "web: keys never sent back, only 'set'")
check(post("api/demo", {"on": True}) == 200 and cast.demo is not None, "web: demo race starts")
for asset in ("icon-256.png", "hero-car.jpg", "helmet-128.png", "favicon.png"):
    with urllib.request.urlopen(base + "assets/" + asset, timeout=5) as r:
        check(r.status == 200 and len(r.read()) > 1000, f"web: {asset}")
try:
    urllib.request.urlopen(base + "assets/..%2F..%2Fsim_cast.py", timeout=5)
    check(False, "web: no files outside assets")
except urllib.error.HTTPError as e:
    check(e.code == 404, "web: no files outside assets")
web.stop()
check(os.path.exists(os.path.join(REPO, "SimCast.ico")), "SimCast.ico in the repo")
done()
