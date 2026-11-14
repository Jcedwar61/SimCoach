"""The guide built into SimCast (the Guide button): how to use it, set up each sim, pick voices, add AI, and fix
problems. Plain text with '## ' headings and '- ' bullets; the window formats it."""

TOPICS = [
    ("Getting started", """
## Welcome to SimCast
SimCast gives your sim race the television treatment. While you drive, a commentary booth calls the race live in your headphones: the start, overtakes, battles, pit stops, fastest laps, cars in trouble, the final lap and the finish. It covers the whole field, not just you, and it follows your race the way a broadcast follows a driver in the story.

## Three steps
- Pick where the commentary plays: Settings > Voices > Play on (your headset, or speakers). Press Test next to a commentator to hear them.
- Tell the booth your name: Settings > Commentary > Your name.
- Start a race in your sim. SimCast goes on air by itself; there's nothing to press.

## Try it now
Press Demo race at the top of the window. Twelve cars, a standing start, battles, pit stops, a spin and a retirement: the booth commentates it exactly as it would a real race. Press Stop demo to end it.

## The window
- Timing: the running order, the gap to the car ahead, PIT when a car is in the pit lane, and your car highlighted.
- The booth: everything said, with who said it. Big moments are highlighted.
- On air / Off air: silences the booth without closing SimCast. Skip cuts the current line.
- Captions window: a small always-on-top window with the line being spoken (for a second screen or OBS).
"""),
    ("What the booth covers", """
## The commentators
- The lead commentator calls the action: overtakes, the start, the finish.
- The analyst explains it: why it happened, what it means, who's quick.
- The pit-lane reporter brings you every pit stop (switch it off in Settings if you prefer two voices).

## Three kinds of coverage
SimCast picks the right one by itself and shows it at the top of the window.
- Whole field: the sim shares every car (Le Mans Ultimate, rFactor 2, iRacing, Automobilista 2, RaceRoom, F1 25, ACC, and Assetto Corsa with the CrewChiefEx app). Overtakes anywhere, battles, pit stops, the leader, the podium.
- Your car only: the sim shares just your car (AC EVO, Assetto Corsa without CrewChiefEx). The booth follows you: places gained and lost, the gap to the car ahead, pressure from behind, trips off the track, your laps and the finish.
- Rally stage: EA SPORTS WRC, DiRT Rally 2.0 and AC Rally. Splits against your best run on that stage, big moments, damage and the stage time. SimCast remembers your best run on every stage, so the comparison gets better every time.

## How it judges the race
Gaps are measured at 40 timing points a lap, like a TV timing system. A place lost in the pits, to a stopped car or through lapped traffic isn't called an overtake. Stale stories are dropped: if three things happen at once, the biggest one is called and the others are summed up.
"""),
    ("Setting up your sim", """
## SimCast finds your sims
When it starts, SimCast looks for the supported sims installed on this PC (every Steam library, iRacing's own folder, and EA app installs of F1 25 and EA SPORTS WRC) and lists them on the start screen and in Settings > Sims: a green tick when a sim is ready, or the one thing still to do. Press Scan again in Settings > Sims after installing a sim.

## Nothing to do
- Le Mans Ultimate, rFactor 2, RaceRoom, AC Rally, AC EVO: just drive.
- iRacing: just drive (iRacing shares every car's position and lap times).

## Set once in the game
- Automobilista 2: Options > System > Shared Memory = "Project CARS 2".

## SimCast sets these up for you
- ACC: SimCast switches on ACC's broadcasting port (in Documents\\Assetto Corsa Competizione\\Config\\broadcasting.json) to see the whole grid. If ACC was running when this happened, restart ACC once.
- EA SPORTS WRC: SimCast adds its telemetry packet to the game's telemetry settings (Documents\\My Games\\WRC\\telemetry). Restart the game once if it was running.
- DiRT Rally 2.0: SimCast switches on UDP telemetry with the extra data (hardware_settings_config.xml). Restart the game once if it was running.
- F1 25: SimCast switches on UDP telemetry (port 20777) once the game has been started once. F1 also sends its own events (collisions, penalties, safety car), which SimCast commentates. In online races, the game's "Your Telemetry" and "Show online names" settings decide what other players' cars show.
- Assetto Corsa: SimCast switches on the CrewChiefEx app when CrewChief has installed it (see below).
Anything SimCast changes is backed up next to the original as .simcast-backup. Switch this off in Settings > Sims.

## Assetto Corsa
To see the other cars, SimCast uses the CrewChiefEx Python app, which comes with CrewChief. When it's installed, SimCast switches it on for you; you can also do it in Content Manager > Settings > Assetto Corsa > Python apps. Without it, SimCast covers your car only.

## SimHub and SimCoach
SimCast can run next to SimHub and SimCoach. On UDP port 20777 (F1 25, DiRT Rally 2.0) it shares the port when SimHub listens on all addresses, and it also listens on 20778 (F1) and 20779 (DiRT Rally 2.0) as a fallback.

## Not supported
NASCAR 25, NASCAR Heat 5, Project Motor Racing, WRC Generations, KartKraft and BeamNG.drive don't share live data SimCast can read. SimCast says so at the top of the window instead of waiting.
"""),
    ("Voices and sound", """
## Where it plays
Settings > Voices > Play on lists your playback devices: headset, speakers, a VR headset. Pick one and press Test. "Windows default" follows whatever Windows uses.

## Choosing voices
Each commentator has their own voice. All of these are free except OpenAI:
- Microsoft neural voices: natural, quick, need the internet. The default.
- Kokoro: high-quality neural voices that run on your PC, no internet after a one-time download (about 115 MB, done in the background the first time you use one).
- Google: simple and reliable, need the internet.
- OpenAI: the most lifelike. Every line is spoken with its own direction (calm, excited, thrilled). Uses your OpenAI key and costs a little per line.
Excitement comes through in every voice: bigger moments are faster, higher and louder.

## If a voice can't be reached
The booth never goes silent: a line the chosen voice can't speak (no internet, no key) is spoken by Kokoro, then Google, then Windows' own voice. The bottom of the window says when that happens.

## Speed and volume
Settings > Voices: Volume, and Speed (how briskly the booth talks).
"""),
    ("AI commentary", """
## What it adds
Without AI, the booth calls every moment from its own lines, instantly. With an AI key:
- the analyst reacts to big moments with real analysis of the race data,
- quiet spells become a natural conversation between the two commentators about the stories in the race,
- there's a proper sign-off at the end.
The AI gets the live standings, gaps, lap times, battles and recent events, and strict rules: only facts from the data, nothing invented, no repeats.

## Keys
Settings > AI: add a key for OpenAI, Google Gemini or DeepSeek (or more than one). Keys stay on your PC (in %APPDATA%\\SimCast\\config.json) and are never shown again. Get one at:
- OpenAI: platform.openai.com/api-keys
- Google Gemini: aistudio.google.com/apikey
- DeepSeek: platform.deepseek.com/api_keys
Have SimCoach? "Copy keys from SimCoach" copies them over (SimCast doesn't need SimCoach otherwise).

## Models
Leave Model on Automatic. SimCast asks the provider which models your key can use and picks the best one for live commentary (quick replies that still read naturally). You can pick another from the list. With more than one key, SimCast moves to another provider if one is down or out of credit.

## Cost
A race of about 30 minutes makes a few dozen short requests. With OpenAI voices on as well, each spoken line is a small speech request too.
"""),
    ("Settings", """
## Commentary
- How chatty: Quiet waits longer before filling a silence, Chatty fills it quickly. Big moments are always called.
- Follow: Whole field is a neutral broadcast. Balanced (the default) makes your race one of the stories. Mostly me keeps the focus on you.
- Your name: how the booth says it. Empty: the name your sim uses.
- Pit-lane reporter: a third voice for pit stops.

## Voices
Names and voices of the three commentators, Play on (the sound device), Volume and Speed.

## AI
AI commentary on or off, the provider to use first, keys, and the model (Automatic is best).

## Sims
- Set up games automatically (EA WRC, DiRT Rally 2.0, ACC).
- F1 25 port, and sharing UDP port 20777 with SimHub.

Settings are saved in %APPDATA%\\SimCast\\config.json.
"""),
    ("Streaming and captions", """
## Captions window
Tick Captions window at the bottom of SimCast's window. A small window shows each line as it's spoken, with who said it. It stays on top: drag it where you want it, right-click to close it.

## In OBS
Add a Window Capture of "SimCast captions" (or of the SimCast window for the timing tower). Use a colour key on the dark background if you want it transparent.

## Commentary audio on stream
SimCast plays on the device picked in Settings > Voices > Play on. Add that device (or an application audio capture of SimCast) to OBS to put the booth on your stream.
"""),
    ("Linux and Steam Deck (Wine/Proton)", """
## How it works
On Linux, sims run in Wine or Proton, and they share their data inside their own Wine prefix. SimCast has to run in the same prefix as the game to see it.

## Install
Run install-simcast-wine.sh (in the SimCast download) with the game's Steam app id or prefix. It opens the normal SimCast setup wizard inside the game's prefix (add --silent to skip it):
- ./install-simcast-wine.sh --game lmu
- ./install-simcast-wine.sh --appid 2399420
- ./install-simcast-wine.sh --prefix ~/.wine
It installs SimCast into that prefix with the Windows installer, and makes a launcher, simcast-<game>.sh, which starts SimCast in the same prefix and with the same Proton as the game. Start the game first, then SimCast.

## Voices under Wine
The Microsoft, Google and OpenAI voices work under Wine and Proton. The Kokoro voices are off there: the maths library they need can crash some Wine versions. If yours handles it, set SIMCAST_WINE_KOKORO=1 in the launcher script to switch them on.

## UDP sims
F1 25, EA WRC and DiRT Rally 2.0 send UDP, which works between any prefix; the launcher still runs SimCast with the game's Proton.
"""),
    ("Troubleshooting", """
## No sound
- Settings > Voices > Play on: pick your headset and press Test.
- The bottom of the window says if a voice service couldn't be reached; the booth then uses Kokoro, Google or Windows' own voice.
- On air must be on (the button at the top).

## "Waiting for a sim"
- The start screen lists the sims SimCast found and what each still needs.
- The game must be running and in a session (not the menus).
- Automobilista 2 needs Shared Memory = Project CARS 2; F1 25 needs UDP telemetry on.
- EA WRC, DiRT Rally 2.0 and ACC: restart the game once after SimCast first set it up.

## Only my car is covered
- Assetto Corsa: install CrewChief (for its CrewChiefEx app); SimCast switches the app on. Restart AC once.
- ACC: restart ACC once after SimCast switched on its broadcasting port.
- AC EVO shares only your car.

## AI isn't talking
Settings > AI shows the model in use and the last problem (wrong key, no credit, no internet). The booth carries on with its own lines.

## The log
%APPDATA%\\SimCast\\simcast.log has what SimCast did and anything that went wrong. Settings > About > Open log folder.
"""),
]
