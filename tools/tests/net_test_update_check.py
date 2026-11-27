"""Update check against the real GitHub API (needs internet): version comparison, offers, installer download."""
import os
import tempfile

from _common import check, done, load

sc = load()
V = sc._ver_tuple
check(V("v6.2.1") > V("6.2") > V("v6.1") and V("6.10") > V("6.9") and V("v6.2") == V("6.2.0"), "version comparison")
latest = sc.check_latest_release
sc.APP_VERSION = "0.1"
info = latest()
check(info is not None and info["installer_url"].endswith("SimCoach-Setup.exe"), f"an old copy is offered {info and info['version']}")
check(info["installer_sha256"] and len(info["installer_sha256"]) == 64, "with the installer's published checksum")
real = info["tag"]
sc.APP_VERSION = real.lstrip("vV")
check(latest() is None, f"{real} itself is up to date")
sc.APP_VERSION = "999.0"
check(latest() is None, "a newer-than-released copy is up to date")
d = tempfile.mkdtemp()
dest = os.path.join(d, "SimCoach-Setup.exe")
sc.download_installer(info["installer_url"], dest, info["installer_sha256"])
check(open(dest, "rb").read(2) == b"MZ" and os.path.getsize(dest) > 1_000_000, "installer downloads and is a Windows program")
try:
    sc.download_installer(info["installer_url"], os.path.join(d, "x.exe"), "0" * 64)
    check(False, "a checksum mismatch is rejected")
except ValueError:
    check(not os.path.exists(os.path.join(d, "x.exe")), "a checksum mismatch is rejected and nothing is kept")
try:
    sc.download_installer(info["installer_url"], os.path.join(d, "y.exe"), None)
    check(False, "no checksum, no download")
except ValueError:
    check(True, "no checksum, no download")
try:
    sc.download_installer(f"https://github.com/{sc.UPDATE_REPO}", os.path.join(d, "bad.exe"), "0" * 64)
    check(False, "a web page is rejected")
except ValueError:
    check(not os.path.exists(os.path.join(d, "bad.exe.part")), "a web page is rejected and cleaned up")
done()
