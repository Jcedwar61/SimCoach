"""The GitHub-side checker (tools/references/review_submission.py) against a local stand-in for GitHub: good laps
are written into the library and the pull request closed with a note; slower, broken or mismatched laps are
refused with the reason; pull requests that touch anything else are left alone. Laps from people the repository
doesn't trust wait for the owner's "library-approved" label, and only canonical lap data is ever written."""
import base64
import importlib.util
import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from _common import check, done, load

os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
sc = load()
REPO, FORK = "Jcedwar61/SimCoach", "speedy/SimCoach"
files = {}          # (repo, ref, path) -> bytes
prs = {}            # number -> {"files": [(path, status)], "state", "comments": []}


def lap(key, t, **extra):
    r = sc.starter_reference("Spa", "gt3")
    d = {"key": list(key), "ref": r["ref"], "best_time": t, "corners": [list(c) for c in r["corners"]],
         "best_corner": {str(k): v for k, v in r["best_corner"].items()}, "saved": "2026-11-12 10:00",
         "provisional": False, "source": "library"}
    d.update(extra)
    return sc.share_payload(d)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, code, obj=None, raw=None):
        body = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n)) if n else {}

    def do_GET(self):
        m = re.fullmatch(rf"/repos/{REPO}/pulls/(\d+)", self.path)
        if m:
            p = prs[int(m.group(1))]
            return self.reply(200, {"state": p["state"], "user": {"login": p.get("login", "speedy")},
                                    "author_association": p.get("assoc", "COLLABORATOR"), "base": {"ref": "main"},
                                    "head": {"sha": f"h{m.group(1)}", "repo": {"full_name": FORK}}})
        m = re.fullmatch(rf"/repos/{REPO}/pulls/(\d+)/files\?per_page=100", self.path)
        if m:
            return self.reply(200, [{"filename": f, "status": st} for f, st in prs[int(m.group(1))]["files"]])
        m = re.fullmatch(r"/repos/([^/]+/[^/]+)/contents/(.+)\?ref=(.+)", self.path)
        if m and (m.group(1), m.group(3), m.group(2)) in files:
            b = files[(m.group(1), m.group(3), m.group(2))]
            if "raw" in (self.headers.get("Accept") or ""):
                return self.reply(200, raw=b)
            return self.reply(200, {"sha": sc.git_blob_sha(b)})
        self.reply(404, {"message": "Not Found"})

    def do_PUT(self):
        b = self.body()
        m = re.fullmatch(rf"/repos/{REPO}/contents/(.+)", self.path)
        key = (REPO, b["branch"], m.group(1))
        if key in files and b.get("sha") != sc.git_blob_sha(files[key]):
            return self.reply(409, {"message": "sha"})
        files[key] = base64.b64decode(b["content"])
        self.reply(201, {})

    def do_POST(self):
        m = re.fullmatch(rf"/repos/{REPO}/issues/(\d+)/labels", self.path)
        if m:
            prs[int(m.group(1))].setdefault("labels", []).extend(self.body()["labels"])
            return self.reply(200, [])
        m = re.fullmatch(rf"/repos/{REPO}/issues/(\d+)/comments", self.path)
        prs[int(m.group(1))]["comments"].append(self.body()["body"])
        self.reply(201, {})

    def do_PATCH(self):
        m = re.fullmatch(rf"/repos/{REPO}/pulls/(\d+)", self.path)
        prs[int(m.group(1))]["state"] = self.body()["state"]
        self.reply(200, {})


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ.update(GITHUB_API_URL=f"http://127.0.0.1:{srv.server_port}", GITHUB_TOKEN="t", GITHUB_REPOSITORY=REPO)
here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("review", os.path.join(here, "..", "references", "review_submission.py"))
rv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rv)

A = ("ACC", "spa", "porsche_992_gt3_r")
B = ("LMU", "spa", "hypercar")
nA, nB = sc.library_file_name(A), sc.library_file_name(B)


def submit(n, entries, other=None, assoc="COLLABORATOR", approved_sha=None, login="speedy"):
    prs[n] = {"files": [(f"references/{name}", st) for name, st, _ in entries] + (other or []),
              "state": "open", "comments": [], "assoc": assoc, "login": login}
    for name, _st, data in entries:
        files[(FORK, f"h{n}", f"references/{name}")] = data
    return rv.review(n, approved_sha=approved_sha)


