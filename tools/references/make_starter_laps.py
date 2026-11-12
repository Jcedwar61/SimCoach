"""Build the starter-lap track data embedded in sim_coach.py (STARTER_TRACKS_B64).

Source: TUMFTM racetrack-database (https://github.com/TUMFTM/racetrack-database), LGPL-3.0: race lines of real
circuits computed from OpenStreetMap centre lines (c) OpenStreetMap contributors. Each race line starts at the
start/finish line in race direction. For every track this stores the lap length and the race line's curvature
in 2000 steps around the lap (as differences, 1e-5 / m); sim_coach.py turns that into speed / brake / throttle for the car's class.

    git clone --depth 1 https://github.com/TUMFTM/racetrack-database.git /tmp/tum
    python tools/references/make_starter_laps.py /tmp/tum/racelines        # rewrites the block in sim_coach.py
"""
import base64
import json
import math
import os
import re
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
BINS = 2000
SKIP = {"IMS"}                      # oval / road-course layouts can't be told apart by name and length


def load_line(path, ds=2.0):
    pts = []
    for line in open(path, encoding="utf-8"):
        if line.strip() and not line.startswith("#"):
            x, y = map(float, line.split(",")[:2])
            pts.append((x, y))
    pts.append(pts[0])
    s = [0.0]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        s.append(s[-1] + math.hypot(x1 - x0, y1 - y0))
    L = s[-1]
    n = int(L / ds)
    out, j = [], 0
    for i in range(n):
        d = i * L / n
        while s[j + 1] < d:
            j += 1
        f = (d - s[j]) / max(1e-9, s[j + 1] - s[j])
        out.append((pts[j][0] + f * (pts[j + 1][0] - pts[j][0]), pts[j][1] + f * (pts[j + 1][1] - pts[j][1])))
    return out, L


def curvature(pts, ds, smooth_m=12.0):
    n = len(pts)
    k = []
    for i in range(n):
        (xa, ya), (xb, yb), (xc, yc) = pts[i - 1], pts[i], pts[(i + 1) % n]
        dx, dy = (xc - xa) / (2 * ds), (yc - ya) / (2 * ds)
        ddx, ddy = (xc - 2 * xb + xa) / ds ** 2, (yc - 2 * yb + ya) / ds ** 2
        k.append((dx * ddy - dy * ddx) / max(1e-9, (dx * dx + dy * dy) ** 1.5))
    w = max(1, int(smooth_m / ds))
    return [sum(k[(i + j) % n] for j in range(-(w // 2), w - w // 2)) / w for i in range(n)]


def track_data(path):
    pts, L = load_line(path)
    k = curvature(pts, L / len(pts))
    n = len(k)
    kb = []
    for i in range(BINS):
        a, b = int(i * n / BINS), max(int(i * n / BINS) + 1, int((i + 1) * n / BINS))
        kb.append(sum(k[a:b]) / (b - a))
    q = [int(round(x * 1e5)) for x in kb]          # curvature in 1e-5 / m (radius to well under a metre)
    return round(L, 1), [q[0]] + [b - a for a, b in zip(q, q[1:])]   # stored as steps: compresses far better


def main(folder):
    data = {}
    for f in sorted(os.listdir(folder)):
        name = f[:-4]
        if f.endswith(".csv") and name not in SKIP:
            data[name] = track_data(os.path.join(folder, f))
            print(f"{name:14s} {data[name][0]:7.1f} m")
    blob = base64.b64encode(zlib.compress(json.dumps(data, separators=(",", ":")).encode(), 9)).decode()
    lines = [blob[i:i + 116] for i in range(0, len(blob), 116)]
    block = "STARTER_TRACKS_B64 = (\n" + "\n".join(f'    "{ln}"' for ln in lines) + "\n)\n"
    p = os.path.join(REPO, "sim_coach.py")
    s = open(p, encoding="utf-8", newline="").read()
    new, n = re.subn(r"STARTER_TRACKS_B64 = \(\n.*?\n\)\n", lambda m: block, s, count=1, flags=re.S)
    if n != 1:
        sys.exit("STARTER_TRACKS_B64 block not found in sim_coach.py")
    open(p, "w", encoding="utf-8", newline="").write(new)
    print(f"{len(data)} tracks, {len(blob)} characters embedded in sim_coach.py")


if __name__ == "__main__":
    main(sys.argv[1])
