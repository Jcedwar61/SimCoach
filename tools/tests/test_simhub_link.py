"""SimHub link: ten times a second SimCoach sends its SimHub plugin one JSON datagram (127.0.0.1) with what the
coach knows, and takes a short list of harmless button presses back. See docs/simhub-link.md."""
import json
import socket
import time

from _common import check, done, load

sc = load()

check(sc.SIMHUB_LINK_PORT == 47318 and sc.SIMHUB_CMD_PORT == 47319, "the ports the SimHub plugin uses")
check(sc.SIMHUB_LINK_PORT != sc.SIMCAST_LINK_PORT, "doesn't collide with the SimCast link")

rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
rx.bind(("127.0.0.1", 0))
rx.settimeout(1.0)
snap = {"live": True, "delta_s": -0.31, "delta_text": "-0.31", "coach": "Turn 5, braked 15 metres early.",
        "corners": [{"turn": i, "loss": 0.1, "issue": "x" * 40} for i in range(1, 20)]}
got_cmds = []
link = sc.SimHubLink(lambda: dict(snap), lambda a, b=None: got_cmds.append((a, b)),
                     port=rx.getsockname()[1], cmd_port=0, log=lambda m: None, start=False)

link.send()
d = json.loads(rx.recvfrom(65535)[0].decode("utf-8"))
check(d["magic"] == "SIMCOACH-SIMHUB" and d["v"] == 1 and d["seq"] == 1, "datagram starts with magic, version, seq")
check(d["delta_s"] == -0.31 and d["coach"].startswith("Turn 5") and len(d["corners"]) == 19, "snapshot carried")
link.send()
check(json.loads(rx.recvfrom(65535)[0])["seq"] == 2, "sequence number counts up")

snap["corners"] = [{"turn": i, "loss": 0.1, "issue": "y" * 200} for i in range(200)]
raw = link.packet()
check(len(raw) <= link.MAX_BYTES and b'"corners"' not in raw and b'"delta_s"' in raw,
      "an oversized snapshot drops the long lists, never the live values")

P = sc.SimHubLink.parse_command
check(P(b"SIMCOACH-CMD 1 repeat") == ("repeat", None), "repeat")
check(P(b"SIMCOACH-CMD 1 MUTE\n") == ("mute", None), "case and trailing newline don't matter")
check(P(b"SIMCOACH-CMD 1 ptt down") == ("ptt", "down") and P(b"SIMCOACH-CMD 1 ptt up") == ("ptt", "up"),
      "push-to-talk press and release")
check(P(b"SIMCOACH-CMD 2 tones extra words") == ("tones", None), "a later version's extra words are ignored")
for bad in (b"SIMCOACH-CMD 1 reset_reference", b"SIMCOACH-CMD 1 ptt", b"SIMCOACH-CMD 0 mute",
            b"SIMCOACH-VOICE 1 talk", b"SIMCOACH-CMD x mute", b"\xff\xfe", b"", b"SIMCOACH-CMD 1"):
    check(P(bad) is None, f"rejected: {bad!r}")

# a real round trip through the command socket, from this PC
port = link.rx.getsockname()[1]
tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
tx.sendto(b"SIMCOACH-CMD 1 overlay", ("127.0.0.1", port))
tx.sendto(b"SIMCOACH-CMD 1 format_disk", ("127.0.0.1", port))
tx.sendto(b"SIMCOACH-CMD 1 ptt down", ("127.0.0.1", port))
t0 = time.monotonic()
while len(got_cmds) < 2 and time.monotonic() - t0 < 2:
    link._listen()
check(got_cmds == [("overlay", None), ("ptt", "down")], "button presses reach SimCoach; unknown ones don't")

check(sc._clock(83.4567) == "1:23.457" and sc._clock(59.9994) == "59.999" and sc._clock(None) is None
      and sc._clock(0) is None, "lap times written for a dashboard")
link.stop()
check(link.rx is None and link.tx is None, "stop closes both sockets")
link.send()                                     # after stop: silently nothing
done()
