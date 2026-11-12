# Third-party notices

## Starter-lap track data

SimCoach's starter laps (`STARTER_TRACKS_B64` in `sim_coach.py`) are derived from the
**TUMFTM racetrack-database** — https://github.com/TUMFTM/racetrack-database —
Copyright (c) Institute of Automotive Technology, Technical University of Munich, licensed under the
**GNU Lesser General Public License v3.0** (`licenses/LGPL-3.0.txt`, which builds on `licenses/GPL-3.0.txt`).

The race lines in that database were computed from centre lines fetched from **OpenStreetMap**,
© OpenStreetMap contributors (https://www.openstreetmap.org/copyright).

Changes made by SimCoach: each race line's curvature is resampled to 2000 points per lap, rounded and stored as
compressed differences. The tool that does this, `tools/references/make_starter_laps.py`, rebuilds the embedded
block from the original files, so the data can be inspected, modified and replaced.
