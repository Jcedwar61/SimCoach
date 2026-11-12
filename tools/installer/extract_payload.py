"""List or extract the files bundled inside SimCoach-Setup.exe (Go's embedded file table).

    python extract_payload.py SimCoach-Setup.exe            # list
    python extract_payload.py SimCoach-Setup.exe OUT_DIR    # extract to OUT_DIR/payload/...
"""
import os
import struct
import sys


def payload(exe_path):
    d = open(exe_path, "rb").read()
    pe = struct.unpack_from("<I", d, 0x3c)[0]
    nsec = struct.unpack_from("<H", d, pe + 6)[0]
    opt = struct.unpack_from("<H", d, pe + 20)[0]
    base = struct.unpack_from("<Q", d, pe + 24 + 24)[0]
    secs = []
    for i in range(nsec):
        o = pe + 24 + opt + i * 40
        vsz, va, rsz, raw = struct.unpack_from("<IIII", d, o + 8)
        secs.append((base + va, vsz, raw, rsz))

    def v2o(v):
        for va, vsz, raw, rsz in secs:
            if va <= v < va + max(vsz, rsz):
                return raw + (v - va)

    def o2v(o):
        for va, vsz, raw, rsz in secs:
            if raw <= o < raw + rsz:
                return va + (o - raw)
    nm = b"payload/install.ps1"          # find one name, then the 48-byte table entries around it
    h = d.find(struct.pack("<QQ", o2v(d.find(nm)), len(nm)))
    start = h
    while True:
        p, ln = struct.unpack_from("<QQ", d, start - 48)
        o = v2o(p) if p else None
        if o is None or not (0 < ln < 300) or not d[o:o + ln].startswith(b"payload"):
            break
        start -= 48
    out, i = [], start
    while True:
        p, ln, dp, dl = struct.unpack_from("<QQQQ", d, i)
        o = v2o(p) if p else None
        if o is None or not (0 < ln < 300) or not d[o:o + ln].startswith(b"payload"):
            break
        name = d[o:o + ln].decode()
        if not name.endswith("/"):
            out.append((name, d[v2o(dp):v2o(dp) + dl] if dl else b""))
        i += 48
    return out


if __name__ == "__main__":
    files = payload(sys.argv[1])
    for name, data in files:
        print(f"{len(data):>10}  {name}")
        if len(sys.argv) > 2:
            path = os.path.join(sys.argv[2], name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "wb").write(data)
