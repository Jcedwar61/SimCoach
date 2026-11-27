"""Runs on GitHub (.github/workflows/library-auto-add.yml) for every pull request that only adds or changes lap
files in references/: each lap is checked with SimCoach's own rules (library_submission_problem: a complete, clean,
believable lap, faster than the library's lap for that sim / track / car). Every lap goes out to every SimCoach,
so a lap is only written into the library when a person vouches for it:
* the submitter is the owner, a collaborator, or listed in the LIBRARY_TRUSTED repository variable
  (comma-separated GitHub logins), or
* the owner approves the pull request by adding the "library-approved" label (only people with triage or write
  access can add labels). The approval covers the commit the pull request had when the label was added.
Otherwise good laps wait: the pull request gets a "library-review" label and a note, and stays open. Laps are
written as SimCoach's own canonical JSON (share_payload), never as the submitted bytes, so nothing but lap data
gets in. The pull request is then closed with a note saying what was added and what wasn't, and why.

Pull requests that touch anything else are left alone for the owner. The submitted files are only read as data:
no code from the pull request is run.

Needs GITHUB_TOKEN (contents + pull requests write), GITHUB_REPOSITORY and GITHUB_EVENT_PATH, as Actions provides.
GITHUB_API_URL can point it at a stand-in server (tests)."""
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO_DIR, "tools", "tests"))
from _common import load  # noqa: E402

sc = load()
API = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = os.environ["GITHUB_REPOSITORY"]
LAP_PATH = re.compile(r"references/([A-Za-z0-9_.-]+\.json)")
LIMIT = 3_000_000
APPROVED, WAITING = "library-approved", "library-review"
TRUSTED_ROLES = ("OWNER", "MEMBER", "COLLABORATOR")


class HTTPFail(Exception):
    def __init__(self, code, msg):
        super().__init__(f"{code} {msg}")
        self.code = code


def call(method, path, body=None, raw=False):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {TOKEN}", "User-Agent": "SimCoach-library-check",
                                          "Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read(LIMIT + 1)
    except urllib.error.HTTPError as e:
        raise HTTPFail(e.code, e.reason) from None
    if raw:
        return data
    return json.loads(data.decode("utf-8")) if data.strip() else {}


def trusted(pr):
    who = ((pr.get("user") or {}).get("login") or "").lower()
    extra = {x.strip().lower() for x in os.environ.get("LIBRARY_TRUSTED", "").split(",") if x.strip()}
    return pr.get("author_association") in TRUSTED_ROLES or (who and who in extra)


def review(number, approved_sha=None):
    """approved_sha: the head commit the owner approved (the "library-approved" label was just added), or None."""
    pr = call("GET", f"/repos/{REPO}/pulls/{number}")
    if pr.get("state") != "open":
        print("closed already")
        return "skipped"
    files = call("GET", f"/repos/{REPO}/pulls/{number}/files?per_page=100")
    if not files or not all(LAP_PATH.fullmatch(f.get("filename", "")) for f in files):
        print("not a lap submission: left for the owner")
        return "skipped"
    head_repo = ((pr.get("head") or {}).get("repo") or {}).get("full_name")
    head_sha = (pr.get("head") or {}).get("sha")
    if approved_sha and approved_sha != head_sha:
        print("the pull request changed after it was approved: waiting for a new approval")
        approved_sha = None
    write = bool(approved_sha) or trusted(pr)
    waiting = []
    base = (pr.get("base") or {}).get("ref") or "main"
    who = (pr.get("user") or {}).get("login") or "a SimCoach driver"
    added, refused = [], []
    for f in files:
        path = f["filename"]
        name = LAP_PATH.fullmatch(path).group(1)
        try:
            if f.get("status") not in ("added", "modified"):
                raise ValueError("only adding or replacing laps is allowed")
            if not head_repo:
                raise ValueError("the submitted copy is gone")
            data = call("GET", f"/repos/{head_repo}/contents/{path}?ref={head_sha}", raw=True)
            if len(data) > LIMIT:
                raise ValueError("over 3 MB")
            d = json.loads(data.decode("utf-8"))
            try:
                cur_meta = call("GET", f"/repos/{REPO}/contents/{path}?ref={base}")
                current = json.loads(call("GET", f"/repos/{REPO}/contents/{path}?ref={base}", raw=True).decode("utf-8"))
            except HTTPFail as e:
                if e.code != 404:
                    raise
                cur_meta, current = {}, None
            prob = sc.library_submission_problem(d, name, current)
            if prob:
                raise ValueError(prob)
            k = d["key"]
            when = sc.fmt_time(d['best_time']).replace(' ', ':')
            if not write:
                waiting.append(f"{k[0]} · {k[1]} · {k[2]} ({when})")
                continue
            data = sc.share_payload(d)              # canonical lap data only, never the submitted bytes
            put = {"message": f"Library lap: {k[0]} / {k[1]} / {k[2]} {sc.fmt_time(d['best_time']).replace(' ', ':')} (from {who}, #{number})",
                   "content": base64.b64encode(data).decode("ascii"), "branch": base}
            if cur_meta.get("sha"):
                put["sha"] = cur_meta["sha"]
            for attempt in range(4):                 # another lap landing at the same moment: try again
                try:
                    call("PUT", f"/repos/{REPO}/contents/{path}", put)
                    break
                except HTTPFail as e:
                    if e.code != 409 or attempt == 3:
                        raise
                    time.sleep(3)
            added.append(f"{k[0]} · {k[1]} · {k[2]} ({sc.fmt_time(d['best_time']).replace(' ', ':')})")
        except Exception as e:
            refused.append(f"{name}: {e}")
    lines = []
    if waiting:
        lines.append("These laps passed SimCoach's checks and are waiting for the owner to approve them (add the "
                     f"`{APPROVED}` label):")
        lines += [f"- {w}" for w in waiting]
    if added:
        lines.append("Added to the SimCoach library, thanks! Every SimCoach picks it up at its next library check:")
        lines += [f"- {a}" for a in added]
    if refused:
        lines.append("Not added:")
        lines += [f"- {r}" for r in refused]
    call("POST", f"/repos/{REPO}/issues/{number}/comments", {"body": "\n".join(lines)})
    print("\n".join(lines))
    if waiting:
        call("POST", f"/repos/{REPO}/issues/{number}/labels", {"labels": [WAITING]})
        return "waiting"
    call("PATCH", f"/repos/{REPO}/pulls/{number}", {"state": "closed"})
    return "added" if added and not refused else "partly" if added else "refused"


if __name__ == "__main__":
    event = json.load(open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8"))
    pr = event["pull_request"]
    approved = (event.get("action") == "labeled" and (event.get("label") or {}).get("name") == APPROVED)
    review(pr["number"], approved_sha=(pr.get("head") or {}).get("sha") if approved else None)
