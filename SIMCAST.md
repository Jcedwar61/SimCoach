<p align="center"><img src="simcast/assets/icon-256.png" width="160" alt="SimCast"></p>

# SimCast: live TV commentary for your sim race (Windows 10/11)

SimCast gives your sim race the television treatment. While you drive, a commentary booth calls the race live
in your headphones: the start, overtakes anywhere in the field, battles, pit stops, fastest laps, cars in
trouble, the final lap and the finish. It covers **the whole race**, not just you, and follows your race the
way a broadcast follows a driver in the story. Rally stages get rally coverage, against the clock.

SimCast is a standalone Windows app. It's built on SimCoach's foundation, but **doesn't need SimCoach
installed** (the two can run side by side).

### Download
* **[SimCast-Setup.exe](SimCast-Setup.exe)**: a standard setup wizard. No admin rights needed. It installs
  SimCast for your Windows account, then gets Python and SimCast's packages (a few minutes, once). Start menu
  and desktop shortcuts; uninstall from *Settings → Apps* (your settings are kept).
* **Linux / Steam Deck:** [install-simcast-wine.sh](install-simcast-wine.sh) installs SimCast into the sim's
  own Proton prefix (see below).

### The booth
* **Ben, the lead commentator**, calls the action: *"And Okafor takes the lead! Past Moretti, and into first place!"*
* **Kate, the analyst**, explains it: *"That's been coming. Okafor has looked the quicker of the two."*
* **Mia, the pit-lane reporter**, brings you every stop: *"Moretti is back out, in fifth, thirty-one seconds in the pit lane."*

Names and voices are yours to change. Each speaks in their own voice and gets faster, higher and louder as the
moment gets bigger; when something big happens, the lead cuts in, the way it does on TV.

### Every sim SimCoach supports
| Sim | Coverage |
| --- | --- |
| Le Mans Ultimate, rFactor 2, iRacing, Automobilista 2, RaceRoom | the whole field |
| F1 25 | the whole field, plus the game's own collisions, penalties and safety car |
| ACC | the whole field, through ACC's broadcasting API (SimCast switches it on), plus ACC's accident events |
| Assetto Corsa | the whole field with the CrewChiefEx app, else your car |
| AC EVO | your car (it doesn't share the others) |
| EA SPORTS WRC, DiRT Rally 2.0, AC Rally | rally stages: splits against your best run on that stage, moments, damage, the stage time and new bests |

SimCast **finds the sims installed on your PC** (every Steam library, iRacing, EA app installs) and lists them on
its start screen, each marked ready or with the one thing still to do. It picks the coverage by itself. *Your car only* means TV-style coverage of your session: places gained
and lost, the gap to the car ahead closing, pressure from behind, trips off the track, your laps and the finish.
For the sims you have installed, SimCast switches on what they need (EA WRC, DiRT Rally 2.0 and F1 25 telemetry,
ACC's broadcasting port, Assetto Corsa's CrewChiefEx app), backing up what it changes. The one setting it can't
make (Automobilista 2's shared memory) is in the built-in guide.

### Voices (free, like SimCoach's)
* **Microsoft neural voices**: natural and quick; the default.
* **Kokoro**: high-quality neural voices that run on your PC, offline after a one-time download.
* **Google** voices.
* **OpenAI** voices (with your OpenAI key): the most lifelike; every line is spoken with its own direction.

Pick a voice for each commentator, and where it plays: **Settings → Voices → Play on** (headset, speakers,
VR headset). If a voice's service can't be reached, the line is spoken by Kokoro, then Google, then Windows'
own voice: the booth never goes silent.

### AI commentary (optional)
The booth calls every moment from its own lines, instantly. Add an **OpenAI, Google Gemini or DeepSeek** key
(Settings → AI) and the analyst reacts to big moments with real analysis, quiet spells become conversation
about the stories in the race, and there's a proper sign-off. **The model is picked automatically**: SimCast
asks the provider which models your key can use and takes the best one for live commentary; you can choose
another from the list. With more than one key, it moves to another provider if one is down. The AI only gets
the race data, and strict rules: no invented facts, drivers by name, no repeats.

### Built-in guide
The **Guide** button opens a guide to everything: getting started, setting up each sim, voices and sound, AI,
every setting, streaming, Linux and troubleshooting. It opens by itself the first time.

### Streaming
Tick **Captions window**: a small always-on-top window shows each line as it's spoken (drag it anywhere; capture
it in OBS). Add the *Play on* device to OBS to put the booth on stream.

### Linux and Steam Deck
Sims share their live data inside their own Wine prefix, so SimCast must run in the same prefix as the game:
```
./install-simcast-wine.sh --game lmu        # or --appid N for any Steam game, or --prefix DIR for plain Wine
./install-simcast-wine.sh --list            # the known sims
```
It finds the game's Proton prefix and Proton build, installs SimCast there silently, and makes
`~/.local/bin/simcast-<game>.sh` plus a menu entry. Start the game, then SimCast. The installer needs no
PowerShell (SimCast.exe gets uv, Python and the packages itself). The script opens the same setup wizard as on
Windows (`--silent` skips it). Under Wine the Kokoro voices are off (NumPy can crash some Wine versions;
`SIMCAST_WINE_KOKORO=1` switches them on); the Microsoft, Google and OpenAI voices work.

## For developers
```
sim_cast.py                  entry point (--demo, --console, --test, --no-voice, --setup)
simcast/sims.py              the sim readers (adapted from SimCoach) with the whole field (Frame.field)
simcast/acc_broadcast.py     ACC's broadcasting API client
simcast/race.py              the race model: timing loops, gaps, overtakes, battles, pit stops, incidents
simcast/solo.py              one-car coverage and rally stages (best runs in %APPDATA%\SimCast\stages.json)
simcast/director.py          what goes on air, when, and what gets cut off
simcast/writer.py            the instant lines, in three voices
simcast/ai.py, providers.py  the AI booth; OpenAI / Gemini / DeepSeek with automatic model choice
simcast/audio.py             voices (Microsoft, Kokoro, Google, OpenAI), fallback, playback, interruptions
simcast/detect.py            the supported sims installed on this PC (Steam libraries, iRacing, EA app)
simcast/gamesetup.py         EA WRC, DiRT Rally 2.0, F1 25, ACC and Assetto Corsa set up for SimCast
simcast/gui.py, guide.py     the window, settings, captions window, the guide
simcast/demo.py              a fictional 12-car race for the demo and the tests
simcast/licenses/            SimCast's MIT licence and third-party notices
tools/launcher/              SimCast.exe (Go): build_launcher.sh
installer-source/simcast/    SimCast-Setup.exe (NSIS, 64-bit): tools/installer/build_simcast_installer.sh
```
Tests: `tools/run_tests.sh` (add `--gui` for the real window under Xvfb);
`tools/installer/wine_check_simcast.sh` installs, runs and uninstalls SimCast under Wine.
