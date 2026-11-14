"""SimCast: the race tracker, the commentary booth, the AI booth (with a stand-in model), the web page's API and
the sim readers' whole-field data. Everything runs on a simulated clock with silent audio."""
import json
import os
import re
import struct
import sys

import tempfile

from _common import REPO, check, done

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="simcast-test-")
sys.path.insert(0, REPO)
from simcast import sims as sc                        # noqa: E402  (SimCast's own readers: no SimCoach)
from simcast import providers                         # noqa: E402
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
cast = headless_run(laps=6, seed=5, log=lambda m: None)
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


booth = ai_mod.AIBooth(lambda: dict(DEFAULTS, openai_api_key="test", ai_colour=True), fake_chat, providers._json_reply,
                       log=lambda m: None)
booth.sync = True
cast = headless_run(laps=5, seed=5, booth=booth, log=lambda m: None)
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


booth = ai_mod.AIBooth(lambda: dict(DEFAULTS, openai_api_key="test"), broken_chat, providers._json_reply, log=lambda m: None)
booth.sync = True
cast = headless_run(laps=4, seed=5, booth=booth, log=lambda m: None)
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

# ---------------------------------------------------------------- settings
cast = SimCast(dict(DEFAULTS), audio=SimAudio(), log=lambda m: None, booth=False, save=False)
cast.update_settings({"chatter": "chatty", "openai_api_key": "sk-secret-123456", "bogus": 1})
check(cast.cfg["chatter"] == "chatty" and "bogus" not in cast.cfg, "settings: change, unknown keys ignored")
cast.update_settings({"chatter": "shouty", "volume": 7, "openai_api_key": ""})
check(cast.cfg["chatter"] == "normal" and cast.cfg["volume"] == 1.0, "settings: bad values fall back or clamp")
check(cast.cfg["openai_api_key"] == "sk-secret-123456", "settings: an empty key box keeps the saved key")
st = cast.state()
check("sk-secret" not in json.dumps(st) and st["settings"]["keys"]["openai_api_key"],
      "settings: keys never shown back, only 'set'")
cast.start_demo(3)
check(cast.demo is not None and cast.source == "Demo", "demo race starts")
cast.stop_demo()
check(cast.demo is None and not cast.source, "demo race stops")
for asset in ("icon-256.png", "icon-48.png", "logo-40.png", "hero-car-240.png", "helmet-32.png"):
    check(os.path.getsize(os.path.join(REPO, "simcast", "assets", asset)) > 500, f"asset {asset}")

