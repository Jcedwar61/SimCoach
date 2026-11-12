# Benchmark lap times

`laps.json` holds quick, repeatable lap times by sim and car class: setup-shop reference laps, leaderboard and
league times collected in November 2026 (each row names its source). They are lap *times* only, with no
telemetry, so they can't be reference laps by themselves. SimCoach uses them two ways:

* **Target time.** At the start of a session the coach quotes the time for the driver's sim and class, or for
  the exact car when a row has car phrases.
* **Tuning starter laps.** Where SimCoach has a starter lap for the track, the calculated lap is tuned so its lap
  time matches the benchmark for that sim and class. That moves corner speeds and braking points toward a real
  quick lap. A benchmark too far from the calculation (another layout, an unusual car) is quoted but not tuned to.

Format: `laps` rows are `[sim, class, track id, seconds, car phrases or null, source]`. `sim` is SimCoach's name
for the sim (`ACC`, `iRacing`, `LMU`, `AMS2`, `rFactor 2`, `AC`, `AC EVO`, `F1 25`) or `*` when it wasn't
recorded; a sim's own row wins over `*`. Track ids are starter-lap tracks (built in or in `../tracks/`) or one of
the `tracks` in this file, which are matched by name and length.

Edit the table in `tools/references/make_benchmarks.py` and run it; SimCoach downloads the file with its library
check, so every driver gets the change without an app update.
