"""Best laps and sharing them from the app, against a local stand-in for GitHub: the Best laps folder, the
fingerprint that tells whether the library has a lap, GitHub's code sign-in, and the two upload routes
(straight into the library with write access; a fork and pull request for everyone else)."""
import base64
import json
import os
import re
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from _common import check, done, load

os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
sc = load()


def lap(key, t=138.2, **extra):
    r = sc.starter_reference("Spa", "gt3")
    d = {"key": list(key), "ref": r["ref"], "best_time": t, "corners": [list(c) for c in r["corners"]],
         "best_corner": {str(k): v for k, v in r["best_corner"].items()}, "saved": "2026-11-12 10:00",
         "provisional": False, "source": "own"}
    d.update(extra)
    return d


# ---- payload and fingerprint ----
A = ("ACC", "spa", "porsche_992_gt3_r")
p1, p2 = sc.share_payload(lap(A)), sc.share_payload(lap(A))
check(p1 == p2 and json.loads(p1)["source"] == "library", "same lap -> same bytes, marked as a library lap")
tmpf = tempfile.mktemp()
open(tmpf, "wb").write(p1)
git = subprocess.run(["git", "hash-object", tmpf], capture_output=True, text=True).stdout.strip()
check(sc.git_blob_sha(p1) == git, "fingerprint = GitHub's file sha")

# ---- Best laps folder ----
refs, best = tempfile.mkdtemp(), tempfile.mkdtemp()
B = ("iRacing", "monza full", "bmw m4 gt3")
for key, d in ((A, lap(A)), (B, lap(B, source="library")), (("ACC", "imola", "x"), lap(("ACC", "imola", "x"), provisional=True))):
    json.dump(d, open(os.path.join(refs, sc.library_file_name(key)), "w"))
w = sc.save_best_laps(refs, best)
check(w == [sc.library_file_name(A)], f"only own clean laps saved ({w})")
check(sc.save_best_laps(refs, best) == [], "unchanged: nothing rewritten")
json.dump(lap(A, t=137.5), open(os.path.join(refs, sc.library_file_name(A)), "w"))
check(sc.save_best_laps(refs, best) == [sc.library_file_name(A)], "a new best lap is saved over the old one")
check(json.load(open(os.path.join(best, sc.library_file_name(A))))["best_time"] == 137.5, "with the new time")

# ---- stand-in GitHub ----
REPO, OWNER, FRIEND = "Jcedwar61/SimCoach", "Jcedwar61", "speedy"
files = {}             # (repo, branch, path) -> bytes
calls = []
polls = {"n": 0}


def blob(b):
    return sc.git_blob_sha(b)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n).decode() if n else ""
        if self.headers.get("Content-Type", "").startswith("application/x-www-form-urlencoded"):
            from urllib.parse import parse_qs
            return {k: v[0] for k, v in parse_qs(raw).items()}
        return json.loads(raw) if raw else {}

    def user(self):
        tok = (self.headers.get("Authorization") or "").replace("Bearer ", "")
        return {"tok-owner": OWNER, "tok-friend": FRIEND}.get(tok)

    def do_POST(self):
        b = self.body()
        calls.append(("POST", self.path))
        if self.path == "/login/device/code":
            return self.reply(200, {"device_code": "dc", "user_code": "ABCD-1234", "interval": 1, "expires_in": 60,
                                    "verification_uri": "https://github.com/login/device"})
        if self.path == "/login/oauth/access_token":
            polls["n"] += 1
            if b.get("client_id") == "deny":
                return self.reply(200, {"error": "access_denied"})
            return self.reply(200, {"error": "authorization_pending"} if polls["n"] < 3 else
                              {"access_token": "tok-friend", "token_type": "bearer"})
        if not self.user():
            return self.reply(401, {"message": "Bad credentials"})
        if self.path == f"/repos/{REPO}/forks":
            return self.reply(202, {"full_name": f"{FRIEND}/SimCoach"})
        m = re.match(r"/repos/([^/]+/[^/]+)/git/refs$", self.path)
        if m:
            branch = b["ref"].split("/", 2)[2]
            for (r, br, pth), v in list(files.items()):
                if r == REPO and br == "main":
                    files[(m.group(1), branch, pth)] = v
            return self.reply(201, {"ref": b["ref"]})
        if self.path == f"/repos/{REPO}/pulls":
            calls.append(("PR", b["head"], b["base"], b["title"]))
            return self.reply(201, {"html_url": f"https://github.com/{REPO}/pull/42"})
        self.reply(404, {"message": "Not Found"})

    def do_GET(self):
        calls.append(("GET", self.path))
        u = self.user()
        if not u:
            return self.reply(401, {"message": "Bad credentials"})
        if self.path == "/user":
            return self.reply(200, {"login": u})
        if self.path == f"/repos/{REPO}":
            return self.reply(200, {"default_branch": "main", "permissions": {"push": u == OWNER}})
        if self.path == f"/repos/{FRIEND}/SimCoach":
            return self.reply(200, {"full_name": f"{FRIEND}/SimCoach"})
        if self.path == f"/repos/{REPO}/git/ref/heads/main":
            return self.reply(200, {"object": {"sha": "abc123"}})
        m = re.match(r"/repos/([^/]+/[^/]+)/contents/(.+)\?ref=(.+)$", self.path)
        if m and (m.group(1), m.group(3), m.group(2)) in files:
            b = files[(m.group(1), m.group(3), m.group(2))]
            return self.reply(200, {"sha": blob(b), "content": base64.b64encode(b).decode()})
        self.reply(404, {"message": "Not Found"})

    def do_PUT(self):
        b = self.body()
        u = self.user()
        m = re.match(r"/repos/([^/]+/[^/]+)/contents/(.+)$", self.path)
        repo, path = m.group(1), m.group(2)
        calls.append(("PUT", repo, b["branch"], path, b.get("sha")))
        if repo == REPO and u != OWNER:
            return self.reply(403, {"message": "Resource not accessible"})
        key = (repo, b["branch"], path)
        if key in files and b.get("sha") != blob(files[key]):
            return self.reply(409, {"message": "sha mismatch"})
        files[key] = base64.b64decode(b["content"])
        self.reply(201, {"content": {"html_url": f"https://github.com/{repo}/blob/{b['branch']}/{path}"}})


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
sc.GITHUB_API = sc.GITHUB_WEB = f"http://127.0.0.1:{srv.server_port}"

