# The SimCoach → SimCast link

SimCoach and [SimCast](https://github.com/Jcedwar61/SimCast) are separate apps with separate releases. While
both run, SimCast lowers its commentary booth whenever SimCoach's coach or crew can be heard. This page is the
contract between them. Any SimCoach must work with any SimCast, old or new, so read it before changing either
side.

* SimCoach side: `SimCastLink` in `sim_coach.py`, tested by `tools/tests/test_simcast_link.py`.
* SimCast side: `simcast/link.py`, tested in `tools/tests/test_simcast.py`.

## Transport

* UDP datagrams to `127.0.0.1:47317`. Nothing leaves the PC.
* SimCoach sends; SimCast listens. Nothing goes the other way.
* With SimCast closed, the datagrams go nowhere. SimCoach ignores send errors.
* A datagram is at most 64 bytes of ASCII.

## Messages (link version 1)

| Datagram (exact bytes)    | Meaning                                            |
|---------------------------|----------------------------------------------------|
| `SIMCOACH-VOICE 1 talk`   | the coach, crew or a braking tone can be heard now |
| `SIMCOACH-VOICE 1 quiet`  | nothing from SimCoach can be heard                 |

Timing:

* `talk` is sent the moment a line or tone starts, then every 100 ms while it plays.
* `quiet` is sent as soon as it stops, then every 2 s as a heartbeat, so SimCast knows SimCoach is running.
* SimCast treats a `talk` as valid for 0.5 s. If SimCoach crashes mid-line, the booth comes back up by itself.
* SimCast treats SimCoach as gone after 5 s with no datagram.

## Rules for changing it

A datagram is words separated by spaces: `MAGIC VERSION STATE [more words...]`.

1. **SimCoach keeps sending the two version 1 messages above, byte for byte.** SimCast 1.1 to 1.3 compare
   whole datagrams, so anything else (another version number, an extra word) and they stop lowering the booth.
   Only change this once every supported SimCast is 1.4 or later.
2. **SimCast 1.4 and later read leniently.** The first word must be `SIMCOACH-VOICE`, the second a whole number
   ≥ 1, and the third `talk` or `quiet`. Extra words after that are ignored, and so is a higher version number:
   the booth still lowers. Anything else is ignored.
3. **Adding information:** add words after the third, and raise the version number once rule 1 allows it. Old
   readers ignore the new words.
4. **Changing what `talk` and `quiet` mean, or the word order:** use a new first word (for example
   `SIMCOACH-VOICE2`) or a new port. Old readers then ignore it rather than misread it. Keep sending version 1
   alongside it until old SimCasts are no longer supported.
5. Keep the port. Change both apps' tests whenever the wire format changes.
