"""Setup sheet: before -> after previews and the 'apply the setup' radio reply."""
from _common import check, done, headless_coach, load

sc = load()
items = [("Aero", "Rear wing", "-1 click"), ("Brakes", "Brake bias", "55.2 %"), ("Tyres", "Hot pressures", "-0.4 psi"),
         ("Fuel", "Starting fuel", "62 litres"), ("Electronics", "Traction control", "+1")]
sheet = {"items": items, "applied": [], "title": "Test Ring · Test Car", "sim": "TEST", "key": ("TEST", "Test Ring", "Test Car")}
rows = sc.SetupApplier.preview(sheet, range(len(items)))
check([r[0] for r in rows] == ["Fuel", "Pressures", "Brake bias", "Rear wing", "Traction control"], "Apply-all preview lists 5 changes")
check(("Pressures", "26.8 psi", "26.4 psi") in rows, "equal pressures shown once")
check(sc.SetupApplier.preview(sheet, [1]) == [("Brake bias", "56%", "55.2%")], "single tick preview")
check(sc.SetupApplier.preview(dict(sheet, applied=[0, 1, 2, 3, 4]), range(5)) == [], "nothing new -> empty preview")
cfg, voice, coach = headless_coach(sc)
coach.last_setup_sheet = dict(sheet, applied=[])
conv = sc.Conversation(cfg, coach, voice, sc.NullOverlay())
r1, r2 = conv.local("apply the setup"), conv.local("apply the setup")
check(r1.startswith("Applied 5 setup changes") and "62 litres" in r1 and "percent" in r1, f"radio reply says what changed: {r1}")
check("already applied" in r2, "second 'apply the setup' -> nothing to change")
done()