# sign-in
start = sc.github_device_start("cid")
check(start["user_code"] == "ABCD-1234", "sign-in code from GitHub")
tok = sc.github_device_poll("cid", start, sleep=lambda s: None)
check(tok == "tok-friend" and polls["n"] == 3, "waits while the driver enters the code, then gets the token")
try:
    sc.github_device_poll("deny", start, sleep=lambda s: None)
    check(False, "cancelled sign-in raises")
except sc.GitHubError as e:
    check("cancelled" in str(e), "cancelled sign-in raises")

name = sc.library_file_name(A)
path = f"references/{name}"
data = open(os.path.join(best, name), "rb").read()

# owner: straight into the library
kind, url = sc.upload_library_lap("tok-owner", name, data, "Best lap", log=lambda m: None)
check(kind == "added" and files[(REPO, "main", path)] == data, "owner: committed straight to the library")
calls.clear()
kind, url = sc.upload_library_lap("tok-owner", name, data, "Best lap", log=lambda m: None)
check(kind == "added" and not any(c[0] == "PUT" for c in calls), "already in the library: nothing written")

# another driver with a faster lap: fork + pull request (updating the existing file)
json.dump(lap(A, t=136.9), open(os.path.join(refs, name), "w"))
sc.save_best_laps(refs, best)
data2 = open(os.path.join(best, name), "rb").read()
calls.clear()
kind, url = sc.upload_library_lap("tok-friend", name, data2, "Best lap: faster", log=lambda m: None)
puts = [c for c in calls if c[0] == "PUT"]
prs = [c for c in calls if c[0] == "PR"]
check(kind == "proposed" and url.endswith("/pull/42"), "other drivers: sent as a pull request")
check(puts and puts[0][1] == f"{FRIEND}/SimCoach" and puts[0][2].startswith("lap-") and puts[0][4] == sc.git_blob_sha(data),
      "file goes to the driver's fork on a new branch, replacing the library's version")
check(prs and prs[0][1].startswith(f"{FRIEND}:lap-") and prs[0][2] == "main", "pull request into the library")
check(files[(REPO, "main", path)] == data, "library unchanged until the owner approves")

# a slower lap isn't sent at all
json.dump(lap(A, t=137.6), open(os.path.join(refs, name), "w"))
sc.save_best_laps(refs, best)
calls.clear()
kind, why = sc.upload_library_lap("tok-friend", name, open(os.path.join(best, name), "rb").read(), "x", log=lambda m: None)
check(kind == "refused" and "faster" in why and not any(c[0] in ("PUT", "PR") for c in calls),
      f"slower than the library's lap: not sent ({why})")

# bad token
try:
    sc.upload_library_lap("nope", name, data2, "x", log=lambda m: None)
    check(False, "expired sign-in reported")
except sc.GitHubError as e:
    check(e.status == 401, "expired sign-in reported (401)")
done()
