"""Assetto Corsa setup sheet: ticking a box changes the car's real setup through SimCoach's helper inside the game.
Runs the helper's actual Lua code (lupa) against a stand-in for Custom Shaders Patch: a car with setup items like a
real AC car, pits / practice rules, and the shared memory between SimCoach and the helper."""
import os
import struct
import sys

from _common import check, done, load

try:
    try:
        import lupa.luajit21 as lupa      # the same Lua engine as Assetto Corsa / CSP
    except ImportError:
        import lupa
except ImportError:
    print("SKIP: lupa (pip install lupa) is needed to run the helper's Lua code")
    sys.exit(0)

sc = load()
L = lupa.LuaRuntime(unpack_returned_tuples=True)
print("Lua engine:", L.eval("jit and jit.version or _VERSION"))
G = L.globals()
FAKE_AC = r"""
car = { brakeBias = 0.62, tractionControlMode = 3, tractionControlModes = 8, absMode = 2, absModes = 6, isInPit = true }
sim = { rainIntensity = 0, rainWetness = 0, rainWater = 0, ambientTemperature = 22, roadTemperature = 30, roadGrip = 1,
        timeMultiplier = 1, isWeatherFXActive = false, timeTotalSeconds = 0, isOnlineRace = false }
resetAllowed = false
-- the car's setup items, as Assetto Corsa reports them (value in raw units, shown x displayMultiplier)
spinners = {
  { name = 'FUEL', min = 1, max = 120, step = 1, value = 30, displayMultiplier = 1 },
  { name = 'PRESSURE_LF', min = 15, max = 40, step = 1, value = 26, displayMultiplier = 1 },
  { name = 'PRESSURE_RF', min = 15, max = 40, step = 1, value = 26, displayMultiplier = 1 },
  { name = 'PRESSURE_LR', min = 15, max = 40, step = 1, value = 25, displayMultiplier = 1 },
  { name = 'PRESSURE_RR', min = 15, max = 40, step = 1, value = 25, displayMultiplier = 1 },
  { name = 'FRONT_BIAS', min = 50, max = 70, step = 1, value = 62, displayMultiplier = 1 },
  { name = 'WING_1', min = 0, max = 10, step = 1, value = 3, displayMultiplier = 1 },
  { name = 'WING_2', min = 0, max = 12, step = 1, value = 7, displayMultiplier = 1 },
  { name = 'ARB_FRONT', min = 1, max = 7, step = 1, value = 4, displayMultiplier = 1 },
  { name = 'ARB_REAR', min = 1, max = 7, step = 1, value = 4, displayMultiplier = 1 },
  { name = 'TRACTION_CONTROL', min = 0, max = 8, step = 1, value = 3, displayMultiplier = 1 },
  { name = 'COMPOUND', min = 0, max = 2, step = 1, value = 0, displayMultiplier = 1,
    items = { 'Slick Soft (S)', 'Slick Medium (M)', 'Wet (W)' } },
}
local function copy(t) local o = {} for k, v in pairs(t) do o[k] = v end return o end
ac = {}
function ac.getPatchVersionCode() return 3000 end
function ac.getSim() return sim end
function ac.getCar(i) return car end
function ac.isCarResetAllowed() return resetAllowed end
function ac.getSetupSpinners() local o = {} for i, s in ipairs(spinners) do o[i] = copy(s) end return o end
function ac.setSetupSpinnerValue(name, v)
  if not (car.isInPit or resetAllowed) then return end      -- the game only takes setup changes in the pits
  for _, s in ipairs(spinners) do if s.name == name then s.value = v end end
  if name == 'FRONT_BIAS' then car.brakeBias = v / 100 end
end
function ac.setBrakeBias(x) car.brakeBias = x end
function ac.setTC(x) car.tractionControlMode = x end
function ac.setABS(x) car.absMode = x end
physics = { awakeCar = function() end }
mmf = {}
local function mk() local t = { kind = {}, op = {}, val = {}, status = {}, before = {}, after = {} }
  for i = 0, 15 do t.kind[i] = 0; t.op[i] = 0; t.val[i] = 0; t.status[i] = 0; t.before[i] = 0; t.after[i] = 0 end
  for _, f in ipairs({'version', 'seq', 'count', 'beat', 'ackSeq', 'flags', 'spinners'}) do t[f] = 0 end
  return t end
function ac.writeMemoryMappedFile(name, layout) mmf[name] = mmf[name] or mk() return mmf[name] end
function ac.readMemoryMappedFile(name, layout) mmf[name] = mmf[name] or mk() return mmf[name] end
script = {}
ui = setmetatable({}, { __index = function() return function() end end })
"""
L.execute(FAKE_AC)
L.execute(sc.CSP_WEATHER_LUA)
update = G.script.update
update(0.016)