# ---------------------------------------------------------------- stands alone
import ast  # noqa: E402
for root, _d, files in os.walk(os.path.join(REPO, "simcast")):
    for fn in files:
        if fn.endswith(".py"):
            tree = ast.parse(open(os.path.join(root, fn), encoding="utf-8").read())
            mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module} | \
                   {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
            check("sim_coach" not in mods, f"stands alone: {fn} doesn't import sim_coach")
check("sim_coach" not in sys.modules, "stands alone: SimCoach never loaded")

# ---------------------------------------------------------------- AI: the best model, picked automatically
class _M:
    def __init__(self, i, c):
        self.id, self.created = i, c


class _FakeClient:
    def __init__(self, ids):
        self.ids = ids
        self.models = self

    def with_options(self, **kw):
        return self

    def list(self):
        return [_M(i, c) for i, c in self.ids]


real_client = providers.openai_client
cfg = dict(DEFAULTS, openai_api_key="k-openai", gemini_api_key="k-gemini")
check(providers.ai_model(cfg, "openai") == providers.PREFERRED["openai"][0], "AI: before asking, the first preferred model")
providers.openai_client = lambda key, base=None: _FakeClient(
    [("gpt-5.6-luna", 1), ("gpt-6.1-terra", 2), ("gpt-6-luna-tts", 3), ("gpt-4o", 0), ("text-embedding-3", 1)]
    if key == "k-openai" else [("models/gemini-3.1-pro-preview", 1), ("models/gemini-3.5-flash-lite", 2)])
providers.detect_models(cfg, "openai")
providers.detect_models(cfg, "gemini")
check(providers.ai_model(cfg, "openai") == "gpt-6.1-terra", "AI: OpenAI picks the best model this key can use")
check(providers.ai_model(cfg, "gemini") == "gemini-3.1-pro-preview", "AI: Gemini too (ids without 'models/')")
check(providers.tts_model(cfg) == "gpt-6-luna-tts", "AI: the newest OpenAI speech model is picked for OpenAI voices")
check("gpt-4o" not in providers.model_choices(cfg, "openai") and "text-embedding-3" not in providers.model_choices(cfg, "openai"),
      "AI: retired and non-chat models aren't offered")
check(providers.ai_model(dict(cfg, openai_model="gpt-5.6-luna"), "openai") == "gpt-5.6-luna", "AI: a model picked by hand wins")
providers.openai_client = real_client
check(providers.ai_model(dict(cfg, deepseek_api_key="k"), "deepseek") == "deepseek-chat", "AI: DeepSeek's default")

# ---------------------------------------------------------------- solo mode (one car) and rally mode
from simcast.solo import StageStore  # noqa: E402


def drive(fn, until, cfg=None):
    a = SimAudio()
    c = SimCast(dict(DEFAULTS, game_setup=False, **(cfg or {})), audio=a, log=lambda m: None, booth=False, save=False)
    c.stages = StageStore(None)
    t = 0.0
    while t < until:
        f = fn(t)
        if f is not None:
            c.feed(f, t)
        c.tick(t)
        a.tick(t)
        t += 1 / 30
    return c, " ".join(ln.text for _, ln in a.spoken)


def solo_frame(t):
    lap = 80.0
    laps = int(max(0, t - 6) // lap)
    pct = (max(0, t - 6) % lap) / lap
    pos = 6 if t < 100 else 5
    f = sc.Frame("AC EVO", "Imola", "Ferrari 296 GT3", laps, pct, 0 if t < 6 else 150, 1, 0, 0, 4, 7000, pct * lap,
                 lap if laps else 0.0, False, False, track_len=4900.0, session="race", position=pos, cars=20,
                 race_laps=4, gap_ahead=2.0, gap_behind=1.5)
    f.car_ahead, f.car_behind = {"name": "Alex Rivera"}, {"name": "Kim Bauer"}
    f.race_over = laps >= 4
    return f


c, said = drive(solo_frame, 340, {"driver_name": "Sam Carter"})
check(c.mode == "solo" and not c.errors, f"solo: one car, its own mode ({c.mode}, {list(c.errors)})")
check("following Sam Carter" in said and re.search(r"past Rivera", said) and
      re.search(r"(chequered flag|crossing the line) in fifth", said),
      "solo: the intro, a place gained past the car ahead, the finish")
check(said.count("two seconds behind Rivera") <= 2, "solo: doesn't keep repeating the same running position")
check("Fastest lap of the race" not in said and " wins" not in said, "solo: never calls a 'race winner' or 'fastest lap' it can't know")

L = 5000.0


def stage_frame(t):
    starts, durs = [3, 160], [150, 140]
    runs = sum(1 for st, d in zip(starts, durs) if t >= st + d)
    for st, d in zip(starts, durs):
        if st <= t < st + d:
            el = t - st
            return sc.Frame("EA WRC", "Monte Carlo - Col de Turini", "Hyundai i20 N Rally1", runs, el / d,
                            130.0, 1, 0, 0, 4, 6000, el, durs[runs - 1] if runs else 0.0, False, False, track_len=L)
    return sc.Frame("EA WRC", "Monte Carlo - Col de Turini", "Hyundai i20 N Rally1", runs, 0.99999 if runs else 0.0,
                    0, 0, 0, 0, 0, 900, 0.0, durs[runs - 1] if runs else 0.0, False, False, track_len=L)


c, said = drive(stage_frame, 320, {"driver_name": "Sam Carter"})
check(c.mode == "rally" and not c.errors, f"rally: its own mode ({c.mode})")
check("Col de Turini" in said and re.search(r"away|Go!|off the line", said), "rally: the stage and the launch")
check("halfway split" in said and "up on the best" in said, "rally: splits against the best run on the second run")
check("new best on this stage by ten seconds" in said, "rally: a new stage best, by how much")
check(c.stages.get("EA WRC|Monte Carlo - Col de Turini|Hyundai i20 N Rally1")["best"] == 140.0, "rally: the best run is kept")

# ---------------------------------------------------------------- ACC's broadcasting API
from simcast.acc_broadcast import ACCBroadcast, read_config  # noqa: E402


def s_(x):
    b = x.encode()
    return struct.pack("<H", len(b)) + b


def lap(ms):
    return struct.pack("<iHHB", ms, 0, 0, 0) + bytes(4)


bc = ACCBroadcast(tempfile.mkdtemp(), log=lambda m: None)
bc.handle(bytes([1]) + struct.pack("<iBB", 7, 1, 1) + s_(""))
check(bc.conn_id == 7, "ACC: registered")
for idx, first, lastn, num in ((3, "Ana", "Silva", 88), (5, "Ben", "Okoro", 7)):
    bc.handle(bytes([6]) + struct.pack("<HB", idx, 1) + s_("Team") + struct.pack("<iBBHB", num, 0, 0, 1, 1) +
              s_(first) + s_(lastn) + s_(lastn[:3].upper()) + struct.pack("<BH", 0, 1))
bc.handle(bytes([2]) + struct.pack("<HHBBffi", 0, 0, 10, 5, 600000.0, 3600000.0, 5) + s_("set") + s_("cam") + s_("hud")
          + bytes([0]) + struct.pack("<fBBBBB", 50000.0, 20, 25, 0, 0, 0) + lap(101000))
for idx, pos, spline, loc in ((3, 1, 0.42, 1), (5, 2, 0.40, 2)):
    bc.handle(bytes([3]) + struct.pack("<HHBBfffBHHHHfHi", idx, 0, 1, 4, 0, 0, 0, loc, 180, pos, pos, pos, spline, 3, 0)
              + lap(101500) + lap(102000) + lap(50000))
bc.handle(bytes([7, 4]) + s_("Accident") + struct.pack("<ii", 1000, 5))
fe = sorted(bc.field(sc.field_entry), key=lambda e: e["position"])
check([e["name"] for e in fe] == ["Ana Silva", "Ben Okoro"] and fe[1]["in_pit"] and fe[1]["player"] and fe[0]["laps"] == 3
      and fe[0]["last"] == 102.0 and bc.session["type"] == "race", f"ACC: the grid from the broadcasting API ({fe})")
check(bc.events() == [{"type": "accident", "car": 5}], "ACC: the game's accident event")
check(read_config(tempfile.mkdtemp()) == (9000, "asd"), "ACC: default port and password when there's no file")

# ---------------------------------------------------------------- game setup
from simcast import gamesetup  # noqa: E402
docs = tempfile.mkdtemp()
wrc = os.path.join(docs, "My Games", "WRC", "telemetry")
os.makedirs(os.path.join(wrc, "udp"))
json.dump({"schema": 1, "udp": {"packets": [{"structure": "wrc", "packet": "session_update", "ip": "127.0.0.1",
                                             "port": 20777, "bEnabled": True}]}}, open(os.path.join(wrc, "config.json"), "w"))
dr2 = os.path.join(docs, "My Games", "DiRT Rally 2.0", "hardwaresettings")
os.makedirs(dr2)
open(os.path.join(dr2, "hardware_settings_config.xml"), "w").write(
    '<hardware_settings_config>\n <motion_platform>\n  <udp enabled="false" extradata="0" ip="127.0.0.1" port="20777" '
    'delay="1" />\n </motion_platform>\n</hardware_settings_config>\n')
accdir = os.path.join(docs, "Assetto Corsa Competizione", "Config")
os.makedirs(accdir)
open(os.path.join(accdir, "broadcasting.json"), "wb").write(
    json.dumps({"updListenerPort": 0, "connectionPassword": "pw", "commandPassword": ""}).encode("utf-16"))
done_ = gamesetup.setup_all(log=lambda m: None, documents=docs)
check(set(done_) == {"EA WRC", "DiRT Rally 2.0", "ACC"}, f"game setup: all three set up ({done_})")
c2 = json.load(open(os.path.join(wrc, "config.json")))
check(any(p["port"] == 20790 and p["structure"] == "simcast" and p["bEnabled"] for p in c2["udp"]["packets"]) and
      any(p["structure"] == "wrc" for p in c2["udp"]["packets"]), "game setup: EA WRC sends SimCast's packet, SimHub's kept")
st_ = json.load(open(os.path.join(wrc, "udp", "simcast.json")))
check(st_["packets"][0]["channels"][0] == "packet_uid" and len(st_["packets"][0]["channels"]) == len(sc.WRC_CHANNELS),
      "game setup: EA WRC packet layout matches the reader")
x = open(os.path.join(dr2, "hardware_settings_config.xml")).read()
check('enabled="true"' in x and 'extradata="3"' in x and os.path.exists(os.path.join(dr2, "hardware_settings_config.xml.simcast-backup")),
      "game setup: DiRT Rally 2.0 UDP on with extradata 3, backed up")
check(read_config(docs) == (9000, "pw"), "game setup: ACC broadcasting port on, password kept")
check(gamesetup.setup_all(log=lambda m: None, documents=docs) == [], "game setup: a second run changes nothing")

# ---------------------------------------------------------------- voices, guide, licences
from simcast.audio import VOICES, engine_of  # noqa: E402
check(engine_of("kokoro:bm_george") == ("kokoro", "bm_george") and engine_of("en-GB-RyanNeural")[0] == "edge" and
      engine_of("openai:ash") == ("openai", "ash") and engine_of("google:en-GB") == ("google", "en-GB"), "voices: engines")
fams = {engine_of(v)[0] for _, v in VOICES}
check(fams == {"edge", "kokoro", "google", "openai"}, "voices: Microsoft, Kokoro, Google and OpenAI offered")
from simcast.guide import TOPICS  # noqa: E402
gtext = " ".join(t for _, t in TOPICS)
for word in ("Play on", "Demo race", "Captions window", "install-simcast-wine.sh", "Automatic", "CrewChiefEx",
             "EA SPORTS WRC", "DiRT Rally 2.0", "AC Rally", "AC EVO", "ACC", "iRacing", "F1 25", "Le Mans Ultimate",
             "rFactor 2", "Automobilista 2", "RaceRoom", "Assetto Corsa"):
    check(word in gtext, f"guide covers: {word}")
lic = os.path.join(REPO, "simcast", "licenses")
notice = open(os.path.join(lic, "THIRD_PARTY_NOTICES.txt")).read()
check("MIT License" in open(os.path.join(lic, "LICENSE.txt")).read() and "The Go Authors" in notice and
      all(n in notice for n in ("kokoro-onnx", "ONNX Runtime", "gTTS", "uv ")), "licences: SimCast MIT and the notices")
check(os.path.exists(os.path.join(REPO, "SimCast.ico")), "SimCast.ico in the repo")
done()
