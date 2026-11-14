# SimCoach

**Free, offline live voice coach, full race crew (Engineer, Strategist, Spotter), click-to-apply garage setups, and in-game pedal overlay for PC sim racing.**

[](https://github.com/Jcedwar61/SimCoach/releases/latest)
[](https://www.overtake.gg/downloads/simcoach-free-live-voice-coach-race-crew.88561/)
[](https://github.com/Jcedwar61/SimCoach)

**SimCoach** ([GitHub Repository](https://github.com/Jcedwar61/SimCoach) | [OverTake.gg Download](https://www.overtake.gg/downloads/simcoach-free-live-voice-coach-race-crew.88561/)) runs 100% locally on your PC with zero recurring subscriptions and zero telemetry upload lag. It works fully offline out of the box, automatically shares UDP port `20777` with SimHub, and optionally connects to your own OpenAI, Google Gemini, or DeepSeek API keys (with automatic fallback) for freeform radio Q&A, setup briefings, and crew banter.

## Supported Sims

| Simulator | Live Coaching & Crew | Click-to-Apply Setups | Special Telemetry Integration |
| :--- | :--- | :--- | :--- |
| **Assetto Corsa (AC)** | Full Crew + Spotter | Native Garage File Update | Auto-installed CSP Lua link & Pure Planner weather |
| **Assetto Corsa Competizione (ACC)** | Full Crew + Spotter | Native Garage File Update | Full GT3/GT4 class benchmarks & tyre wear |
| **Le Mans Ultimate (LMU)** | Full Crew + Spotter | Native Garage File Update | Virtual energy tracking & lift-and-coast calls |
| **rFactor 2** | Full Crew + Spotter | Native Garage File Update | Full telemetry, stint strategy & spotter |
| **iRacing** | Coaching, Crew, Fuel, Gaps & Flags | Setup Briefing & Advice | Session benchmarks (no SimCoach spotter/live tyre data) |
| **Automobilista 2 (AMS2)** | Full Crew + Spotter | Setup Briefing & Advice | Full UDP/shared-memory telemetry & benchmarks |
| **RaceRoom (R3E)** | Full Crew + Spotter | Setup Briefing & Advice | Virtual energy tracking & lift-and-coast calls |
| **F1 25** | Full Crew + Spotter | Setup Briefing & Advice | Flashback recovery & UDP `20777` SimHub sharing |
| **EA SPORTS WRC & DiRT Rally 2.0** | Live Coaching & Crew | Setup Briefing & Advice | Stage coaching & UDP `20777` SimHub sharing |
| **Assetto Corsa EVO & AC Rally** | Live Coaching & Crew | Setup Briefing & Advice | Ready for early-access telemetry integration |

## Key Features

* **Coaching From Lap One (43 Starter-Lap Circuits & 87 Benchmarks)**: Calculates a starter reference lap from real circuit geometry ([TUMFTM Racetrack Database](https://github.com/TUMFTM/racetrack-database) and [bacinger/f1-circuits](https://github.com/bacinger/f1-circuits)) tuned to 87 repeatable class benchmarks across 48 tracks—giving you immediate braking countdowns on out-laps before your first clean lap replaces it.
* **Live Corner Coaching & Practice Drills**: Delivers 3-tone braking countdowns, focus cues before key corners, and instant biomechanical exit diagnosis without blaming you for laps ruined by traffic, yellow flags, or cold tyres. Say `"work on turn 3 for five laps"` on the radio for targeted corner drills or get automatic race-start reviews after Turn 1 (launch, 0–100, and positions gained/lost).
* **Six Distinct Coach Personalities**: Starts on the calm **Composed** coach by default (with profanity opt-in in Settings). Switch styles anytime over the radio between **Apex**, **Rotation**, **Composed**, **Feel**, **Exit**, and **Data** (e.g., say `"data coach"`).
* **Full Multi-Voice Race Crew**: Assigns individual voices to your **Engineer** (fuel, tyre temps/wear, engine temps, track-limit strikes), **Strategist** (radar rain forecasts, drying-line pit calls, stint plans), and **Spotter** (cars alongside). Urgent box or flag calls automatically cut banter short.
* **Click-to-Apply Setup Sheet**: Pops up automatically in the pits or on the grid (or via the `SETUP` button on the overlay). Clicking any recommendation previews every `before -> after` change and directly updates your sim's native garage setup file in AC, ACC, LMU, and rFactor 2.
* **Click-Through In-Game Overlay & Wi-Fi Companion Screen**: Displays a live delta, target brake/throttle pressure bands, and a 4-second scrolling pedal trace against your best lap without stealing mouse focus, plus an optional live telemetry page for a phone or tablet on the same Wi-Fi.
* **Community Reference Lap Library**: Saves your fastest clean lap per sim, car, and track in `Documents\SimCoach Reports\Best laps`. Sign in to GitHub once with a short device code to upload your best laps or automatically sync faster verified community reference laps every 12 hours (your own laps are never overwritten).
* **Push-to-Talk Radio & Multi-AI Support**: Bind Push-to-Talk to any steering wheel button or `F8` to ask `"how much fuel"`, `"should I pit"`, `"suggest a setup"`, `"engine temps"`, or `"skip the briefing"`. Supports OpenAI, Google Gemini, and DeepSeek keys with automatic failover.

## Installation & Quick Start

1. **Download the Latest Release**: Grab the latest installer or release archive from [SimCoach Releases on GitHub](https://github.com/Jcedwar61/SimCoach/releases/latest) or [SimCoach on OverTake.gg](https://www.overtake.gg/downloads/simcoach-free-live-voice-coach-race-crew.88561/).
2. **Run the Installer**: The installer downloads `uv` directly from its official GitHub release and configures your local environment.SimCoach checks GitHub at startup and every 12 hours for one-click updates.
3. **Launch & Drive**: Start SimCoach alongside your simulator (and SimHub—UDP port `20777` is shared automatically). On first launch, tell the crew what name to call you and bind your Push-to-Talk button (`F8` or wheel button).

## Repository & OverTake.gg Short Descriptions (Copy-Paste Ready)

* **GitHub Repository Description (under 160 chars, replace current tagline)**:
  `Free offline sim racing voice coach, AI race engineer, strategist & spotter. Click-to-apply setups, pedal trace overlay & SimHub UDP 20777 sharing.`
* **GitHub Topics (add in Repo Settings -> Gear Icon)**:
  `sim-racing` `simhub` `assetto-corsa` `assetto-corsa-competizione` `le-mans-ultimate` `iracing` `rfactor2` `automobilista-2` `f1-25` `race-engineer` `spotter` `telemetry`
* **OverTake.gg Resource Tagline (under 100 chars — fixes cut-off "click-to-apply setups & ov")**:
  `Free offline voice coach, race crew (engineer/strategist/spotter), click-to-apply setups & overlay.`
* **OverTake.gg Consolidation Note**:
  You currently have two separate listings on OverTake.gg ([Listing #88561](https://www.overtake.gg/downloads/simcoach-free-live-voice-coach-race-crew.88561/) with 25 downloads and [Listing #88689](https://www.overtake.gg/downloads/simcoach.88689/) with 8 downloads) that both carry the auto-flagged `possiblefalsepositive` tag. Keeping `#88561` as your single canonical listing, pasting the full `6.2 -> 6.9` changelog into its Updates tab, and removing `#88689` (plus deleting the `possiblefalsepositive` tag on `#88561` if editable) will merge all your views, downloads, and ratings in one place.

## Credits & Third-Party Notices

* Circuit geometry and starter-lap track shapes use [TUMFTM/racetrack-database](https://github.com/TUMFTM/racetrack-database) (LGPL-3.0, OpenStreetMap contributors) and [bacinger/f1-circuits](https://github.com/bacinger/f1-circuits) (MIT) — see `THIRD_PARTY_NOTICES.md` in the [SimCoach GitHub Repository](https://github.com/Jcedwar61/SimCoach).
