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
| test_simcast_link / test_kokoro_share | SimCast link packets (frozen v1 bytes); Kokoro model reused from SimCast's folder |
| test_session_repeat / test_lap_talk | once-a-day briefing, skip / full briefing; short debriefs, fair coaching |
| reference library files | every lap in `references/` is valid (`tools/references/check_library.py`) |
| net_test_update_check | update check, installer download (`--network`) |
| gui_test_app | Settings, welcome box, setup sheet confirm, overlay SETUP button, phone page, update banner (`--gui`) |

## Releasing a new version

1. Make the changes and run `tools/run_tests.sh --gui --network`.
2. `python tools/installer/set_version.py 6.4` sets the version in sim_coach.py and the README download link.
   Add a "What's new" section to README.md.
3. `tools/installer/build_installer.sh` rebuilds the `SimCoach-Setup.exe` wizard with NSIS (`apt install nsis
   p7zip-full`; works from Linux), taking the version from sim_coach.py, and checks every file inside matches
   the repo. `tools/installer/wine_check.sh` runs it under Wine and screenshots every page (`apt install wine
   wine32:i386 xvfb xdotool imagemagick`).
4. Merge to main, then publish: **Actions > Release > Run workflow** (`.github/workflows/release.yml`). It tags
   `v6.4` on main, builds the release zip (`tools/release/make_zip.sh`, which also checks the installer carries
   main's sim_coach.py) and publishes the GitHub release with **SimCoach-Setup.exe** and the zip attached, using
   README.md's "What's new in 6.4" section as the notes. It refuses a version that's already released.
5. By hand instead: `tools/release/make_zip.sh` writes `dist/SimCoach-v6.4-release.zip` from origin/main; tag
   `v6.4` on main and attach **SimCoach-Setup.exe** (exactly this name: installed copies' update check and SimCast's
   setup wizard look for it) and the zip.
   Pre-filled: `https://github.com/Jcedwar61/SimCoach/releases/new?tag=v6.4&target=main&title=SimCoach%20v6.4`

## Installer helpers

- `installer-source/simcoach.nsi` is the wizard; `installer-source/install.ps1` the setup steps it runs.
- The wizard's optional *SimCast* component (step `simcast` in install.ps1) downloads SimCast's latest
  `SimCast-Setup.exe`, checks it against the SHA-256 digest GitHub publishes for the release asset and runs it
  with `/S`. SimCast's wizard does the same for SimCoach, so keep the asset name `SimCoach-Setup.exe`.
- `docs/simcast-link.md` is the SimCoach → SimCast ducking protocol; read it before changing `SimCastLink`.
- `7z l SimCoach-Setup.exe` lists the files inside an installer (`7z x` extracts them).
- `installer/set_exe_icon.py SimCoach.exe SimCoach.ico` puts a new icon into the launcher (pip install pefile).
  The icon's source is `installer-source/art/icon-512.png`; make SimCoach.ico from it (16-256 px) first.
- `release/export_csp_app.py sim_coach.py OUT` writes the Assetto Corsa helper app (it goes in the release zip).

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
