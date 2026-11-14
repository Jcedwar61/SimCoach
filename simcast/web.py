"""SimCast's control page and stream overlay, served on this PC (http://127.0.0.1:8766/).

/            the control page: timing tower, what the booth is saying, settings, the demo race
/overlay     a transparent timing tower and caption for OBS or a second screen
/state.json  everything the pages show
/api/...     changes (POST, only from this PC, only with the page's token)

With 'lan' on, phones and tablets on the same network can open the pages too (read-only).
"""
from __future__ import annotations

import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
UI_DIR = os.path.join(HERE, "ui")
ASSET_DIR = os.path.join(HERE, "assets")
ASSET_TYPES = {".png": "image/png", ".jpg": "image/jpeg"}
MAX_BODY = 64 * 1024


class WebUI:
    def __init__(self, cast, log=print):
        self.cast, self.log = cast, log
        self.token = secrets.token_urlsafe(18)
        self.httpd = None
        self.port = None

    def url(self):
        return f"http://127.0.0.1:{self.port}/" if self.port else ""

    def handle_action(self, action, body):
        """POST /api/<action>. Returns (status, dict)."""
        cast = self.cast
        if action == "settings":
            cast.update_settings(body.get("settings") or {})
            return 200, {"ok": True}
        if action == "demo":
            if body.get("on", True):
                cast.start_demo(body.get("laps"))
            else:
                cast.stop_demo()
            return 200, {"ok": True}
        if action == "on_air":
            cast.director.on_air = bool(body.get("on", True))
            if not cast.director.on_air:
                cast.audio.interrupt(None)
            return 200, {"ok": True}
        if action == "skip":
            cast.audio.interrupt(None)
            return 200, {"ok": True}
        if action == "test_voice":
            who = body.get("who") if body.get("who") in ("lead", "analyst", "pit") else "lead"
            cfg = cast.config()
            text = {"lead": f"Hello, I'm {cfg.get('lead_name')}, and I'll be calling the action today!",
                    "analyst": f"And I'm {cfg.get('analyst_name')}. I'll be telling you what it all means.",
                    "pit": f"{cfg.get('pit_name')} here in the pit lane, I'll bring you every stop."}[who]
            if hasattr(cast.audio, "preview"):
                cast.audio.preview(who, text, 2)
            return 200, {"ok": True}
        return 404, {"error": "unknown action"}

    def start(self, port=8766, lan=False):
        ui = self
        page_cache = {}

        def page(name):
            if name not in page_cache:
                with open(os.path.join(UI_DIR, name), encoding="utf-8") as fh:
                    page_cache[name] = fh.read()
            return page_cache[name].replace("__TOKEN__", ui.token).encode("utf-8")

        class H(BaseHTTPRequestHandler):
            server_version = "SimCast"

            def log_message(self, *a):
                pass

            def _local(self):
                return self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1")

            def _send(self, code, body, ctype, cache=False):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "max-age=3600" if cache else "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)

            def _json(self, code, d):
                self._send(code, json.dumps(d, separators=(",", ":")).encode("utf-8"), "application/json")

            def do_GET(self):
                path = self.path.split("?", 1)[0]
                try:
                    if path in ("/", "/index.html"):
                        # Remote viewers get the page without the token, so they can't change anything.
                        body = page("index.html")
                        if not self._local():
                            body = body.replace(ui.token.encode(), b"")
                        self._send(200, body, "text/html; charset=utf-8")
                    elif path in ("/overlay", "/overlay.html"):
                        self._send(200, page("overlay.html"), "text/html; charset=utf-8")
                    elif path == "/state.json":
                        self._json(200, ui.cast.state())
                    elif path.startswith("/assets/"):
                        name = os.path.basename(path)
                        ext = os.path.splitext(name)[1].lower()
                        fp = os.path.join(ASSET_DIR, name)
                        if ext not in ASSET_TYPES or not os.path.isfile(fp):
                            self._send(404, b"not found", "text/plain")
                            return
                        with open(fp, "rb") as fh:
                            self._send(200, fh.read(), ASSET_TYPES[ext], cache=True)
                    else:
                        self._send(404, b"not found", "text/plain")
                except Exception as e:
                    ui.log(f"Web page error: {e}")
                    self._json(500, {"error": str(e)})

            def do_POST(self):
                path = self.path.split("?", 1)[0]
                if not path.startswith("/api/"):
                    self._json(404, {"error": "not found"})
                    return
                if not self._local() or self.headers.get("X-SimCast-Token") != ui.token:
                    self._json(403, {"error": "changes only from the SimCast page on this PC"})
                    return
                n = int(self.headers.get("Content-Length") or 0)
                if n > MAX_BODY:
                    self._json(413, {"error": "too big"})
                    return
                try:
                    body = json.loads(self.rfile.read(n) or b"{}") if n else {}
                    if not isinstance(body, dict):
                        raise ValueError("expected an object")
                    code, out = ui.handle_action(path[5:], body)
                    self._json(code, out)
                except Exception as e:
                    self._json(400, {"error": str(e)})

        host = "0.0.0.0" if lan else "127.0.0.1"
        for p in (port, port + 1, port + 2, 0):
            try:
                self.httpd = ThreadingHTTPServer((host, p), H)
                break
            except OSError as e:
                self.log(f"Port {p} busy ({e})")
        if self.httpd is None:
            return False
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True, name="web").start()
        return True

    def stop(self):
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
