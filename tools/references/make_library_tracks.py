"""Build starter-lap track files for the library (references/tracks/*.json) from circuit centre lines.

Source: bacinger/f1-circuits (https://github.com/bacinger/f1-circuits, MIT): GeoJSON centre lines that start near the
start/finish line (the app lines each one up with the sim on the first lap; lines drawn against the race direction
are turned round). They are coarse (a point every ~40 m), so each is smoothed with a spline and
a racing line is fitted inside a 10 m wide corridor (least curvature, bounded least squares); very tight corners
are limited to a 15 m radius. Checked against the built-in TUMFTM race lines on shared circuits, the simulated GT3
lap times agree within about 3 %.

    pip install numpy scipy
    git clone --depth 1 https://github.com/bacinger/f1-circuits.git /tmp/f1c
    python tools/references/make_library_tracks.py /tmp/f1c/f1-circuits.geojson [only_id ...]
"""
import json
import math
import os
import sys

import numpy as np
from scipy.interpolate import splev, splprep
from scipy.optimize import lsq_linear

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(REPO, "references", "tracks")
BINS = 2000
TRACKS = {   # dataset id: (file id, spoken name, phrases matched against the sim's track name, race direction)
    "mc-1929": ("Monaco", "Monaco", ["monaco", "monte carlo"], "cw"),
    "fr-1969": ("PaulRicard", "Paul Ricard", ["paul ricard", "ricard", "castellet"], "cw"),
    "sg-2008": ("Singapore", "Singapore", ["singapore", "marina bay"], "ccw"),
    "it-1953": ("Imola", "Imola", ["imola", "enzo e dino"], "ccw"),
    "pt-2008": ("Portimao", "Portimão", ["portimao", "algarve"], "cw"),
    "it-1914": ("Mugello", "Mugello", ["mugello"], "cw"),
    "tr-2005": ("Istanbul", "Istanbul Park", ["istanbul"], "ccw"),
    "fr-1960": ("MagnyCours", "Magny-Cours", ["magny cours", "nevers"], "cw"),
    "pt-1972": ("Estoril", "Estoril", ["estoril"], "cw"),
    "br-1977": ("Jacarepagua", "Jacarepaguá", ["jacarepagua"], "ccw"),
    "sa-2021": ("Jeddah", "Jeddah", ["jeddah", "saudi"], "ccw"),
    "us-2022": ("Miami", "Miami", ["miami"], "ccw"),
    "qa-2004": ("Lusail", "Lusail", ["lusail", "losail", "qatar"], "cw"),
    "es-2026": ("Madrid", "Madrid", ["madring", "madrid"], "cw"),
    "az-2016": ("Baku", "Baku", ["baku", "azerbaijan"], "ccw"),
    "us-2023": ("LasVegas", "Las Vegas", ["las vegas", "vegas"], "ccw"),
    "ar-1952": ("BuenosAires", "Buenos Aires", ["buenos aires", "galvez"], "cw"),
    "za-1961": ("Kyalami", "Kyalami", ["kyalami"], "cw"),
    "us-1956": ("WatkinsGlen", "Watkins Glen", ["watkins glen", "watkins"], "cw"),
}


OFFICIAL = {"Estoril": 4182.0}       # where the dataset's "length" is of an older layout than its drawing


def xy(feature):
    c = np.array(feature["geometry"]["coordinates"], float)[:, :2]
    lat0 = np.radians(c[:, 1].mean())
    return np.column_stack([np.radians(c[:, 0] - c[0, 0]) * 6371008.8 * math.cos(lat0),
                            np.radians(c[:, 1] - c[0, 1]) * 6371008.8])


