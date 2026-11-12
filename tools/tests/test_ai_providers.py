"""AI providers: routing, fallback to other keys, dropping an unsupported option, errors naming the right provider.
Runs against a local stand-in for the OpenAI-style API (no real keys or network)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from _common import check, done, load

sc = load()
LOG = []


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        LOG.append((self.path, body))

        def send(code, obj):
            d = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(d)))
            self.end_headers()
            self.wfile.write(d)
        if self.path.startswith("/down"):
            return send(503, {"error": {"message": "overloaded"}})
        if self.path.startswith("/badkey"):
            return send(401, {"error": {"message": "bad key"}})
        if "reasoning_effort" in body and self.path.startswith("/noeffort"):
            return send(400, {"error": {"message": 'Unknown name "reasoning_effort": Cannot find field.'}})
        send(200, {"id": "x", "object": "chat.completion", "created": 0, "model": body["model"],
                   "choices": [{"index": 0, "finish_reason": "stop",
                                "message": {"role": "assistant", "content": f"OK from {self.path}"}}]})


srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_port}"
P = sc.AI_PROVIDERS
msgs = [{"role": "user", "content": "hi"}]
cfg = dict(sc.DEFAULT_CONFIG, ai_provider="openai", openai_api_key="k1", gemini_api_key="k2", deepseek_api_key="")

P["openai"]["base_url"], P["gemini"]["base_url"], P["deepseek"]["base_url"] = base + "/down/v1", base + "/noeffort/v1", base + "/ok/v1"
r, who = sc.ai_chat_ex(cfg, msgs)
gem = [b for p, b in LOG if p.startswith("/noeffort")]
check(who.startswith("Gemini") and "noeffort" in r, "OpenAI down -> falls back to Gemini")
check(len(gem) == 2 and "reasoning_effort" in gem[0] and "reasoning_effort" not in gem[1], "unsupported option dropped and retried")

try:
    sc.ai_chat_ex(dict(cfg, ai_fallback=False), msgs)
    check(False, "fallback off -> error")
except Exception as e:
    check("OpenAI" in sc.openai_problem(e, "openai"), "fallback off -> spoken error names OpenAI")

P["openai"]["base_url"] = base + "/badkey/v1"
try:
    sc.ai_chat_ex(cfg, msgs)
    check(False, "bad key -> error")
except Exception as e:
    check("API key" in sc.openai_problem(e, "openai"), "bad key -> no fallback, says check the key")

r, who = sc.ai_chat_ex(dict(cfg, ai_provider="deepseek", deepseek_api_key="k3"), msgs)
check(who == "DeepSeek deepseek-chat" and "max_tokens" in LOG[-1][1], "DeepSeek selected, uses max_tokens")
P["openai"]["base_url"] = base + "/ok/v1"
sc.ai_chat_ex(cfg, msgs)
check("max_completion_tokens" in LOG[-1][1], "OpenAI uses max_completion_tokens")

P["openai"]["base_url"], P["gemini"]["base_url"] = base + "/down/v1", base + "/badkey/v1"
try:
    sc.ai_chat_ex(cfg, msgs)
    check(False, "fallback with a bad key -> error")
except Exception as e:
    check(sc.openai_problem(e, "openai").startswith("Gemini"), "error names the provider that failed last (Gemini)")
check(sc.ai_key(dict(sc.DEFAULT_CONFIG, ai_provider="gemini")) == "", "no Gemini key by default")
done()
