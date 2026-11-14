SimCoach - live English voice coach for your sims
==================================================

Quick start & installation (Windows 10 / 11)
--------------------------------------------
  - With the installer: run SimCoach-Setup.exe.
    * Installs for your Windows account only (no admin rights needed) into %LOCALAPPDATA%\Programs\SimCoach,
      adds SimCoach (with its own icon) to the desktop and Start menu, and registers an Uninstall entry
      under Settings > Apps > Installed apps.
    * The setup window downloads uv (the Python runner, from github.com/astral-sh/uv), Python 3.12,
      SimCoach's packages, and offline speech recognition (about 1 GB, a few minutes) so the first launch
      opens straight away.
    * Because the installer isn't code-signed, Windows SmartScreen may show "Windows protected your PC":
      click "More info", then "Run anyway".
    * Updating: run a newer SimCoach-Setup.exe over the top (it closes any running SimCoach first and saves
      your session). Uninstalling keeps your reference laps and settings (%APPDATA%\SimCoach) and your
      reports (Documents\SimCoach Reports).
  - Without the installer: double-click SimCoach.bat in this folder (uses the same app and data folders).
  - Coaching starts automatically and waits for a sim (untick "Start coaching automatically" in Settings if
    you prefer pressing Start manually). The interface uses an always-dark theme with a dark title bar.


