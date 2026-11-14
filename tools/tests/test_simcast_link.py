"""SimCast link: while the coach or crew can be heard, SimCoach tells SimCast (UDP on 127.0.0.1) so its TV
booth drops under the coach; 'quiet' when it stops, and a 'quiet' heartbeat every 2 s so SimCast knows it's there."""
import socket
import time

from _common import check, done, load

sc = load()
v = sc.Voice(sc.load_config(), enabled=False)
rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
rx.bind(("127.0.0.1", 0))
rx.settimeout(0.5)
link = sc.SimCastLink(v, port=rx.getsockname()[1], start=False)


def got():
    out = []
    rx.settimeout(0.2)
    try:
        while True:
            out.append(rx.recvfrom(64)[0])
    except socket.timeout:
        return out


check(sc.SIMCAST_LINK_PORT == 47317 and v.link is link, "the link is on the port SimCast listens on")
link.step()
check(got() == [link.QUIET], "quiet heartbeat while nothing plays")
link.step()
check(got() == [], "no heartbeat again within 2 s")
v._on_air(True)
check(got() == [link.TALK], "a line starting tells SimCast at once")
link.step()
check(got() == [link.TALK] and v.audible(), "keeps saying 'talking' while the line plays")
v._on_air(False)
link.step()
check(got() == [link.QUIET] and not v.audible(), "'quiet' as soon as the line ends")
v.enabled = True
v._mixer = False
sc.beep = lambda f, ms: None
v.tone(880, 150)
during = v.audible()
check(got() == [link.TALK] and during, "a braking tone counts as the coach talking")
time.sleep(0.05)
check(not v.audible(), "the tone is over after its length")
done()
