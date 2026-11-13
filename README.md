# SimCoach - Live English Voice Coach & Race Crew (Windows 10/11)

### Download & Preview
* **[Download SimCoach-Setup.exe (Windows Installer, v6.10.1)](SimCoach-Setup.exe)**
* **[Latest Release & Full ZIP](../../releases/latest)**
* **[▶️ Watch Preview Video (1080p MP4)](simcoach_preview.mp4)**

### Install
Run `SimCoach-Setup.exe`. No admin rights needed; it installs Python 3.12, SimCoach's packages and free offline speech recognition. If Windows SmartScreen appears: *More info → Run anyway*. SimCoach tells you when a newer release is out and can install it for you.

### Supported sims
Assetto Corsa, ACC, AC EVO, AC Rally, Le Mans Ultimate, rFactor 2, Automobilista 2 (*Shared Memory = Project CARS 2*), RaceRoom, iRacing, F1 25 (*UDP 20777, format 2025*), EA WRC and DiRT Rally 2.0. Shares port 20777 with SimHub.

### What it does
* **Live voice coaching:** braking tones, focus-corner cues and exit diagnosis against your reference lap, with a short debrief each lap. Six coach styles (Apex, Rotation, Composed, Feel, Exit, Data).
* **Coaching from lap one:** at 43 circuits SimCoach calculates a *starter lap* for your car's class and lines it up with your sim during the first lap, so braking calls start before you've set a time. Your first clean lap replaces it.
* **Target lap times:** the coach tells you what a quick lap is for your sim and class (or exact car) at 48 tracks, from 87 benchmark times across ACC, iRacing, LMU, AMS2, rFactor 2, AC and F1.
* **Race crew:** engineer, strategist and spotter call fuel, virtual energy, temperatures, wear, track limits, weather, flags, gaps and cars alongside. Urgent calls cut in ahead of everything else.
* **Race starts and drills:** a grid reminder and a start review after turn one; say *"work on turn 3 for five laps"* for a focused drill.
* **Setup help:** a setup briefing and a click-to-apply setup sheet at the start of every session (it shows each change and asks first).
* **Shared reference library:** laps other drivers share are downloaded automatically for your exact sim, track and car. The **Best laps** tab keeps your own best laps and shares them in one click, or automatically if you switch that on (free GitHub sign-in); a shared lap is checked and added automatically if it's the fastest for that combination.
* **Pace and consistency:** your best lap as a percentage of the target, how repeatable your laps are, and which of the two to work on first.
* **Overlay and phone screen:** a click-through overlay with delta and pedal traces, plus a live page for a phone or tablet on the same Wi-Fi (click *Phone screen* and scan the code).
* **Talk to it:** push-to-talk (wheel button or F8) with offline speech recognition; optional AI answers, banter and setup briefings through OpenAI, Google Gemini or DeepSeek, with automatic fallback.
* **Reports:** an HTML report after each session.

The full guide is in [README.txt](README.txt). The library's rules are in [references/](references/). Developer tools and the release checklist are in [tools/](tools/). Third-party data credits are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

### What's new in 6.10.1
* **Fairer consistency score:** laps more than 2 % off your best (early laps while you learn the track, or a lap spoiled by traffic) are now set aside, so getting quicker through a session no longer counts as being inconsistent. Found in a test session where steady laps after a learning lap were rated "inconsistent, 3.6 seconds".

