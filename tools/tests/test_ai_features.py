"""AI features beyond chat: a provider per job (task routing), the written session analysis in the report and the
after-race text, and loosely worded voice commands mapped to radio commands. Runs against a local stand-in for the
OpenAI-style API (no real keys or network)."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from _common import check, done, headless_coach, load

sc = load()
LOG = []
REPLY = {"text": "OK"}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        LOG.append((self.path, body))
        if self.path.startswith("/down"):
            code, obj = 503, {"error": {"message": "overloaded"}}
        else:
            code, obj = 200, {"id": "x", "object": "chat.completion", "created": 0, "model": body["model"],
                              "choices": [{"index": 0, "finish_reason": "stop",
                                           "message": {"role": "assistant", "content": REPLY["text"]}}]}
        d = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(d)))
        self.end_headers()
        self.wfile.write(d)


srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_port}"
P = sc.AI_PROVIDERS
for pid in P:
    P[pid]["base_url"] = f"{base}/{pid}/v1"
msgs = [{"role": "user", "content": "hi"}]

# --- task routing -------------------------------------------------------------------------------------------------
cfg = dict(sc.DEFAULT_CONFIG, ai_provider="openai", openai_api_key="k1", deepseek_api_key="k3", gemini_api_key="",
           ai_tasks={"banter": "deepseek", "report": "gemini"})
_, who = sc.ai_chat_ex(cfg, msgs, task="banter")
check(who.startswith("DeepSeek") and LOG[-1][0].startswith("/deepseek"), "banter goes to the provider chosen for it")
_, who = sc.ai_chat_ex(cfg, msgs, task="chat")
check(who.startswith("OpenAI"), "a task with no choice uses the main provider")
_, who = sc.ai_chat_ex(cfg, msgs, task="report")
check(who.startswith("OpenAI"), "a task's provider with no key falls back to the main provider")
check(sc.ai_order(cfg, "banter") == ["deepseek", "openai"], f"order: task provider, then main ({sc.ai_order(cfg, 'banter')})")
P["deepseek"]["base_url"] = f"{base}/down/v1"
_, who = sc.ai_chat_ex(cfg, msgs, task="banter")
check(who.startswith("OpenAI"), "task provider down -> main provider answers")
P["deepseek"]["base_url"] = f"{base}/deepseek/v1"
cfg2 = dict(sc.DEFAULT_CONFIG, ai_provider="openai", openai_api_key="", deepseek_api_key="k3")
check(sc.ai_any_key(cfg2) and sc.ai_chat_ex(cfg2, msgs)[1].startswith("DeepSeek"),
      "main provider has no key but another does: that one answers (fallback on)")
check(not sc.ai_any_key(dict(cfg2, ai_fallback=False)), "fallback off: only the main key counts")
c3 = dict(sc.DEFAULT_CONFIG, ai_tasks={"banter": "deepseek", "bogus": "openai", "chat": "nobody"})
import os, tempfile  # noqa: E401
os.makedirs(os.path.dirname(sc.CONFIG_PATH), exist_ok=True)
with open(sc.CONFIG_PATH, "w") as fh:
    json.dump(c3, fh)
check(sc.load_config()["ai_tasks"] == {"banter": "deepseek"}, "unknown tasks and providers are dropped on load")

# --- parsing and rendering the analysis ------------------------------------------------------------------------
good = {"headline": "Solid <b>pace</b>, Turn 3 is the gap.", "strengths": ["Clean exits"], "time_loss": ["Turn 3: 0.3 s"],
        "plan": ["Brake 5 m later into Turn 3", "Smooth throttle out of Turn 5"], "progress": ""}
a = sc.parse_analysis("```json\n" + json.dumps(good) + "\n```")
check(a and a["plan"][0].startswith("Brake") and a["strengths"] == ["Clean exits"], "analysis parsed from a fenced reply")
check(sc.parse_analysis("Just some prose.") is None and sc.parse_analysis('{"headline": "x"}') is None,
      "prose or a reply without a plan is rejected")
h = sc.analysis_html(dict(a, who="OpenAI test"))
check("Coach's analysis" in h and "&lt;b&gt;" in h and "<ol><li>Brake" in h, "analysis HTML is escaped and has the plan")
check(sc.analysis_html(None) == "", "no analysis -> nothing in the report")

# --- end to end: laps, report, AI analysis rewritten into it -----------------------------------------------------
REPLY["text"] = json.dumps(good)
cfg = sc.load_config()
cfg.update(driver_name="Sam", shared_refs=False, ai_provider="openai", openai_api_key="k1", ai_tasks={})
cfg, voice, coach = headless_coach(sc, cfg)
prof = sc.starter_reference("Spa", "gt3")
ref, base_t, length = prof["ref"], prof["best_time"], 7004
d = t = lap_t = last = 0.0
n, dt, laps = 0, 1 / 30, [146.0, 143.0, 142.6]
while n < len(laps):
    b = min(sc.BINS - 1, int(d / length * sc.BINS))
    v = max(10.0, ref["speed"][b] * base_t / laps[n])
    coach.update(sc.Frame("ACC", "spa", "Porsche 911 GT3 R (992)", n, d / length, v, ref["thr"][b], ref["brk"][b], 0.0, 3,
                          6000.0, lap_t, last, False, False, fuel=50.0, fuel_cap=100.0, track_len=length,
                          session="practice"), t)
    t, lap_t, d = t + dt, lap_t + dt, d + v / 3.6 * dt
    if d >= length:
        d, n, last, lap_t = d - length, n + 1, lap_t, 0.0
check(len(coach.history) >= 2, f"laps recorded ({len(coach.history)})")
LOG.clear()
path = coach.end_session()
for _ in range(100):
    if coach.ai_analysis:
        break
    time.sleep(0.05)
time.sleep(0.2)
check(coach.ai_analysis and coach.ai_analysis.get("who", "").startswith("OpenAI"), "analysis arrives in the background")
rep = open(path, encoding="utf-8").read()
check("Coach's analysis" in rep and "Practice plan" in rep and "Brake 5 m later" in rep, "report rewritten with it")
sent = json.loads(LOG[-1][1]["messages"][1]["content"].split("SESSION DATA: ", 1)[1])
check(sent.get("corner_table") and sent.get("all_laps") and "previous_sessions" in sent, "AI gets corners, laps, history")
n_calls = len(LOG)
coach.snapshot_report()
time.sleep(0.3)
check(len(LOG) == n_calls, "no new laps -> the analysis isn't asked for again")
txt = coach.after_race_debrief(coach.last_frame, time.monotonic(), speak=False)
body = open(coach.last_debrief_txt, encoding="utf-8").read()
check("Coach's analysis" in body and "Practice plan" in body, "after-race text includes the analysis")
cfg["ai_reports"] = False
coach.ai_analysis = None
check(coach.request_ai_analysis(coach.past_sessions()) is False, "switched off -> not asked")

# --- loosely worded commands ------------------------------------------------------------------------------------
cfg["talk_level"] = 1
conv = sc.Conversation(cfg, coach, voice, sc.NullOverlay(), log=lambda m: None)
r = conv.ai_command("CMD: be quiet")
check(r and r[1] == "be quiet" and cfg["talk_level"] == 0, f"'CMD: be quiet' goes quiet ({r})")
r = conv.ai_command("CMD: switch to data coach.")
check(r and cfg["coach_personality"] == "naujoks", f"persona switch through the AI ({r})")
r = conv.ai_command("CMD: braking tones off")
check(r and "off" in r[0].lower(), f"braking tones off ({r})")
r = conv.ai_command("CMD: reset reference")
check(r and r[1] is None and coach.best_time, "a command outside the safe list is refused (reference kept)")
r = conv.ai_command("CMD: work on turn 2 for 3 laps")
check(r and r[1] == "work on turn 2 for 3 laps" and r[0], f"drill command ({r[0][:60] if r else r})")
check(conv.ai_command("Brake later into turn 3.") is None, "a normal answer is not a command")
for c in sc.Conversation.AI_COMMANDS:
    phrase = c.replace("N", "2").replace("M", "3")
    check(sc.Conversation._RE_AI_CMD.match(phrase) is not None, f"listed command matches: {phrase}")
    if phrase not in ("full briefing", "after race debrief", "session report"):  # these start work of their own
        check(conv.local(phrase) is not None, f"listed command is one the radio understands: {phrase}")
REPLY["text"] = "CMD: talk more"
cfg.update(talk_level=1, ai_commands=True)
said = []
voice.say = lambda text, *a, **k: said.append(text)
conv._ask_openai("mate give me more chat on the radio")
check(cfg["talk_level"] == 2 and said and "more" in said[-1].lower(), f"AI-mapped command runs end to end ({said[-1:]})")
check("Radio commands" in LOG[-1][1]["messages"][0]["content"], "the command list is in the system prompt")
cfg["ai_commands"] = False
REPLY["text"] = "Copy that."
conv._ask_openai("how's it going")
check("Radio commands" not in LOG[-1][1]["messages"][0]["content"], "commands off -> not in the prompt")
done()
