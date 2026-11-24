# SimCoach changelog

Every release, newest first. The README has the latest one.

## What's new in 6.20
* **Fixes the slow window in 6.19:** switching tabs, scrolling and resizing had become very slow (seconds per
  tab on some PCs) because of how 6.19 drew its new rounded controls. They're prepared once at start-up now, so
  the window responds at normal speed again, with the same new look.

## What's new in 6.19
* **A refined look:** the SimCoach window has been redesigned. Buttons, text boxes, drop-downs, cards,
  check boxes, sliders and scroll bars are now smooth and rounded; the tabs are clean labels with an
  underline on the one you're in; the top bar is calmer, with *Start coaching* standing out as the one main
  action; tables are roomier; and the Live tab lists your lap stats in a tidy column.
* **Welcome box:** the first-run quick setup opens in the middle of the window and takes the keyboard, so you
  can type your name straight away.

## What's new in 6.18
* **Session goals:** when a session ends, the one or two corners that cost you the most time per clean lap
  become the goal for your next session with that car and track. The coach names the goal in its opening
  call, makes those corners your first focus corners, shows how each is going against last session on the
  Live tab, and says *"Goal done"* once you're quicker there over three clean laps. The Coach Report has a
  *Goal from last session* table, the AI analysis sees it, and you can ask *"what's my goal?"*.
* **Simple view:** new installs show only the coaching essentials (four tabs and the everyday settings);
  *Show everything* brings back every tab and setting. Copies updated from an earlier version keep showing
  everything until you click *Simple view*.
* **A shorter README:** the release history has moved to [CHANGELOG.md](CHANGELOG.md).

## What's new in 6.17
* **A provider for each AI job:** *Settings → Who does what* sends radio answers, crew banter, setup briefings, the session analysis and command understanding each to OpenAI, Google Gemini or DeepSeek. Use DeepSeek for the frequent, cheap banter and OpenAI for answers, for example. A job whose provider has no key uses the main one, and the fallback still covers outages. Any saved key now switches the AI features on, not only the main provider's.
* **The coach's analysis in every report:** with an AI key, each Coach Report and after-race text gets a written verdict, what went well, where the time goes and a practice plan, from the session's corners, laps and your earlier sessions. It's added a few seconds after the report is written. After a race the coach also reads out the verdict and the first thing to practise. Switch it off in Settings.
* **Commands in your own words:** "pipe down for a bit" or "let's practise turn four for three laps" now run the matching radio command. Only harmless commands can be picked this way: resetting your reference or changing the car's setup still needs the exact words.
* **"Am I improving?"** The radio AI now sees your earlier sessions at the track.

## What's new in 6.16
* **New licence:** SimCoach is now licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE) instead of MIT. It stays free to use, share and change for any noncommercial purpose; commercial use needs the author's permission. Nothing else changes.