def centre(p, smooth=5.0, ds=5.0):
    if np.allclose(p[0], p[-1]):
        p = p[:-1]
    keep = [0]
    for i in range(1, len(p)):
        if np.hypot(*(p[i] - p[keep[-1]])) > 1.0:
            keep.append(i)
    pc = np.vstack([p[keep], p[0]])
    tck, _ = splprep([pc[:, 0], pc[:, 1]], s=smooth * len(pc), per=True, k=3)
    uu = np.linspace(0, 1, 20001)[:-1]
    x, y = splev(uu, tck)
    seg = np.hypot(np.diff(np.r_[x, x[0]]), np.diff(np.r_[y, y[0]]))
    L = seg.sum()
    s = np.r_[0, np.cumsum(seg)][:-1]
    n = int(L / ds)
    u2 = np.interp(np.arange(n) * L / n, s, uu)
    x, y = splev(u2, tck)
    dx, dy = splev(u2, tck, der=1)
    nrm = np.hypot(dx, dy)
    return np.column_stack([x, y]), np.column_stack([-dy / nrm, dx / nrm]), L


def raceline(C, N, half=5.0):
    n = len(C)
    A, b = np.zeros((2 * n, n)), np.zeros(2 * n)
    i = np.arange(n)
    a, c = (i - 1) % n, (i + 1) % n
    for d in (0, 1):
        r = 2 * i + d
        A[r, a] += N[a, d]
        A[r, i] += -2 * N[i, d]
        A[r, c] += N[c, d]
        b[r] = -(C[a, d] - 2 * C[i, d] + C[c, d])
    return C + lsq_linear(A, b, bounds=(-half, half), lsq_solver="exact", max_iter=60).x[:, None] * N


def curvature(P, min_radius=15.0):
    a, c = np.roll(P, 1, 0), np.roll(P, -1, 0)
    d1, d2 = (c - a) / 2, c - 2 * P + a
    L = np.hypot(*(c - P).T).sum()
    k = (d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]) / np.maximum(1e-9, np.hypot(d1[:, 0], d1[:, 1]) ** 3)
    k = np.convolve(np.r_[k[-3:], k, k[:3]], np.ones(3) / 3, mode="same")[3:-3]
    return L, np.clip(k, -1 / min_radius, 1 / min_radius)


def build(feature, spec):
    tid, spoken, phrases, direction = spec
    p = xy(feature)
    area = 0.5 * np.sum(p[:-1, 0] * p[1:, 1] - p[1:, 0] * p[:-1, 1])
    if ("ccw" if area > 0 else "cw") != direction:
        p = p[::-1]                                  # drawn against the race direction: same start point, turned round
    C, N, Lc = centre(p)
    official = OFFICIAL.get(tid) or float(feature["properties"].get("length") or 0)
    if official and abs(Lc - official) / official > 0.02:
        raise ValueError(f"{tid}: {Lc:.0f} m, but the circuit is {official:.0f} m")
    L, k = curvature(raceline(C, N))
    n = len(k)
    kb = [float(np.mean(k[int(i * n / BINS):max(int(i * n / BINS) + 1, int((i + 1) * n / BINS))])) for i in range(BINS)]
    q = [int(round(x * 1e5)) for x in kb]
    # length: the circuit's official length (what sims report); the racing line itself is a little shorter
    return {"id": tid, "spoken": spoken, "phrases": phrases, "length": round(official or float(Lc), 1),
            "steps": [q[0]] + [y - x for x, y in zip(q, q[1:])],
            "source": "bacinger/f1-circuits (MIT) centre line, racing line fitted by tools/references/make_library_tracks.py"}


def main(path, only):
    feats = {f["properties"]["id"]: f for f in json.load(open(path, encoding="utf-8"))["features"]}
    os.makedirs(OUT, exist_ok=True)
    for fid, spec in TRACKS.items():
        if only and spec[0] not in only:
            continue
        try:
            d = build(feats[fid], spec)
        except Exception as e:
            print(f"SKIP {spec[0]}: {e}", flush=True)
            continue
        with open(os.path.join(OUT, d["id"] + ".json"), "w", encoding="utf-8") as fh:
            json.dump(d, fh, separators=(",", ":"), ensure_ascii=False)
        print(f"{d['id']:12s} {d['length']:7.1f} m", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], set(sys.argv[2:]))
