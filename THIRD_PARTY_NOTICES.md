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

## RaceRoom car names

The RaceRoom car list (`RACEROOM_CARS_B64` in `sim_coach.py`: model id, car name, class name) is taken from
`r3e-data.json` in **sector3studios/r3e-spectator-overlay** — https://github.com/sector3studios/r3e-spectator-overlay —
by Sector3 Studios / KW Studios, the makers of RaceRoom Racing Experience. Only the ids and names are used.
`tools/references/make_raceroom_cars.py` rebuilds the list from that file.

## Starter-lap tracks in the library

Twelve starter-lap tracks in the library (`references/tracks/`: Donington, Fuji, IndianapolisGP, IndianapolisRoad,
Jerez, LagunaSeca, Misano, RoadAmerica, RoadAtlanta, TheBend, Valencia, Zolder) are derived from **OpenStreetMap**
data, © OpenStreetMap contributors, available under the **Open Database License (ODbL 1.0)**
(https://www.openstreetmap.org/copyright, https://opendatacommons.org/licenses/odbl/1-0/). Those files are a
derived database and are themselves available under the ODbL. Changes: each circuit's raceway outline was taken in
race direction, smoothed, a racing line fitted inside a 10 m corridor, and its curvature stored at 2000 points per
lap (`tools/references/make_osm_tracks.py`).

The starter-lap tracks in the library (`references/tracks/*.json`, downloaded by the app) are derived from
**bacinger/f1-circuits** — https://github.com/bacinger/f1-circuits — Copyright (c) 2019-2025 Tomislav Bacinger,
**MIT License**:

> Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
> documentation files (the "Software"), to deal in the Software without restriction, including without limitation
> the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and
> to permit persons to whom the Software is furnished to do so, subject to the following conditions: The above
> copyright notice and this permission notice shall be included in all copies or substantial portions of the
> Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.

Changes made by SimCoach (`tools/references/make_library_tracks.py`): each centre line is smoothed, a racing line
is fitted inside a 10 m corridor, and its curvature is stored at 2000 points per lap.