### What's new in 6.10
* **Pace against the target:** the Live tab shows your best lap as a percentage of a quick lap for your sim and class (or exact car), e.g. *103.4% · target 2:16.4*. The coach says it after a new best lap and in the after-race report, the HTML report has it with a "Where you are" verdict, and the Progress table tracks it across sessions. Ask *"what's the target time?"*.
* **Consistency score:** how much your clean laps vary (very consistent / consistent / a bit up and down / inconsistent), on the Live tab, in the debrief and in the report. A single ruined lap is set aside rather than averaged in. The coach tells you whether to work on consistency or pace first. Ask *"how consistent am I?"*.
* **Quick setup on first launch:** three short steps: your name, where the coach's voice plays (with a test call), and your push-to-talk wheel button. Run it again from *Settings → Quick setup*.
* **Share new best laps automatically** (Best laps tab, off by default): once you're signed in to GitHub, new and improved best laps go to the library without asking each time, with the same checks as sharing by hand.
* **RaceRoom car names:** RaceRoom only reports a car number, so cars showed as "car 1738". They now have their real names and classes (360 cars, from Sector3's own data), so target times and the right starter-lap class work in RaceRoom. References saved under the old names are moved over automatically.

### What's new in 6.9.1
* **Phone screen button:** the phone / tablet live screen was hidden in Settings. A *Phone screen* button at the top of the window now switches it on and shows a QR code to scan, the address, *Copy address* and *Test on this PC*. It also says so when the PC isn't on a network, and lists the PC's other addresses if it has more than one.

* **Starter laps table:** the References tab now lists every circuit with a starter lap (43) with its length, the calculated lap time for GT3, GT4, prototype and F1 cars, and the real target times for each sim, plus the 27 tracks that have target times only.
* **Settings layout:** the right-hand column (wheel-button *Set* / *Clear*, coaching options) can no longer be cut off at the window edge; the window opens a little wider. Smaller text fixes on the Radio check and Best laps tabs.

### What's new in 6.9
* **Benchmark lap times for every sim:** 87 quick, repeatable lap times by sim and car class (ACC, iRacing, Le Mans Ultimate, Automobilista 2, rFactor 2, Assetto Corsa and F1) are in the library's [benchmarks](references/benchmarks/laps.json), from setup-shop reference laps, leaderboards and league results. At the start of a session the coach tells you the target for your sim and class ("a quick GT3 lap here is about 2:16.4"), or for your exact car where there is one (e.g. the GTP cars at Montreal). 48 tracks have targets, including ones with no starter lap (Nordschleife, Le Mans, Bathurst, Laguna Seca, Road Atlanta, Long Beach, The Bend and more).
* **Starter laps tuned to them:** at circuits with a starter lap, the calculated lap is tuned so its lap time matches your sim's benchmark, which moves its corner speeds and braking points toward a real quick lap. Before tuning, the calculated GT3 laps were already within about 4 % of the benchmarks.
* **References tab** lists the starter-lap circuits.

### What's new in 6.8
* **Starter laps at 19 more circuits**, delivered through the library so every SimCoach gets them automatically (no app update needed for future tracks): Imola, Mugello, Monaco, Paul Ricard, Portimão, Kyalami, Watkins Glen, Estoril, Magny-Cours, Istanbul, Singapore, Baku, Jeddah, Miami, Las Vegas, Lusail, Madrid, Buenos Aires and Jacarepaguá. That makes 43 circuits with coaching from lap one, for any supported sim and car. These are calculated laps (approximate braking points, no live delta); your first clean lap replaces them. Track shapes: [bacinger/f1-circuits](https://github.com/bacinger/f1-circuits) (MIT).
* **Starter laps line up far more reliably:** the lap is matched to the sim's start line from the shape of your speed trace over the first part of the lap, and copes with start lines up to 8 % of a lap away (the old method often gave up).

### What's new in 6.7.1
* **Sharing fixes:** sharing works for drivers whose copy of the library on GitHub is out of date; clearer messages when GitHub sign-in can't start; laps shared by several drivers at the same moment are all processed.
* **Library clean-up:** a lap that's taken out of the library is removed from everyone's downloaded laps at the next check (your own laps are never touched).

### What's new in 6.7
* **Best laps tab:** your best lap for every sim, track and car, saved ready to share (*Documents\SimCoach Reports\Best laps*), with its library status.
* **Share from the app:** *Share selected* or *Share all new* uploads laps to the SimCoach library. Sign in to GitHub once with a short code (your password never goes through SimCoach). Laps are checked and added automatically within a minute or two (clean, believable and faster than the library's lap for that car and track), then reach every SimCoach driver.

### What's new in 6.6
* **Library laps import automatically:** new laps shared to the [SimCoach reference library](references/) are added to your References at start-up and every 12 hours (or *References → Update from library*). Library laps that someone improves are updated too; your own laps are never replaced. If a lap arrives for the car and track you're driving, the coach switches to it and tells you.

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