class LuaTransport:
    """The shared memory, bridged to the Lua tables; every poll is one game frame."""
    def __init__(self):
        self.frames = 0

    def tick(self):
        update(0.016)
        self.frames += 1

    def write_cmd(self, data):
        m = G.mmf["SimCoach.CSPSetup.v2"]
        if m is None:
            return False
        version, seq, count = struct.unpack_from("<3i", data, 0)
        kinds = struct.unpack_from("<16i", data, 12)
        ops = struct.unpack_from("<16i", data, 76)
        vals = struct.unpack_from("<16f", data, 140)
        m.version, m.count = version, count
        for i in range(16):
            m.kind[i], m.op[i], m.val[i] = kinds[i], ops[i], vals[i]
        m.seq = seq
        return True

    def read_res(self):
        r = G.mmf["SimCoach.CSPSetupResult.v1"]
        if r is None:
            return None
        return (struct.pack("<6i", r.version, r.beat, r.ackSeq, r.flags, r.count, r.spinners)
                + struct.pack("<16i", *[int(r.status[i]) for i in range(16)])
                + struct.pack("<16f", *[float(r.before[i]) for i in range(16)])
                + struct.pack("<16f", *[float(r.after[i]) for i in range(16)]))


sc.CSPSetupLink.transport = LuaTransport()


def spinner(name):
    for s in G.spinners.values():
        if s.name == name:
            return s.value


st = sc.CSPSetupLink.state()
check(st is not None and st["flags"] & 2, "SimCoach sees the helper running, car in the pits")

items = [("Fuel", "Fuel load", "42 litres"),
         ("Tyres", "Hot pressures", "27.0 to 27.4 psi on slicks"),
         ("Brakes", "Brake bias", "0.5 % rearward (rotation on trail-braking)"),
         ("Aero", "Rear wing", "-1 to -2 clicks (top speed)"),
         ("Suspension", "Front anti-roll bar", "1 click softer than the rear"),
         ("Electronics", "Traction control", "Up 1 click"),
         ("Fuel", "Use per lap", "About 2.4 litres"),
         ("Brakes", "Brake ducts", "Balanced")]
sheet = {"items": items, "applied": set(), "sim": "AC", "title": "Spa · BMW M4 GT3"}
log = []

r = sc.SetupApplier.toggle_item(sheet, 0, enabled=True, log=log.append)
check(spinner("FUEL") == 42 and 0 in r["applied"], f"fuel: the car's fuel setting is now 42 ({spinner('FUEL')})")
check("Fuel 30 L → 42 L" in r["status"], f"status says what changed: {r['status']}")
r = sc.SetupApplier.toggle_item(sheet, 1, enabled=True, log=log.append)
check([spinner(x) for x in ("PRESSURE_LF", "PRESSURE_RF", "PRESSURE_LR", "PRESSURE_RR")] == [27, 27, 27, 27],
      "pressures: all four set (27.2 psi rounds to the car's 1 psi steps)")
r = sc.SetupApplier.toggle_item(sheet, 3, enabled=True, log=log.append)
check(spinner("WING_2") == 6 and spinner("WING_1") == 3, "rear wing: one click less on the rear wing item, front untouched")
r = sc.SetupApplier.toggle_item(sheet, 4, enabled=True, log=log.append)
check(spinner("ARB_FRONT") == 3, "front anti-roll bar one click softer")
r = sc.SetupApplier.toggle_item(sheet, 2, enabled=True, log=log.append)
check(spinner("FRONT_BIAS") == 61 and abs(G.car.brakeBias - 0.61) < 1e-6,
      f"brake bias 0.5 % rearward on a car with 1 % steps: one step back, 62 -> {spinner('FRONT_BIAS')}")
