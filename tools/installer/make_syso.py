"""Write installer-source/rsrc_windows_amd64.syso (icon, manifest, version info) for a new version, copying the
resources of an existing SimCoach-Setup.exe and replacing its version.

    python make_syso.py SimCoach-Setup.exe ../../installer-source/rsrc_windows_amd64.syso 6.4
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pe_resources import read_resources  # noqa: E402


def four(v):
    n = [int(x) for x in v.split(".")][:4]
    return n + [0] * (4 - len(n))


def main(src_exe, out, version):
    new = four(version)
    res = read_resources(src_exe)
    fixed = []
    for t, n, lang, b in res:
        if t == 16:                                   # VS_VERSIONINFO
            i = b.find(struct.pack("<I", 0xFEEF04BD))
            ms, ls = struct.unpack_from("<II", b, i + 8)
            old = f"{ms >> 16}.{ms & 0xffff}.{ls >> 16}.{ls & 0xffff}"
            b = b.replace(old.encode("utf-16-le"), ".".join(map(str, new)).encode("utf-16-le"))
            vv = struct.pack("<II", (new[0] << 16) | new[1], (new[2] << 16) | new[3])
            b = b[:i + 8] + vv + vv + b[i + 24:]
        fixed.append((t, n, lang, b))
    tree = {}
    for t, n, lang, b in fixed:
        tree.setdefault(t, {}).setdefault(n, {})[lang] = b
    size_dir = lambda k: 16 + 8 * k
    off = 0
    root_off = off
    off += size_dir(len(tree))
    type_off, name_off, entry_off, data_off = {}, {}, {}, {}
    for t in sorted(tree):
        type_off[t] = off
        off += size_dir(len(tree[t]))
    for t in sorted(tree):
        for n in sorted(tree[t]):
            name_off[(t, n)] = off
            off += size_dir(len(tree[t][n]))
    for t in sorted(tree):
        for n in sorted(tree[t]):
            for lang in sorted(tree[t][n]):
                entry_off[(t, n, lang)] = off
                off += 16
    for t in sorted(tree):
        for n in sorted(tree[t]):
            for lang in sorted(tree[t][n]):
                off = (off + 7) & ~7
                data_off[(t, n, lang)] = off
                off += len(tree[t][n][lang])
    size = (off + 7) & ~7
    buf = bytearray(size)

    def put_dir(at, children):
        struct.pack_into("<IIHHHH", buf, at, 0, 0, 0, 0, 0, len(children))
        for k, (cid, tgt, isdir) in enumerate(children):
            struct.pack_into("<II", buf, at + 16 + 8 * k, cid, tgt | (0x80000000 if isdir else 0))
    put_dir(root_off, [(t, type_off[t], True) for t in sorted(tree)])
    relocs = []
    for t in sorted(tree):
        put_dir(type_off[t], [(n, name_off[(t, n)], True) for n in sorted(tree[t])])
        for n in sorted(tree[t]):
            put_dir(name_off[(t, n)], [(lang, entry_off[(t, n, lang)], False) for lang in sorted(tree[t][n])])
            for lang in sorted(tree[t][n]):
                e, b = entry_off[(t, n, lang)], tree[t][n][lang]
                struct.pack_into("<IIII", buf, e, data_off[(t, n, lang)], len(b), 0, 0)
                relocs.append(e)                     # data RVA, relocated against the .rsrc section
                buf[data_off[(t, n, lang)]:data_off[(t, n, lang)] + len(b)] = b
    raw_ptr = 20 + 40
    reloc_ptr = raw_ptr + size
    sym_ptr = reloc_ptr + 10 * len(relocs)
    o = bytearray(struct.pack("<HHIIIHH", 0x8664, 1, 0, sym_ptr, 2, 0, 0))
    o += struct.pack("<8sIIIIIIHHI", b".rsrc", 0, 0, size, raw_ptr, reloc_ptr, 0, len(relocs), 0, 0x40000040)
    o += buf
    for r in relocs:
        o += struct.pack("<IIH", r, 0, 3)            # IMAGE_REL_AMD64_ADDR32NB
    o += struct.pack("<8sIhHBB", b".rsrc", 0, 1, 0, 3, 1)
    o += struct.pack("<IHHIHBBBBH", size, len(relocs), 0, 0, 0, 0, 0, 0, 0, 0)[:18]
    o += struct.pack("<I", 4)
    open(out, "wb").write(o)
    print(f"wrote {out}: version {'.'.join(map(str, new))}, {len(relocs)} resources")


if __name__ == "__main__":
    main(*sys.argv[1:4])
