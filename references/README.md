# SimCoach reference library

Reference laps shared by SimCoach drivers. The first time you drive a sim / track / car combination with no lap of
your own, SimCoach looks here for a lap with **exactly** that sim, track and car, downloads it and coaches you
against it, until you beat it and your own lap takes over. Turn it off in Settings ("Use reference laps from the
SimCoach library").

SimCoach also imports new laps from here automatically: at start-up, every 12 hours, and with **References →
Update from library**. A lap that's replaced here with a faster one is updated on every driver's PC. A driver's
own lap for a combination is never replaced.

## Adding a lap

1. Drive a clean, quick lap. SimCoach saves it as your reference.
2. In SimCoach: **References** tab, select the lap, **Share to library…**. That saves a copy in
   `Documents\SimCoach Reports\Library uploads` and opens this folder's upload page on GitHub.
3. Drag the file onto the page and commit. People without write access to this repository get a
   "propose changes" pull request instead, for the owner to approve.

Only share laps you drove yourself. A file holds the sim, track and car names and the lap trace (speed, pedals,
corner data): no driver name, settings or keys.

## File rules (checked by `tools/references/check_library.py`)

- The file name is the reference's own name: `<sim>__<track>__<car>.json`, as SimCoach saves it.
- It must be a complete, clean lap (not provisional) for the sim / track / car in its name.
- Under 3 MB.

One file per combination: a quicker lap for the same combination replaces the file.