Supported sims (detected automatically)
---------------------------------------
  Assetto Corsa, Assetto Corsa Competizione (ACC), AC Rally, AC EVO*, Le Mans Ultimate (LMU),
  rFactor 2, Automobilista 2 (AMS2), RaceRoom, iRacing**, EA SPORTS WRC, F1 25, DiRT Rally 2.0
  (* AC EVO's telemetry layout is only partly documented by Kunos.)
  (** iRacing: coaching, laps, fuel, gaps, flags and the crew work. iRacing doesn't share other cars'
   positions or live tyre data, so SimCoach's spotter and tyre calls are off there (iRacing has its own
   spotter), and one-click setup apply doesn't write iRacing setup files.)

  Not supported (no public telemetry feed): NASCAR 25, NASCAR Heat 5, Project Motor Racing,
  WRC Generations, KartKraft, BeamNG.drive, CarX Street. If one of these is running, SimCoach tells you
  why it can't read telemetry rather than staying on "Waiting for a sim".


One-time game settings
----------------------
  - Automobilista 2: Options > System > Shared Memory = "Project CARS 2"
  - F1 25: Settings > Telemetry: UDP On, port 20777, format 2025
  - EA SPORTS WRC, DiRT Rally 2.0, rFactor 2: already configured automatically (EA WRC sends SimHub its
    feed on 20777 and SimCoach its own on 20790; DiRT Rally 2.0 sends on 20777).
  - Assetto Corsa:
    * Weather & live setup link (CSP / Pure / Sol): SimCoach automatically installs a small CSP Lua app
      ("SimCoach Weather Link") into Assetto Corsa's apps\lua folder via Steam. It runs automatically,
      shares rain, track wetness, puddles, and Pure Planner weather transitions, and applies the setup
      changes you tick on the setup sheet to your car. (If AC was already open when SimCoach installed or
      updated it, restart AC once to load it.)
    * Spotter & gaps: uses the CrewChiefEx Python app (Content Manager > Settings > Assetto Corsa > Python
      apps; SimCoach enables it for you).
  - ACC, AC Rally, LMU, RaceRoom: nothing needed. (RaceRoom cars are named from SimCoach's built-in list of
    360 cars; a car added to RaceRoom after this version shows as "car <number>" until SimCoach is updated.)
  - Running SimHub and SimCoach together: no setup needed. SimCoach shares UDP port 20777 with SimHub when
    SimHub listens on all addresses, steps aside if SimHub launches later, and also listens on fallback
    ports 20778 (F1) and 20779 (DiRT Rally 2.0). Untick "Share ... telemetry with SimHub" in Settings to
    disable port sharing.


What's new (latest updates)
---------------------------
  - Click-to-apply pre-race setup sheet pop-up:
    * When the Strategist and Coach call a pre-race setup (or when you ask for one), a checklist window
      opens with exact adjustments grouped by area: Fuel, Strategy, Tyres, Brakes, Aero, Suspension,
      Differential, and Electronics.
    * Click any box (the checkbox, setting name, change text, or the Apply badge) to immediately apply that
      setting in the sim.
      Assetto Corsa (needs Custom Shaders Patch): the change goes straight onto your car's current setup
      through the SimCoach Weather Link, and the sheet shows what really changed (e.g. "Rear wing 7 -> 6").
      In races and qualifying the car must be in the pits; in single-player practice it works anywhere. A
      box that couldn't be applied unticks itself and says why (not in the pits, the car has no such
      setting, already set). Unticking puts the car's own value back.
      Other sims: SimCoach writes the sim's garage setup file (SimCoach_Race.json for ACC, SimCoach_Race.svm
      for LMU and rFactor 2, plus a copy in Documents\SimCoach Reports\Setups) to load in the garage.
    * Click a ticked box again to revert that specific change back to baseline in the sim, or click
      "Apply all" / "Revert all" in the footer (or say "apply the setup" on the radio) to apply every
      change at once. "Apply all" first lists every value it will change (before -> after) and asks you
      to confirm; ticking one box shows what it changed; the radio reply says what was applied.
    * Opens by itself at the start of every session (practice, qualifying, race, hotlap or rally stage),
      even on a rolling start, together with the strategist and coach briefing. The full briefing plays the
      first session of the day with a car and track; later sessions get one short line (say "full briefing"
      for the rest, or "skip the briefing" to cut it). Settings > Race engineer, strategist & spotter:
      "Setup briefing" (Full once a day, then short / Full every session / Off) and "Open the setup sheet
      at the start of each session". Open or close it any time
      with the SETUP button on the in-game overlay, the overlay's right-click menu, a wheel button, or by
      saying "show the setup sheet". A sheet asked for later in a session, while driving, waits until you
      stop in the pits. It stays on top without stealing keyboard focus from your sim and remembers its
      screen position.
    * Every setup sheet is also saved as a text file in Documents\SimCoach Reports, listed in the Reports
      tab, and embedded as a table in your HTML Coach Report showing which items were applied in the sim.
  - Virtual energy, engine temperatures & track limits:
    * LMU and RaceRoom virtual energy: tracks energy usage per lap from lap one, warns when virtual energy
      is your stint limit before fuel ("energy's the limit this stint", "energy for three more laps", "two
      laps of energy left", "box this lap"), advises lift-and-coast when slightly short to the flag, and
      factors virtual energy into "should I pit?" and "how much fuel / energy?" calls.
    * Engine temperatures (LMU, rFactor 2, AMS2, RaceRoom, ACC, F1 25): learns your car's normal water and
      oil temperatures over the first three green laps, then warns when temperatures climb or become
      critical without nagging cars that naturally run warm. Ask "engine temps?" anytime.
    * LMU track limits: calls each new track-limits strike in qualifying and races before it becomes a
      penalty.
  - Weather, track wetness & forecasts:
    * AC (with CSP / Pure / Sol), ACC, LMU, rFactor 2, AMS2, and F1 25: pit calls for wet and slick tyres
      use both active rainfall and track surface wetness, keeping you on wets until a dry line forms.
    * Weather radar warnings ("rain within half an hour", "rain expected in the next ten minutes", or "rain
      on the way") work in ACC, F1 25, and Assetto Corsa (timed from Pure Planner's transition rate).
  - Race control flags, spotter & gaps:
    * Yellow flags, full-course yellows, virtual safety car, safety car, blue flags (in races), and "Green
      flag" calls work across AC, ACC, LMU, rFactor 2, AMS2, RaceRoom, and F1 25.
    * Built-in spotter ("Car left / Car right / Three wide / Clear / Still there") and live gaps to cars
      ahead and behind work natively in ACC, LMU, rFactor 2, AMS2, RaceRoom, F1 25, and AC (via
      CrewChiefEx), with automatic tyre-radius calibration for lock-up and wheelspin detection across all
      wheel-speed sims.


On track: live coaching & voice commands
----------------------------------------
  - Reference lap: your first clean lap (or stage run) maps every corner automatically and starts live
    coaching on the very next lap. If lap one has an off-track excursion, SimCoach still maps a provisional
    reference so coaching starts immediately, then swaps in your first clean lap.
  - Starter laps (coaching from lap one): at 24 built-in circuits (Spa, Monza, Silverstone, Suzuka, Brands
    Hatch GP, Zandvoort, Nurburgring GP, Barcelona, Red Bull Ring, Hungaroring, Hockenheim, COTA, Interlagos,
    Bahrain, Sepang, Shanghai and more) SimCoach builds an approximate reference from the track's shape for
    your car's class, when you have no lap of your own there yet. It matches the sim's track by name and
    length (other layouts are never used), lines it up over the first part of the lap, then calls braking points.
    The References tab lists them all in a "Starter laps" table: circuit, length, calculated lap time
    per car class and the real target times per sim.
    Benchmarks: the library holds quick lap times by sim and car class (ACC, iRacing, LMU, AMS2, rFactor 2,
    AC, F1). The coach tells you the target for your sim and class (or exact car) at the start of a session,
    also at tracks without a starter lap, and starter laps are tuned to match it.
    More circuits arrive automatically from the library's tracks folder (31 so far, e.g. Imola, Mugello,
    Monaco, Paul Ricard, Laguna Seca, Road America, Road Atlanta, Donington, Misano, Fuji; track shapes from
    bacinger/f1-circuits, MIT, and OpenStreetMap, (c) OpenStreetMap contributors, ODbL).
    No live delta or "time lost" against it; your first lap replaces it, and it's never saved. Settings:
    "Starter laps". Track shapes: TUMFTM racetrack-database (LGPL-3.0), from OpenStreetMap data
    (c) OpenStreetMap contributors. See THIRD_PARTY_NOTICES.md and github.com/TUMFTM/racetrack-database.
  - Best laps tab: your best lap for every sim / track / car, kept ready to share in Documents\SimCoach
    Reports\Best laps, with its library status (Not shared / Sent, waiting for approval / In the library).
    Share selected or Share all new uploads them to the library from the app: the first time, sign in to
    GitHub with the code SimCoach shows. Laps are checked and added to the library automatically within a
    minute or two (only if faster than the library's lap for that car and track). Shared: sim, track, car
    and the lap trace only.
  - SimCoach reference library: the first time you drive a sim / track / car with no lap of your own, SimCoach
    checks the shared library (the references folder of SimCoach's GitHub repository) for a lap with exactly
    that sim, track and car, and coaches you against it until you beat it. Share your own laps with
    the Best laps tab. New laps shared to the library are imported automatically (at start-up,
    every 12 hours, or References > Update from library); library laps that get faster are updated, and your
    own laps are never replaced. Settings: "Use and auto-import reference laps from the SimCoach library"
    (SimCoach only reads the library's file list and files from GitHub; nothing is sent).
  - Braking countdown: three tones (beep, beep, BEEP) timed to your reference braking point.
  - Race starts: a short reminder when you're sitting on the grid, then a start review after turn one
    (wheelspin, bogging down or lifting, 0-100 km/h time, and places gained or lost). Standing starts only.
  - Focus cues & corner-exit feedback: pre-loaded voice cues before your two biggest time-loss corners and
    immediate biomechanical diagnosis on corner exit, followed by a concise end-of-lap debrief.
  - F1 flashbacks & invalid laps: rewinding with a flashback wipes telemetry and off-track markers from the
    rewound stretch so the lap stays valid; on invalid laps, clean corners are still coached and can record
    corner personal bests.
  - Instant voice commands (push-to-talk via wheel button, on-screen button, or F8):
    * Session & pace: "radio check", "repeat", "last lap", "best lap", "theoretical best", "what's my
      pace", "after-race debrief", "write report", "reset reference"
    * Strategy & car status: "how much fuel", "how much fuel do I need", "how much energy", "should I pit",
      "how are my tyres", "damage check", "engine temps", "cars around me", "who's ahead", "who's behind"
    * Setup: "suggest a setup", "apply the setup", "show the setup sheet", "close the setup sheet"
    * Briefing: "full briefing", "skip the briefing"
    * Target and consistency: "what's the target time" (a quick lap for your sim and class, and how far off
      you are), "how consistent am I" (how much your clean laps vary, and what to work on first).
    * Practice drills: "work on turn 3 for five laps" (or "practise turn 7"; default 5 laps). The coach talks
      only about that corner, scores it every lap against your best there, sums up before vs during at the
      end and adds a table to the report. "Stop the drill" ends it early. Practice and qualifying only.
    * Audio & display controls: "be quiet", "normal coaching", "talk more", "braking tones on / off / every
      corner", "split deltas on / off", "start capture", "stop capture"
    * Open questions ("where am I losing time?", "how do I fix understeer in Turn 3?"): answered using your
      live session telemetry when an AI key (OpenAI, Google Gemini or DeepSeek) is configured in Settings.


Race crew (Engineer, Strategist & Spotter)
------------------------------------------
  - Each crew member has their own voice and can be toggled individually in Settings:
    * Pre-race setup briefing: before a race begins, the Strategist and Coach collaborate on fuel load,
      stop strategy, tyre compound/pressures, brake ducts/bias, aero wing/rake, anti-roll bars, diff
      preload, and TC/ABS, and publish the interactive checklist to the Setup Sheet window where clicking
      any box applies that setting in the sim.
    * Post-lap reports: after every lap (or every 2 laps / important calls only), the Engineer reports fuel,
      virtual energy, tyre temps/pressures/wear, and damage, while the Strategist reports position, laps to
      go, fuel plan, and gaps.
    * Live race alerts: immediate calls for position changes, pit window open/closing, undercut
      opportunities in traffic, low fuel/energy, new or worsening damage, high tyre wear, rain/drying
      track, flags, and final lap.
    * Crew chatter: natural reactions to overtakes, contact, personal bests, final lap, and chequered flag,
      plus light banter on quiet straights (configurable as Off / Normal / Lots, and Clean or Salty).
      Chatter never talks over corner cues, race alerts, or the spotter.
    * Spotter: cuts in immediately over all other audio for cars alongside. If left/right is reversed in a
      sim, tick that game under "Swap left/right in" on the Settings tab.


In-game overlay (Overlay button, top right)
-------------------------------------------
  - Borderless, always-on-top panel for windowed or borderless-fullscreen sims. Drag it anywhere (position
    is saved). Right-click to show/hide pedal gauges, reset position, lock it, or close it.
  - Lock overlay ("Lock overlay" on the main window or right-click menu): makes the overlay click-through
    so mouse clicks pass straight to the sim and it never steals focus.
  - Displays live delta to your best lap, the latest coach/crew message, live BRAKE and THROTTLE pressure
    gauges with target bands from your reference lap (TOO MUCH / ENOUGH / TOO LITTLE, plus LOCK-UP and
    WHEELSPIN flash alerts), and a scrolling 4-second pedal trace against your best lap.


Tabs & settings
---------------
  - Live: live delta, lap KPIs (last, best and theoretical best lap, your pace against the target as a
    percentage of a quick lap for your sim and class, and your consistency: how much clean laps vary),
    latest coach call, current focus corners, Hold to talk, Test voice, Setup sheet button, and Quiet mode
    toggle.
  - Quick setup: on first launch SimCoach asks three things: your name, where the coach's voice should
    play (with a test call), and which wheel button you hold to talk. Run it again any time from
    Settings > Quick setup.
  - Best laps: your best lap per sim / track / car, ready to share. Tick "Share new best laps
    automatically" to send new and improved laps to the library without being asked each time (off by
    default; needs GitHub sign-in).
  - Radio check: test push-to-talk, microphone level meter, speech recognition, coach reply, voice output,
    and total round-trip time before launching a sim, or send a typed question.
  - Laps & corners: live session lap table and turn-by-turn loss, minimum speed, and issue breakdown.
  - Settings:
    * Voice & audio: driver name, coach voice, speaking speed, volume, speaker/headset (including VR
      headsets), microphone, and speech recognition (offline recognition runs on your PC for free; "OpenAI
      online (uses key)" sends only your push-to-talk clips to OpenAI and falls back to offline recognition
      if the connection drops). Supports Microsoft neural voices, Google voices, and local neural voices.
    * Wheel buttons: bind Push-to-talk (hold), Repeat last message, Mute/unmute coach, Braking tones
      on/off, Show/hide overlay, Start/stop a data capture, and Show/hide the setup sheet. Works while the
      game has focus (F8 is the keyboard fallback for push-to-talk).
    * Coaching: talk level (Quiet / Normal / Chatty), Coach personality (Apex all-round pro, Rotation,
      Composed, Feel, Exit, or Data; say e.g. "data coach" or "switch to composed style" on the radio),
      braking tones, split deltas, auto-start, F1 UDP port, and SimHub port sharing. At Normal, the lap
      debrief is short (lap time, gap to your best, one coaching point, fuel warnings) and corner callouts
      cover your focus corners and big losses; Chatty adds everything else. Laps spoiled by traffic, a
      yellow flag or cold tyres are never roasted or blamed. New installs start with the Composed coach and
      Important-only crew lap reports.
    * Phone / tablet screen: click "Phone screen" at the top of the SimCoach window. It switches the live
      page on and shows a QR code and an address: connect the phone or tablet to the same Wi-Fi as the PC,
      scan the code with its camera (or type the address into its browser) for a big live delta, lap times,
      position, gaps, fuel and the coach's last call. "Test on this PC" opens the same page in your browser.
      The same switch is the "Phone / tablet live screen" tick box in Settings. Read-only: nothing on the page can change SimCoach. Windows may ask once to allow SimCoach
      on private networks. Crew banter never holds up urgent calls: an urgent call cuts it short.
    * Updates: "Tell me when an update is out" (on by default) checks GitHub for a newer SimCoach at start-up
      and every 12 hours. A banner offers Install update (downloads the new SimCoach-Setup.exe and runs it;
      it closes SimCoach, saves your session and keeps your settings), What's new, or Not now (skips that
      version). If you run SimCoach from the zip folder instead of the installer, it offers Download.
      "Check now" checks straight away.
    * Conversation (AI): pick the AI provider (OpenAI, Google Gemini or DeepSeek), paste its API key and
      click "Test key". Keys are stored locally in %APPDATA%\SimCoach\config.json (or set the
      OPENAI_API_KEY, GEMINI_API_KEY or DEEPSEEK_API_KEY environment variable). With "try my other keys"
      ticked, if the chosen provider is down or busy SimCoach asks the next one you have a key for.
      Online speech recognition always uses the OpenAI key.
  - References: view, delete, export, and import reference laps (%APPDATA%\SimCoach\references). Import a
    faster driver's reference JSON to be coached against their lap.
  - Reports: browse, open, write mid-session snapshots, or delete HTML Coach Reports, text after-race
    debriefs, and text setup sheets (saved in Documents\SimCoach Reports, including OneDrive Documents).
  - Log & data capture: view live logs (%APPDATA%\SimCoach\simcoach.log) or record a 60-second (up to
    5-minute) telemetry capture zip into Documents\SimCoach Reports\Captures via the Log tab button, a
    wheel button, or by saying "start capture" / "stop capture". Captures contain only game telemetry and
    session logs, never your settings or API keys.
