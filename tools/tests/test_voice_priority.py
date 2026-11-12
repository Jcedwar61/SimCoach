"""Speech priority: urgent calls cut crew banter short; everything else behaves as before."""
import time

from _common import check, done, load

sc = load()
v = sc.Voice(sc.load_config(), enabled=False)


def case(kind, queued, spot_waiting=False, hold=False):
    with v.q.mutex:
        v.q.queue.clear()
    while not v.spot_q.empty():
        v.spot_q.get_nowait()
    v.preempt.clear()
    v.hold.clear()
    v._item = ("line", kind, time.monotonic(), None)
    for k in queued:
        v.q.put(("x", k, time.monotonic(), None))
    if spot_waiting:
        v.spot_q.put(("Car left.", "spot", time.monotonic(), None))
        v.preempt.set()
    if hold:
        v.hold.set()
    return v._must_stop(kind == "spot")


check(case("chat", ["urgent"]) is True, "banter + urgent queued -> stop")
check(case("chat", ["info"]) is False, "banter + routine line queued -> keep")
check(case("chat", []) is False, "banter alone -> keep")
check(case("info", ["urgent"]) is False, "coach line + urgent queued -> keep")
check(case("answer", ["urgent"]) is False, "answer + urgent queued -> keep")
check(case("info", [], spot_waiting=True) is True, "spotter waiting -> stop")
check(case("chat", [], spot_waiting=True) is True, "banter + spotter waiting -> stop")
check(case("info", [], hold=True) is True, "push-to-talk held -> stop")
check(case("spot", ["urgent"]) is False, "spotter line keeps going")
done()
