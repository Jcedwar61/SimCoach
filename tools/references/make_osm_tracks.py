"""Build starter-lap track files for the library (references/tracks/*.json) from OpenStreetMap circuit outlines.

Input: a JSON file {track id: {"len": metres, "lonlat": [[lon, lat], ...]}} with each circuit's racing loop in race
direction, starting near the middle of the pit straight. Those loops were taken from OpenStreetMap's raceway ways
(highway=raceway, in race direction from their one-way tags; pit lanes excluded; the loop whose length matches the
circuit). The shape is smoothed and a racing line fitted exactly as in make_library_tracks.py.

Track names, name phrases and lengths come from references/benchmarks/laps.json. Data (c) OpenStreetMap
contributors, available under the Open Database License (ODbL 1.0); see THIRD_PARTY_NOTICES.md.

    pip install numpy scipy
    python tools/references/make_osm_tracks.py loops.json [only_id ...]
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_library_tracks as M  # noqa: E402

REPO = os.path.dirname(os.path.dirname(HERE))
BINS = 2000


def xy(lonlat):
    c = np.array(lonlat, float)
    lat0 = np.radians(c[:, 1].mean())
    return np.column_stack([np.radians(c[:, 0] - c[0, 0]) * 6371008.8 * math.cos(lat0),
                            np.radians(c[:, 1] - c[0, 1]) * 6371008.8])


def build(tid, loop, info):
    p = xy(loop["lonlat"])
    p = np.vstack([p, p[:1]])
    C, N, Lc = M.centre(p)
    official = float(info["length"])
    if abs(Lc - official) / official > 0.03:
        raise ValueError(f"{tid}: outline {Lc:.0f} m, but the circuit is {official:.0f} m")
    L, k = M.curvature(M.raceline(C, N))
    n = len(k)
    kb = [float(np.mean(k[int(i * n / BINS):max(int(i * n / BINS) + 1, int((i + 1) * n / BINS))])) for i in range(BINS)]
    q = [int(round(x * 1e5)) for x in kb]
    return {"id": tid, "spoken": info["spoken"], "phrases": info["phrases"], "length": round(official, 1),
            "steps": [q[0]] + [y - x for x, y in zip(q, q[1:])],
            "source": "OpenStreetMap raceway outline (ODbL, (c) OpenStreetMap contributors), racing line fitted by "
                      "tools/references/make_osm_tracks.py"}


def main(path, only):
    loops = json.load(open(path, encoding="utf-8"))
    bench = json.load(open(os.path.join(REPO, "references", "benchmarks", "laps.json"), encoding="utf-8"))["tracks"]
    os.makedirs(M.OUT, exist_ok=True)
    for tid, loop in sorted(loops.items()):
        if only and tid not in only:
            continue
        if tid not in bench:
            print(f"SKIP {tid}: no name / length in benchmarks/laps.json", flush=True)
            continue
        try:
            d = build(tid, loop, bench[tid])
        except Exception as e:
            print(f"SKIP {tid}: {e}", flush=True)
            continue
        with open(os.path.join(M.OUT, tid + ".json"), "w", encoding="utf-8") as fh:
            json.dump(d, fh, separators=(",", ":"), ensure_ascii=False)
        print(f"{tid:18s} {d['length']:7.1f} m", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], set(sys.argv[2:]))
