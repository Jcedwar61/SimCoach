# Starter-lap tracks

Track shapes SimCoach downloads automatically (at start-up and every 12 hours) to coach from lap one at circuits
that aren't built into the app. When a driver has no lap of their own at one of these tracks, SimCoach calculates
an approximate *starter lap* for their car's class from the shape, lines it up with the sim during the first
lap, and calls braking points. The driver's first clean lap replaces it.

These are calculated laps, not driven ones: braking points are approximate and there is no live delta against
them. Real laps shared by drivers (the files one folder up) always take priority.

Each file: `id`, `spoken` (how the coach says the name), `phrases` (matched against the sim's track name; the
lap length must also be within 3 %), `length` in metres, and `steps` (the racing line's curvature at 2000 points
around the lap, as differences in 1e-5 / m).

Built with `tools/references/make_library_tracks.py` from
[bacinger/f1-circuits](https://github.com/bacinger/f1-circuits) (MIT), and with
`tools/references/make_osm_tracks.py` from OpenStreetMap raceway outlines (© OpenStreetMap contributors, ODbL:
Donington, Fuji, Indianapolis GP and road course, Jerez, Laguna Seca, Misano, Road America, Road Atlanta, The
Bend, Valencia, Zolder). Every OpenStreetMap track was checked against real GT3 (or class) lap times: the
calculated lap was within 4 % of them before tuning. Checked by `tools/references/check_library.py`.