r = submit(1, [(nA, "added", lap(A, 138.2))])
check(r == "added" and files[(REPO, "main", f"references/{nA}")] == lap(A, 138.2), "new lap written into the library")
check(prs[1]["state"] == "closed" and "Added to the SimCoach library" in prs[1]["comments"][0], "PR closed with a thank-you")

r = submit(2, [(nA, "modified", lap(A, 137.4))])
check(r == "added" and json.loads(files[(REPO, "main", f"references/{nA}")])["best_time"] == 137.4, "faster lap replaces it")

r = submit(3, [(nA, "modified", lap(A, 137.9))])
check(r == "refused" and json.loads(files[(REPO, "main", f"references/{nA}")])["best_time"] == 137.4, "slower lap refused")
check("faster or equal" in prs[3]["comments"][0] and prs[3]["state"] == "closed", "with the reason")

r = submit(4, [(nB, "added", lap(A, 130.0))])
check(r == "refused" and (REPO, "main", f"references/{nB}") not in files, "file named for another combination refused")

bad = json.loads(lap(B, 140.0))
bad["best_time"] = 60.0                                  # lap time that doesn't fit its own trace
r = submit(5, [(nB, "added", json.dumps(bad).encode())])
check(r == "refused" and "doesn't match the lap time" in prs[5]["comments"][0], "made-up lap time refused")

r = submit(6, [(nB, "added", b"not json")])
check(r == "refused", "broken file refused")

r = submit(7, [(nB, "added", lap(B, 140.0))], other=[("sim_coach.py", "modified")])
check(r == "skipped" and prs[7]["state"] == "open" and not prs[7]["comments"], "PR touching other files left alone")

r = submit(8, [(nB, "added", lap(B, 140.0)), (sc.library_file_name(("x", "y", "z")), "removed", b"")])
check(r == "partly" and (REPO, "main", f"references/{nB}") in files and "only adding" in prs[8]["comments"][0],
      "mixed PR: good lap added, deletion refused")

# Someone the repository doesn't know: a good lap waits for the owner
C = ("AMS2", "interlagos", "gt3_gen2")
nC = sc.library_file_name(C)
r = submit(9, [(nC, "added", lap(C, 139.0))], assoc="NONE", login="stranger")
check(r == "waiting" and (REPO, "main", f"references/{nC}") not in files, "stranger's lap not written by itself")
check(prs[9]["state"] == "open" and "library-review" in prs[9].get("labels", [])
      and "library-approved" in prs[9]["comments"][0], "left open, labelled, with how to approve it")
r = submit(10, [(nC, "added", lap(C, 139.0))], assoc="NONE", login="stranger", approved_sha="old-commit")
check(r == "waiting", "an approval of an earlier commit doesn't count")
r = submit(11, [(nC, "added", lap(C, 139.0))], assoc="NONE", login="stranger", approved_sha="h11")
check(r == "added" and (REPO, "main", f"references/{nC}") in files, "owner's approval adds it")
os.environ["LIBRARY_TRUSTED"] = "Regular, other"
D = ("AMS2", "interlagos", "gt4")
r = submit(12, [(sc.library_file_name(D), "added", lap(D, 139.0))], assoc="NONE", login="regular")
check(r == "added", "logins in LIBRARY_TRUSTED are trusted")
os.environ.pop("LIBRARY_TRUSTED")

# Only lap data gets in: extra fields are dropped, missing values refused
E = ("AMS2", "interlagos", "f_ultimate")
nE = sc.library_file_name(E)
padded = json.loads(lap(E, 139.0))
padded["junk"] = "x" * 1000
padded["ref"]["junk"] = [1, 2, 3]
r = submit(13, [(nE, "added", json.dumps(padded).encode())])
stored = json.loads(files[(REPO, "main", f"references/{nE}")])
check(r == "added" and "junk" not in stored and "junk" not in stored["ref"], "extra fields stripped before writing")
holey = json.loads(lap(B, 141.0))
holey["ref"]["speed"][10] = float("nan")
r = submit(14, [(nB, "added", json.dumps(holey).encode())])
check(r == "refused" and "NaN" in prs[14]["comments"][0], "NaN in a lap trace refused")
done()
