# SimCoach developer tools

Everything needed to test SimCoach and build a release, so each release starts from the same steps.

## Tests

```
tools/run_tests.sh               # offline tests, about 3 minutes
tools/run_tests.sh --gui         # + the real app window (Linux: python3-tk and xvfb-run)
tools/run_tests.sh --network     # + the update check against GitHub's real releases
PYTHON=/path/to/python tools/run_tests.sh --gui --network
```

Tests use a throwaway settings folder, so they never touch your real `%APPDATA%\SimCoach` or reports.
Needs `numpy`, `openai` and `pyflakes` (and `tkinter` for `--gui`).

| Test | Checks |
|---|---|
| offline coaching run | `sim_coach.py --test`: simulated race laps through the coach, crew, report |
| test_ai_providers | OpenAI / Gemini / DeepSeek routing, fallback, error messages (local stand-in server) |
| test_personalities | personality voice commands; no real coaches' names; first-run defaults |
| test_voice_priority | urgent calls cut banter; spotter and push-to-talk behave as before |
| test_setup_sheet | before -> after previews; "apply the setup" reply |
| test_drills | practice drill over simulated laps, report table |
| test_race_start | grid reminder and start review for clean / wheelspin / bog / lift; silent for rolling starts and practice |
| test_session_briefing | setup sheet pops up and the briefing is heard at the start of every session type |
| test_iracing | iRacing reader against a synthetic SDK memory image |
| test_starter_laps | starter laps: track matching, car classes, lap times, line-up, replacement, mismatch drop |
| test_reference_library | shared library downloads (local stand-in for GitHub) and the coach flow |
| test_library_review | GitHub-side checker that adds shared laps (faster / slower / broken / mismatched / non-lap PRs) |
| test_share_laps | Best laps folder, library fingerprint, GitHub code sign-in, owner commit vs fork + pull request (local stand-in) |
| test_ac_setup_live | Assetto Corsa setup sheet: runs the in-game helper's real Lua code (needs `pip install lupa`) against a stand-in for CSP: apply, revert, pits rule, missing settings, radio command |
| test_pace_consistency | pace against the target, consistency score, advice, voice commands, session history, report |
| test_raceroom | RaceRoom car names and classes, target times there, moving references saved under "car <id>" |
| test_benchmarks | benchmark lap times by sim / class / car: selection, starter-lap tuning, target announcements, library file |
| test_library_tracks | starter-lap track shapes from the library: checks, download, use, removal |
| test_library_sync | automatic library import: new / changed / unchanged / bad files, own laps kept, live adoption |
| test_session_repeat / test_lap_talk | once-a-day briefing, skip / full briefing; short debriefs, fair coaching |
| reference library files | every lap in `references/` is valid (`tools/references/check_library.py`) |
| net_test_update_check | update check, installer download (`--network`) |
| gui_test_app | Settings, welcome box, setup sheet confirm, overlay SETUP button, phone page, update banner (`--gui`) |

## Releasing a new version

1. Make the changes and run `tools/run_tests.sh --gui --network`.
2. `python tools/installer/set_version.py 6.4` sets the version in sim_coach.py, the installer's Apps entry,
   the installer's Windows version info and the README download link. Add a "What's new" section to README.md.
3. `tools/installer/build_installer.sh` rebuilds `SimCoach-Setup.exe` (Go 1.22+, works from Linux too) and
   checks every bundled file matches the repo.
4. Merge to main, then `tools/release/make_zip.sh` writes `dist/SimCoach-v6.4-release.zip` from origin/main.
5. Publish the GitHub release: tag `v6.4` on main, attach **SimCoach-Setup.exe** (exactly this name: installed
   copies' update check looks for it) and the zip.
   Pre-filled: `https://github.com/Jcedwar61/SimCoach/releases/new?tag=v6.4&target=main&title=SimCoach%20v6.4`

## Installer helpers

- `installer/extract_payload.py SimCoach-Setup.exe [OUT]` lists (or extracts) the files bundled in an installer.
- `installer/make_syso.py SRC.exe OUT.syso VERSION` writes the icon / manifest / version resources.
- `installer/pe_resources.py` reads resources out of a .exe (used by make_syso).

## Reference data

- `references/make_raceroom_cars.py R3E_DATA.json` rebuilds the RaceRoom car list built into sim_coach.py
  (run it when RaceRoom adds cars)
- `references/make_benchmarks.py` writes the benchmark lap times (`references/benchmarks/laps.json` and the copy
  built into sim_coach.py); add new times to its table and run it
- `references/make_osm_tracks.py LOOPS.json` builds library track files from OpenStreetMap raceway outlines
  (circuit loops in race direction; see the script)
- `references/make_library_tracks.py F1_CIRCUITS.geojson` builds the library's starter-lap track files
  (`references/tracks/`, needs numpy + scipy) from bacinger/f1-circuits
- `references/make_starter_laps.py RACELINES_DIR` rebuilds the starter-lap track data embedded in sim_coach.py
  from the TUMFTM racetrack-database (`git clone --depth 1 https://github.com/TUMFTM/racetrack-database.git`).
- `references/check_library.py` checks the shared library in `references/` (see `references/README.md`).
