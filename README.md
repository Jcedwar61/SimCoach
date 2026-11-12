# SimCoach - Live English Voice Coach & Race Crew (Windows 10/11)

### Download & Preview
* **[Download SimCoach-Setup.exe (Windows Installer, v6.5)](SimCoach-Setup.exe)**
* **[Latest Release & Full ZIP](../../releases/latest)**
* **[▶️ Watch Preview Video (1080p MP4)](simcoach_preview.mp4)**

* **Install:** Run `SimCoach-Setup.exe` (no admin needed; installs Python 3.12, packages & free offline speech recognition; SmartScreen: *More info > Run anyway*) or `SimCoach.bat`.
* **Supported Sims:** AC, ACC, AC Rally, AC EVO*, LMU, rF2, AMS2 (*Shared Memory = Project CARS 2*), RaceRoom, **iRacing**, EA WRC, F1 25 (*UDP 20777, 2025*), DiRT Rally 2.0. Shares port 20777 with SimHub.
* **Live Coaching & Crew:** First clean lap maps corners for braking tones, focus cues & exit diagnosis. Engineer, Strategist & Spotter call fuel, virtual energy, temps, wear, track limits, rain/wetness, flags, gaps, cars alongside & banter.
* **Setup, Overlay & Voice:** Click-to-apply setup sheet updates setups directly in-sim. Click-through overlay shows delta & pedal traces. Push-to-talk (wheel/F8), ref sharing, HTML reports & optional AI Q&A (OpenAI, Google Gemini or DeepSeek, with automatic fallback).

### What's new in 6.5
* **Coaching from lap one:** at 24 well-known circuits SimCoach builds a *starter lap* from the track's shape for your car's class (GT3, GT4, cup, GTE, prototype, F1, single-seater, road car) when you have no lap of your own there. It lines up with your sim over the first corners, then calls braking points; your first lap replaces it. Track data: [TUMFTM racetrack-database](https://github.com/TUMFTM/racetrack-database) (LGPL-3.0) from OpenStreetMap data, © OpenStreetMap contributors — see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
* **SimCoach reference library:** laps shared by drivers in [references/](references/). The first time you drive a combination, SimCoach fetches a lap for exactly that sim, track and car if there is one. Share yours with *References → Share to library*.

### What's new in 6.4
* **Calmer session starts:** the first session of the day with a car and track gets the full intros and setup briefing; later sessions get one short line plus the setup sheet. Say *"full briefing"* to hear it all, or *"skip the briefing"* to cut it. Settings: briefing *Full once a day, then short* / *Full every session* / *Off*, and a switch for the automatic setup sheet pop-up.
* **Less talk per lap:** the lap debrief is lap time, gap to your best and one coaching point (plus fuel warnings); corner callouts focus on your focus corners and big losses. *Chatty* keeps the full version. New installs: crew lap reports *Important calls only*.
* **Fair coaching:** no roasting or corner blame for laps spoiled by traffic, yellow flags or cold tyres; new installs start with the calm *Composed* coach.

### What's new in 6.3
* **Update notice:** SimCoach checks GitHub for a newer release (at start-up and every 12 hours) and shows a banner with *Install update*, *What's new* and *Not now*. Turn it off or *Check now* in Settings.
* **Setup briefing is a priority call** at the start of every session, so it's always heard ahead of intros and banter.

### What's new in 6.2.1
* **Setup sheet pops up at the start of every session** (practice, qualifying, race, hotlap, rally), even on a rolling start.
* **Open the setup sheet from the overlay:** a SETUP button, plus *Show / hide setup sheet* in its right-click menu.

### What's new in 6.2
* **Choose your AI:** OpenAI, Google Gemini or DeepSeek for Q&A, crew banter and setup briefings, with automatic fallback to your other keys if one is down.
* **Fixed:** live setup changes in Assetto Corsa (CSP) now apply; the overlay's *Reset position* saves correctly; closing the overlay no longer quits the app.
* **Track limits** calls now say how many strikes you have.
* **Friendlier first run:** SimCoach asks what the crew should call you, and crew radio starts clean (swearing is opt-in in Settings).
* **iRacing support:** coaching, laps, fuel, gaps, flags and the crew (no SimCoach spotter or live tyre data there).
* **Practice drills:** say "work on turn 3 for five laps" and the coach focuses on that corner, then sums up your progress.
* **Race-start coaching:** a grid reminder, then a start review after turn one (launch, 0-100, places gained or lost).
* **Phone / tablet screen:** optional live page with a big delta, laps, gaps and fuel on the same Wi-Fi.
* **Safer setup apply:** "Apply all" shows every before → after change and asks first.
* **Urgent calls cut banter short**, so a box call or flag is never stuck behind a joke.
* **Coach personalities** are now named by style: Apex, Rotation, Composed, Feel, Exit and Data. Switch on the radio with e.g. "data coach".
* **Installer:** downloads uv straight from its official GitHub release instead of running a remote script, and the app shows its version in the title bar.
