"""Coach personalities: voice commands switch only when asked, and no real coaches' names are left anywhere."""
import re

from _common import check, done, headless_coach, load

sc = load()
cfg, voice, coach = headless_coach(sc)
check(cfg["driver_name"] == "" and cfg["crew_language"] == "clean", "first-run defaults: no name, clean language")
conv = sc.Conversation(cfg, coach, voice, sc.NullOverlay())
for q, k in [("data coach please", "naujoks"), ("switch to composed style", "mansell"), ("change coach to rotation", "almeida"),
             ("use the feel coach", "bentley"), ("exit mode", "perel"), ("go back to apex coach", "apex"), ("calm coach", "mansell")]:
    cfg["coach_personality"] = "apex" if k != "apex" else "naujoks"
    conv.local(q)
    check(cfg["coach_personality"] == k, f"'{q}' switches to {k}")
for q in ["coach how was my exit", "coach where am i losing time on exit", "what does the data say coach",
          "how do i feel the rotation in turn three", "coach i lost the rear on exit"]:
    cfg["coach_personality"] = "apex"
    conv.local(q)
    check(cfg["coach_personality"] == "apex", f"'{q}' does not switch")
names = re.compile(r"almeida|mansell|bentley|perel|naujoks|suellio|driver61|speed secrets|coach dave|popometer", re.I)
txt = ("".join(n for n, _ in sc.COACH_PERSONALITIES) + "".join(sc.COACH_PERSONA_PROMPTS.values())
       + "".join(p[2] for p in sc.Conversation._PERSONAS))
check(not names.findall(txt), "no real names in labels, prompts or replies")
check("the driver" in sc.build_system_prompt(dict(cfg, driver_name="")), "empty name -> 'the driver' in the AI prompt")
done()
