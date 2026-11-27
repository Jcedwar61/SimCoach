# The SimCoach → SimHub link

SimCoach feeds SimHub dashboards through SimCoach's own SimHub plugin. This page is the contract between them.

* SimCoach side: `SimHubLink`, `App._simhub_data` and `App._simhub_do` in `sim_coach.py`, tested by
  `tools/tests/test_simhub_link.py` and `tools/tests/gui_test_app.py`.
* Plugin side: `simhub/plugin/SimCoachPlugin.cs`.

## Transport

* Feed: UDP datagrams from SimCoach to `127.0.0.1:47318`, every 100 ms while SimCoach is open and *Send coaching
  to SimHub dashboards* is ticked. With SimHub closed they go nowhere; SimCoach ignores send errors.
* Buttons: UDP datagrams from the plugin to `127.0.0.1:47319`. SimCoach binds that port on 127.0.0.1 only and
  ignores datagrams from any other address.
* Nothing leaves the PC. 47317 is the SimCast link; don't reuse it.

## Feed (link version 1)

One UTF-8 JSON object per datagram, at most 8000 bytes. If a snapshot would be bigger, SimCoach drops `corners`,
then `laps`, then `goals` (never the live values).

| Key | Type | Meaning |
|---|---|---|
| `magic` | `"SIMCOACH-SIMHUB"` | always first; the plugin ignores anything else |
| `v` | int ≥ 1 | link version |
| `seq` | int | counts up per datagram |
| `version`, `driver` | str | SimCoach version, driver name |
| `running`, `live` | bool | coaching started · a sim is sending telemetry |
| `sim`, `track`, `car`, `status` | str / null | session and the Live tab's headline |
| `delta_s`, `delta_text` | float / null, str | delta to the reference in seconds; `"--.--"` when there's none |
| `coach`, `coach_age` | str / null, float / null | the coach's last call and seconds since it changed |
| `focus`, `goal`, `heard`, `heard_age` | str / null | the Live tab's focus and goal lines; what push-to-talk heard |
| `talking`, `muted`, `tones`, `mic` | bool, bool, str, str / null | audible now · talk level 0 · `brake_callouts` · listener state |
| `lap`, `laps_done` | int | current lap · laps in history |
| `last`/`last_s`, `best`/`best_s`, `theo`/`theo_s`, `target`/`target_s` | `"m:ss.fff"` / float | lap times |
| `pace_pct`, `cons_sd`, `cons_label` | float, float, str | best lap as % of target · spread of clean laps |
| `pos`, `cars`, `gap_ahead`, `gap_behind`, `fuel`, `fuel_laps`, `speed`, `gear` | | race and car (as on the phone screen) |
| `focus_turns` | [int] | focus corners' turn numbers |
| `drill` | `{turn, lap, of}` / null | a corner drill in progress |
| `goals` | `[{turn, change, laps, done, last_loss}]` | goals from last session; `change` < 0 = quicker |
| `corners` | `[{turn, loss, issue}]` | every corner, last lap's loss against your best there |
| `worst` | up to 5 of `corners` | biggest loss first, losses > 0 only |
| `laps` | up to 8 `[{n, time, s, gap, pit, invalid}]` | recent laps, oldest first |

A missing key and `null` mean the same: not known right now.

## Buttons

ASCII words separated by spaces: `SIMCOACH-CMD <version> <action> [arg]`.

| Datagram | Does |
|---|---|
| `SIMCOACH-CMD 1 repeat` | repeat the last call |
| `SIMCOACH-CMD 1 mute` | mute / unmute the coach |
| `SIMCOACH-CMD 1 tones` | braking tones on / off |
| `SIMCOACH-CMD 1 overlay` | show / hide the overlay |
| `SIMCOACH-CMD 1 sheet` | show / hide the setup sheet |
| `SIMCOACH-CMD 1 capture` | start / stop a data capture |
| `SIMCOACH-CMD 1 ptt down` / `ptt up` | push-to-talk pressed / released |

Only these. Anything else is ignored, so a dashboard can never reset references, change the car's setup or
change settings beyond these toggles.

## Rules for changing it

1. **Adding a feed key is always fine**: the plugin ignores keys it doesn't know. Add a property for it in the
   plugin, and a row above.
2. **Never change a key's meaning or type.** Add a new key instead and keep sending the old one while plugins
   that read it are in use.
3. Readers accept any `v` ≥ 1. Raise `v` when a release adds something a plugin may want to check for.
4. **New button actions**: add them to `SIMHUB_COMMANDS` in `sim_coach.py` and to the table above. Older
   SimCoaches ignore actions they don't know; extra words after the action are ignored too.
5. Keep the ports. Change the tests on both sides whenever the format changes.