r = sc.SetupApplier.toggle_item(sheet, 5, enabled=True, log=log.append)
check(spinner("TRACTION_CONTROL") == 4, "traction control up one")
r = sc.SetupApplier.toggle_item(sheet, 6, enabled=True, log=log.append)
check(6 in r["applied"], "a note (fuel per lap) can be ticked: nothing to change on the car")

r = sc.SetupApplier.toggle_item(sheet, 0, enabled=False, log=log.append)
check(spinner("FUEL") == 30 and 0 not in r["applied"], "unticking puts the car's own value back (30 L)")
r = sc.SetupApplier.toggle_item(sheet, 3, enabled=False, log=log.append)
check(spinner("WING_2") == 7, "and the wing back to 7")

# on track in a race: the game refuses setup changes; the box doesn't stay ticked and the reason is given
G.car.isInPit = False
r = sc.SetupApplier.toggle_item(sheet, 0, enabled=True, log=log.append)
check(spinner("FUEL") == 30 and 0 not in r["applied"], "out of the pits: not applied, box unticked")
check("in the pits" in r["status"], f"and the driver is told why: {r['status']}")
G.resetAllowed = True                       # single-player practice: changes allowed anywhere
r = sc.SetupApplier.toggle_item(sheet, 0, enabled=True, log=log.append)
check(spinner("FUEL") == 42, "single-player practice: applied on track too")
G.car.isInPit = True
G.resetAllowed = False

# a car without the setting
sheet2 = {"items": [("Differential", "Preload", "Up 2 clicks")], "applied": set(), "sim": "AC"}
r = sc.SetupApplier.toggle_item(sheet2, 0, enabled=True, log=log.append)
check(0 not in r["applied"] and "not on this car" in r["status"], f"setting the car doesn't have: {r['status']}")

# Apply all, then Revert all
fresh = {"items": items[:6], "applied": set(), "sim": "AC"}
before = {n: spinner(n) for n in ("FUEL", "WING_2", "ARB_FRONT", "TRACTION_CONTROL")}
r = sc.SetupApplier.apply_all(fresh, enabled=True, log=log.append)
check(len(r["applied"]) >= 5 and spinner("WING_2") == before["WING_2"] - 1, f"apply all: {r['status']}")
r = sc.SetupApplier.apply_all(fresh, enabled=False, log=log.append)
check({n: spinner(n) for n in before} == before and not r["applied"], "revert all: every value back where it was")

# wet tyres, by the compound's name
wet = {"items": [("Tyres", "Compound", "Wets for the rain")], "applied": set(), "sim": "AC"}
sc.SetupApplier.toggle_item(wet, 0, enabled=True, log=log.append)
check(spinner("COMPOUND") == 2, "wet tyres: the compound named Wet")
sc.SetupApplier.toggle_item(wet, 0, enabled=False, log=log.append)
check(spinner("COMPOUND") == 0, "back to the soft slick it was on")

# the radio command "apply the setup" uses the same path and reads back what really changed
from _common import headless_coach  # noqa: E402
cfg, voice, coach = headless_coach(sc)
coach.last_setup_sheet = {"items": items[:4], "applied": set(), "sim": "AC", "title": "Spa · BMW"}
conv = sc.Conversation(cfg, coach, voice, sc.NullOverlay(), log=lambda m: None)
ans = conv.local("apply the setup")
check(ans.startswith("Done on the car:") and "rear wing 7 to 6" in ans.lower(), f"radio: {ans}")
G.car.isInPit = False
coach.last_setup_sheet = {"items": [("Aero", "Rear wing", "+1 click")], "applied": set(), "sim": "AC"}
ans = conv.local("apply the setup")
check("pits" in ans, f"radio, out of the pits: {ans}")
G.car.isInPit = True

# helper not running (Assetto Corsa closed, or no CSP): nothing pretends to be applied
class Dead:
    def read_res(self):
        return None

    def write_cmd(self, d):
        return False

    def tick(self):
        pass


sc.CSPSetupLink.transport = Dead()
r = sc.SetupApplier.toggle_item({"items": items[:1], "applied": set(), "sim": "AC"}, 0, enabled=True, log=log.append)
check(not r["applied"] and "helper isn't running" in r["status"], "no helper: box unticked, says what's needed")
check(not any("SimCoach_Race.ini" in p_ and "Assetto Corsa" + os.sep + "setups" in p_ for p_ in [r.get("setup_file") or ""]),
      "nothing written into Assetto Corsa's own setups folder")
done()
