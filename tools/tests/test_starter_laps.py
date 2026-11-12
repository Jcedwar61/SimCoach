"""Starter laps: track matching (name + length), car classes, plausible lap times, and the coach flow on a
simulated driver: loaded at session start, lined up with the sim over the first corners, braking beeps after
that, no delta or blame against it, replaced by the first lap, never saved; dropped on a mismatched layout."""
import os

from _common import check, done, headless_coach, load

sc = load()
T = sc.starter_track
for args, want in [(("ACC", "spa", 7004), "Spa"), (("iRacing", "Circuit de Spa-Francorchamps", 7004), "Spa"),
                   (("AC", "ks_brands_hatch gp", 3908), "BrandsHatch"), (("AC", "ks_brands_hatch indy", 1929), None),
                   (("F1 25", "Silverstone", 5891), "Silverstone"), (("F1 25", "Silverstone Reverse", 5891), None),
                   (("LMU", "Autodromo Nazionale Monza", 5793), "Monza"), (("ACC", "nurburgring", 5137), "Nuerburgring"),
                   (("AC", "ks_nordschleife", 20832), None), (("ACC", "red_bull_ring", 4318), "Spielberg"),
                   (("F1 25", "Abu Dhabi", 5281), None), (("ACC", "zolder", 4011), None), (("ACC", "spa", None), None),
                   (("EA WRC", "Monza rally", 5800), None), (("AMS2", "Interlagos GP", 4309), "SaoPaulo")]:
    check(T(*args) == want, f"track {args[1]!r} ({args[2]} m) -> {want}")
C = sc.car_class
for game, car, want in [("ACC", "Porsche 911 GT3 R (992)", "gt3"), ("iRacing", "Porsche 911 GT3 Cup (992)", "cup"),
                        ("ACC", "BMW M4 GT4", "gt4"), ("iRacing", "Global Mazda MX-5 Cup", "road"),
                        ("LMU", "Ferrari 499P", "proto"), ("LMU", "Oreca 07 Gibson", "proto"), ("F1 25", "Ferrari", "f1"),
                        ("iRacing", "Dallara F3", "formula"), ("LMU", "Ferrari 488 GTE Evo", "gte"),
                        ("RaceRoom", "car 1234", "gt3"), ("AC", "ks_ferrari_sf15t", "f1")]:
    check(C(game, car) == want, f"car {car!r} -> {want}")
times = {cls: sc.starter_reference("Spa", cls)["best_time"] for cls in sc.STARTER_CARS}
check(times["f1"] < times["proto"] < times["gte"] < times["gt3"] < times["gt4"] < times["road"], f"class order {times}")
check(125 < times["gt3"] < 150 and 95 < times["f1"] < 115 and 160 < times["road"] < 200, "Spa lap times plausible")
for tid in sc.STARTER_TRACKS:
    r = sc.starter_reference(tid, "gt3")
    check(r is not None and len(r["corners"]) >= 4 and sc.ref_problem({"key": ["x", "y", "z"], **r}) is None,
          f"{tid}: complete reference, {len(r['corners']) if r else 0} corners")


class Rec(sc.NullOverlay):
    def __init__(self):
        self.posts = []

    def post(self, **kw):
        self.posts.append(kw)


def drive(track, length, profile_tid="Spa", true_shift=12, laps=2.3, enabled=True):
    """A driver lapping 8 % slower than the starter lap, on a sim whose start line sits true_shift bins away."""
    ov = Rec()
    cfg = sc.load_config()
    cfg.update(driver_name="Sam", starter_laps=enabled, shared_refs=False, brake_callouts="all")
    cfg, voice, coach = headless_coach(sc, cfg, ov)
    said = []
    voice.log = lambda m: said.append(m)
    prof = sc.starter_reference(profile_tid, "gt3", shift=true_shift)["ref"]
    BINS, dt = sc.BINS, 1 / 60
    d, t, lap_t, laps_done, last = 0.0, 0.0, 0.0, 0, 0.0
    beeps_lap1, saved_during_lap1, events = 0, False, []
    sc.BEEP_LOG.clear()
    while laps_done < laps:
        b = min(BINS - 1, int(d / length * BINS))
        v = max(10.0, prof["speed"][b] * 0.92)
        f = sc.Frame("ACC", track, "Porsche 911 GT3 R (992)", laps_done, d / length, v, prof["thr"][b], prof["brk"][b], 0.0,
                     3, 6000.0, lap_t, last, False, False, fuel=50.0, fuel_cap=100.0, track_len=length, session="practice")
        coach.update(f, t)
        t += dt
        lap_t += dt
        d += v / 3.6 * dt
        if laps_done == 0 and os.path.exists(coach._path()):
            saved_during_lap1 = True
        if d >= length:
            d -= length
            if laps_done == 0:
                beeps_lap1 = len(sc.BEEP_LOG)
                events.append(("lap1_said", list(said)))
                events.append(("lap1_posts", len(ov.posts)))
            laps_done, last, lap_t = laps_done + 1, lap_t, 0.0
    return coach, said, ov, beeps_lap1, saved_during_lap1, events


coach, said, ov, beeps, saved1, ev = drive("spa", 7004)
lap1 = ev[0][1] if ev else said
check(any("built a starter lap for Spa" in m and "GT3 car" in m for m in said), "starter lap announced at session start")
check(any("Starter lap lined up" in m for m in lap1), "lined up during the first lap")
base = sc.starter_reference("Spa", "gt3")["corners"]
n_lap1 = ev[1][1] if len(ev) > 1 else len(ov.posts)
check(not any(p.get("delta") not in (None, "--.--") for p in ov.posts[:n_lap1]), "no live delta against the starter lap")
check(any(p.get("delta") not in (None, "--.--") for p in ov.posts[n_lap1:]), "live delta back once it's the driver's own lap")
check(beeps > 0, f"braking beeps on lap one after lining up ({beeps})")
check(not any(" lost. " in m for m in lap1), "no 'time lost' callouts against the starter lap")
check(not saved1, "starter lap never saved as a reference")
check(any("That's your own reference now" in m for m in said) and coach.ref_source == "own", "first lap replaces it")
own = sc.json.load(open(coach._path(), encoding="utf-8")) if os.path.exists(coach._path()) else {}
check(own.get("source") == "own", "the saved reference is the driver's own")
# the alignment finds the sim's start-line offset, small or several percent of a lap, on different tracks
for tid, nm, L, off in (("Spa", "spa", 7004, 12), ("Spa", "spa", 7004, -140), ("Monza", "monza", 5758, 110),
                        ("Suzuka", "suzuka", 5747, 150), ("Zandvoort", "zandvoort", 4244, -60)):
    c2, said2, *_ = drive(nm, L, profile_tid=tid, true_shift=off, laps=0.6)
    got = (c2._starter or {}).get("shift")
    check(got is not None and abs(got - off) <= 4, f"{tid}: lined up by the sim's offset (found {got}, offset {off})")
c3, said3, *_ = drive("monza", 5758, laps=0.7)
check(any("doesn't match my starter lap" in m for m in said3) and c3.ref is None, "a layout that doesn't match is dropped")
c4, said4, *_ = drive("spa", 7004, laps=0.1, enabled=False)
check(any("Give me a clean lap" in m for m in said4) and c4.ref is None, "switched off in Settings: no starter lap")
done()
