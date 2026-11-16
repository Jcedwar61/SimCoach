"""Kokoro voice model shared with SimCast: when SimCast already downloaded it, SimCoach links (or copies) SimCast's
files instead of downloading ~115 MB again; a missing or cut-short SimCast copy means a normal download."""
import os

from _common import check, done, load

sc = load()
v = sc.Voice(sc.load_config(), enabled=False, log=lambda m: None)
kdir, mpath, vpath = v._kokoro_paths()
cast = os.path.join(os.path.dirname(sc.APP_DIR), "SimCast", "kokoro")
os.makedirs(cast, exist_ok=True)


def fake(path, size):
    with open(path, "wb") as fh:          # sparse: the size checks pass without writing 115 MB
        fh.truncate(size)


urls = []


class NoNet:
    def __init__(self, req, timeout=None):
        urls.append(req.full_url)
        raise OSError("no network in this test")


import urllib.request
urllib.request.urlopen = NoNet

# nothing from SimCast yet: a normal download is tried (and fails here, no network)
v._kokoro_download()
check(len(urls) == 1 and not os.path.exists(mpath), "no SimCast copy: downloads as before")

# SimCast has both files: nothing downloaded, both in place, SimCast's copies untouched
fake(os.path.join(cast, "kokoro-v1.0.int8.onnx"), 60_000_000)
fake(os.path.join(cast, "voices-v1.0.bin"), 27_000_000)
urls.clear()
v._kokoro_download()
check(urls == [] and os.path.getsize(mpath) == 60_000_000 and os.path.getsize(vpath) == 27_000_000,
      "SimCast's model files used, nothing downloaded")
check(not os.path.exists(mpath + ".part") and not os.path.exists(vpath + ".part"), "no .part files left over")
os.remove(mpath)
check(os.path.exists(os.path.join(cast, "kokoro-v1.0.int8.onnx")), "removing SimCoach's copy leaves SimCast's")

# a cut-short SimCast copy is not borrowed
os.remove(vpath)
fake(os.path.join(cast, "voices-v1.0.bin"), 1000)
urls.clear()
v._kokoro_download()
check(os.path.exists(mpath) and not os.path.exists(vpath) and urls and urls[0].endswith("voices-v1.0.bin"),
      "a cut-short SimCast copy is downloaded instead")
done()
