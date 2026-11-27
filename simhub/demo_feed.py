"""Plays a made-up SimCoach session into the SimHub plugin, so you can look at (or design) the SimCoach dashboard
without SimCoach or a sim running. Close SimCoach first: both send to the same port.

    python simhub/demo_feed.py            # until Ctrl+C
    python simhub/demo_feed.py --secs 30

It also prints the button presses the dashboard sends back (SimCoach.Repeat, .Mute, ...)."""
import argparse
import json
import math
import socket
import time

FEED, CMD = ("127.0.0.1", 47318), ("127.0.0.1", 47319)
CALLS = ["Turn 5, 3 tenths lost. You braked 15 metres early.",
         "Lap 7, 1:49.212. Two tenths off your best. Work on turn 3: carry more speed to the apex.",
         "Turn 3, nicely done. That's a tenth found.",
         "Car behind, 0.8 seconds and closing.",
         "Fuel's fine: about 14 laps in the tank."]


def lap(s):
    m, r = divmod(s, 60)
    return f"{int(m)}:{r:06.3f}"


def snapshot(t, state):
    k = int(t // 12) % len(CALLS)
    delta = 0.45 * math.sin(t / 4.0) - 0.05
    laps = [109.912, 109.604, 110.380, 109.212, 109.455, 112.902, 109.318]
    best = min(laps)
    return {
        "magic": "SIMCOACH-SIMHUB", "v": 1, "seq": int(t * 10), "version": "6.22", "running": True, "live": True,
        "driver": "Demo", "sim": "ACC", "track": "Spa-Francorchamps", "car": "Porsche 992 GT3 R",
        "status": "ACC · Spa-Francorchamps · Porsche 992 GT3 R · practice",
        "delta_s": round(delta, 2), "delta_text": f"{delta:+.2f}",
        "coach": CALLS[k], "coach_age": round(t % 12, 1),
        "focus": "Turn 3: carry more speed to the apex  ·  Turn 5: brake later",
        "goal": "Today's goal  ·  Turn 5: 0.18s a lap quicker so far   ·   Turn 12: lost 0.21s a lap there last session",
        "heard": "You: how consistent am I?" if t % 60 > 40 else None,
        "heard_age": round(t % 60 - 40, 1) if t % 60 > 40 else None,
        "talking": t % 12 < 3, "muted": state["muted"], "tones": "off" if state["tones_off"] else "focus",
        "mic": "listening" if 40 < t % 60 < 42 else "ready",
        "lap": len(laps) + 1, "laps_done": len(laps), "last_s": laps[-1], "last": lap(laps[-1]),
        "best_s": best, "best": lap(best), "theo_s": 108.64, "theo": lap(108.64),
        "target_s": 106.4, "target": lap(106.4), "pace_pct": round(100 * best / 106.4, 2),
        "cons_sd": 0.29, "cons_label": "consistent",
        "pos": 4, "cars": 22, "gap_ahead": 1.4 - 0.02 * (t % 30), "gap_behind": 0.8, "fuel": "38.5 L",
        "fuel_laps": 14, "speed": int(180 + 90 * math.sin(t / 3)), "gear": 4 + int(2 * math.sin(t / 3)),
        "focus_turns": [3, 5], "drill": None,
        "goals": [{"turn": 5, "change": -0.18, "laps": 4, "done": True, "last_loss": 0.32},
                  {"turn": 12, "change": 0.04, "laps": 4, "done": False, "last_loss": 0.21}],
        "corners": [{"turn": i, "loss": round(0.05 * ((i * 7) % 5), 2), "issue": None} for i in range(1, 20)],
        "worst": [{"turn": 5, "loss": 0.31, "issue": "braked 15 m early"},
                  {"turn": 12, "loss": 0.22, "issue": "slow on the exit"},
                  {"turn": 3, "loss": 0.14, "issue": "apex speed 6 km/h low"},
                  {"turn": 18, "loss": 0.09, "issue": "lifted in the fast bit"}],
        "laps": [{"n": n, "time": lap(s), "s": s, "gap": round(s - best, 3), "pit": False, "invalid": n == 6}
                 for n, s in enumerate(laps, 1)],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--secs", type=float, default=0)
    a = ap.parse_args()
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        rx.bind(CMD)
        rx.settimeout(0.1)
    except OSError:
        print("Port 47319 is busy (is SimCoach open?): button presses won't be shown.")
        rx = None
    state = {"muted": False, "tones_off": False}
    t0 = time.monotonic()
    print("Sending a demo SimCoach session to SimHub. Ctrl+C to stop.")
    while not a.secs or time.monotonic() - t0 < a.secs:
        tx.sendto(json.dumps(snapshot(time.monotonic() - t0, state)).encode("utf-8"), FEED)
        if rx is None:
            time.sleep(0.1)
            continue
        try:
            msg = rx.recvfrom(256)[0].decode("ascii", "replace")
            print("Button from SimHub:", msg)
            if msg.endswith(" mute"):
                state["muted"] = not state["muted"]
            elif msg.endswith(" tones"):
                state["tones_off"] = not state["tones_off"]
        except socket.timeout:
            pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