## What's new in 6.15
* **SimCast from the setup wizard:** SimCoach-Setup.exe has a new option, *SimCast: TV commentary for your race* (unticked). Tick it and setup also installs the latest [SimCast](https://github.com/Jcedwar61/SimCast), downloaded from its GitHub release and checked against the published SHA-256 before it runs. With SimCast already installed, the option offers to update it instead. The two stay separate apps with their own updates and uninstallers.
* **One voice model for both:** SimCoach and SimCast already shared Python and their packages; now they share the Kokoro voice model too. If SimCast has downloaded it (about 115 MB), SimCoach uses that copy instead of downloading it again, and the other way round.
* **A written contract for the SimCast link:** [docs/simcast-link.md](docs/simcast-link.md) sets out the messages SimCoach sends while the coach talks and how they may change, so any SimCoach keeps working with any SimCast. Nothing changes on the wire.

## What's new in 6.14
* **Push-to-talk you can trust.** Speech recognition is rebuilt. The microphone now runs all the time, so the half second *before* you press is already recorded and nothing at the front of a sentence is lost. The clip is cleaned (DC and handling rumble removed, speech band passed, a noise gate against fan and sim noise, level normalised) and decoded with radio bias words, so "box this lap", "sector two" and "brake bias" come back as words instead of guesses; a thin result is decoded a second way before anything reaches the coach. On test clips the word error rate fell from 5.8% to 0.8% clean and from 11.9% to 6.8% on a noisy headset mic, at roughly half the delay.
* **The right mic, the right way.** Mics are opened on **WASAPI in shared mode** (DirectSound, MME and WDM-KS follow in that order), so nothing else can be shut out of your headset; an unplugged headset falls back to the Windows default instead of leaving push-to-talk dead (it used to hold the mic open for the whole session). New *Settings → Mic input* and *Mic boost*, and the radio check names the API it opened and shows the pre-roll. Short commands are no longer thrown away.
* **Fixed:** the speech model setting was ignored after a restart, and a very quiet mic was rejected.

## What's new in 6.13
* **Runs alongside SimCast:** with [SimCast](https://github.com/Jcedwar61/SimCast) (live TV commentary for your race) running at the same time, the commentary drops under the coach and crew while they talk, braking tones included, and comes back up after. Both keep talking; neither goes silent. Set how far it drops in SimCast (*Settings → Voices → When SimCoach talks*, SimCast 1.1 or later). Nothing leaves your PC.

## What's new in 6.12
* **A proper Windows installer:** SimCoach-Setup.exe is now a standard setup wizard: welcome, licence, choose your shortcuts and install folder, a progress page, then *Start SimCoach*. The downloads (Python, packages, speech recognition) happen inside the wizard instead of a console window. Uninstall from *Settings → Apps* as before; your laps, settings and reports are kept.
* **New icon:** the helmet-and-headset icon on the desktop, Start menu, taskbar, the app window and the installer.

## What's new in 6.11.1
* **Setup sheet works in Assetto Corsa:** ticking a box now changes your car's actual setup (fuel, tyre pressures, brake bias, wing, anti-roll bars, dampers, diff, TC, ABS, tyre compound) through SimCoach's helper app in Custom Shaders Patch, and the sheet shows what really changed, e.g. *Rear wing 7 → 6*. Before, it changed nothing in the car. In races and qualifying the car must be in the pits (in single-player practice, anywhere); a box that can't be applied unticks itself and says why. Unticking puts your car's own value back. **Restart Assetto Corsa once after updating** so it loads the new helper.

## What's new in 6.11
* **Starter laps at 12 more circuits:** Laguna Seca, Road America, Road Atlanta, Donington, Misano, Zolder, Valencia, Jerez, Fuji, The Bend, and the Indianapolis GP and road course layouts, built from OpenStreetMap track outlines (© OpenStreetMap contributors, ODbL). Each was checked against real lap times: within 4 % before tuning. That's 55 circuits with coaching from lap one, delivered through the library.
* **Crew banter matches your pace:** while you're well off a quick lap or your own best, the strategist encourages instead of saying "pace is solid".
* **Report fuel:** the setup sheet in the report shows the fuel you actually used per lap, not the guess from the start of the session.

## What's new in 6.10.1
* **Fairer consistency score:** laps more than 2 % off your best (early laps while you learn the track, or a lap spoiled by traffic) are now set aside, so getting quicker through a session no longer counts as being inconsistent. Found in a test session where steady laps after a learning lap were rated "inconsistent, 3.6 seconds".

## What's new in 6.10
* **Pace against the target:** the Live tab shows your best lap as a percentage of a quick lap for your sim and class (or exact car), e.g. *103.4% · target 2:16.4*. The coach says it after a new best lap and in the after-race report, the HTML report has it with a "Where you are" verdict, and the Progress table tracks it across sessions. Ask *"what's the target time?"*.
* **Consistency score:** how much your clean laps vary (very consistent / consistent / a bit up and down / inconsistent), on the Live tab, in the debrief and in the report. A single ruined lap is set aside rather than averaged in. The coach tells you whether to work on consistency or pace first. Ask *"how consistent am I?"*.
* **Quick setup on first launch:** three short steps: your name, where the coach's voice plays (with a test call), and your push-to-talk wheel button. Run it again from *Settings → Quick setup*.
* **Share new best laps automatically** (Best laps tab, off by default): once you're signed in to GitHub, new and improved best laps go to the library without asking each time, with the same checks as sharing by hand.
* **RaceRoom car names:** RaceRoom only reports a car number, so cars showed as "car 1738". They now have their real names and classes (360 cars, from Sector3's own data), so target times and the right starter-lap class work in RaceRoom. References saved under the old names are moved over automatically.

## What's new in 6.9.1
* **Phone screen button:** the phone / tablet live screen was hidden in Settings. A *Phone screen* button at the top of the window now switches it on and shows a QR code to scan, the address, *Copy address* and *Test on this PC*. It also says so when the PC isn't on a network, and lists the PC's other addresses if it has more than one.

* **Starter laps table:** the References tab now lists every circuit with a starter lap (43) with its length, the calculated lap time for GT3, GT4, prototype and F1 cars, and the real target times for each sim, plus the 27 tracks that have target times only.
* **Settings layout:** the right-hand column (wheel-button *Set* / *Clear*, coaching options) can no longer be cut off at the window edge; the window opens a little wider. Smaller text fixes on the Radio check and Best laps tabs.

## What's new in 6.9
* **Benchmark lap times for every sim:** 87 quick, repeatable lap times by sim and car class (ACC, iRacing, Le Mans Ultimate, Automobilista 2, rFactor 2, Assetto Corsa and F1) are in the library's [benchmarks](references/benchmarks/laps.json), from setup-shop reference laps, leaderboards and league results. At the start of a session the coach tells you the target for your sim and class ("a quick GT3 lap here is about 2:16.4"), or for your exact car where there is one (e.g. the GTP cars at Montreal). 48 tracks have targets, including ones with no starter lap (Nordschleife, Le Mans, Bathurst, Laguna Seca, Road Atlanta, Long Beach, The Bend and more).
* **Starter laps tuned to them:** at circuits with a starter lap, the calculated lap is tuned so its lap time matches your sim's benchmark, which moves its corner speeds and braking points toward a real quick lap. Before tuning, the calculated GT3 laps were already within about 4 % of the benchmarks.
* **References tab** lists the starter-lap circuits.

## What's new in 6.8
* **Starter laps at 19 more circuits**, delivered through the library so every SimCoach gets them automatically (no app update needed for future tracks): Imola, Mugello, Monaco, Paul Ricard, Portimão, Kyalami, Watkins Glen, Estoril, Magny-Cours, Istanbul, Singapore, Baku, Jeddah, Miami, Las Vegas, Lusail, Madrid, Buenos Aires and Jacarepaguá. That makes 43 circuits with coaching from lap one, for any supported sim and car. These are calculated laps (approximate braking points, no live delta); your first clean lap replaces them. Track shapes: [bacinger/f1-circuits](https://github.com/bacinger/f1-circuits) (MIT).
* **Starter laps line up far more reliably:** the lap is matched to the sim's start line from the shape of your speed trace over the first part of the lap, and copes with start lines up to 8 % of a lap away (the old method often gave up).

## What's new in 6.7.1
* **Sharing fixes:** sharing works for drivers whose copy of the library on GitHub is out of date; clearer messages when GitHub sign-in can't start; laps shared by several drivers at the same moment are all processed.
* **Library clean-up:** a lap that's taken out of the library is removed from everyone's downloaded laps at the next check (your own laps are never touched).

## What's new in 6.7
* **Best laps tab:** your best lap for every sim, track and car, saved ready to share (*Documents\SimCoach Reports\Best laps*), with its library status.
* **Share from the app:** *Share selected* or *Share all new* uploads laps to the SimCoach library. Sign in to GitHub once with a short code (your password never goes through SimCoach). Laps are checked and added automatically within a minute or two (clean, believable and faster than the library's lap for that car and track), then reach every SimCoach driver.

## What's new in 6.6
* **Library laps import automatically:** new laps shared to the [SimCoach reference library](references/) are added to your References at start-up and every 12 hours (or *References → Update from library*). Library laps that someone improves are updated too; your own laps are never replaced. If a lap arrives for the car and track you're driving, the coach switches to it and tells you.

## What's new in 6.5
* **Coaching from lap one:** at 24 well-known circuits SimCoach builds a *starter lap* from the track's shape for your car's class (GT3, GT4, cup, GTE, prototype, F1, single-seater, road car) when you have no lap of your own there. It lines up with your sim over the first corners, then calls braking points; your first lap replaces it. Track data: [TUMFTM racetrack-database](https://github.com/TUMFTM/racetrack-database) (LGPL-3.0) from OpenStreetMap data, © OpenStreetMap contributors — see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
* **SimCoach reference library:** laps shared by drivers in [references/](references/). The first time you drive a combination, SimCoach fetches a lap for exactly that sim, track and car if there is one. Share yours with *References → Share to library*.

## What's new in 6.4
* **Calmer session starts:** the first session of the day with a car and track gets the full intros and setup briefing; later sessions get one short line plus the setup sheet. Say *"full briefing"* to hear it all, or *"skip the briefing"* to cut it. Settings: briefing *Full once a day, then short* / *Full every session* / *Off*, and a switch for the automatic setup sheet pop-up.
* **Less talk per lap:** the lap debrief is lap time, gap to your best and one coaching point (plus fuel warnings); corner callouts focus on your focus corners and big losses. *Chatty* keeps the full version. New installs: crew lap reports *Important calls only*.
* **Fair coaching:** no roasting or corner blame for laps spoiled by traffic, yellow flags or cold tyres; new installs start with the calm *Composed* coach.

## What's new in 6.3
* **Update notice:** SimCoach checks GitHub for a newer release (at start-up and every 12 hours) and shows a banner with *Install update*, *What's new* and *Not now*. Turn it off or *Check now* in Settings.
* **Setup briefing is a priority call** at the start of every session, so it's always heard ahead of intros and banter.

## What's new in 6.2.1
* **Setup sheet pops up at the start of every session** (practice, qualifying, race, hotlap, rally), even on a rolling start.
* **Open the setup sheet from the overlay:** a SETUP button, plus *Show / hide setup sheet* in its right-click menu.

## What's new in 6.2
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
