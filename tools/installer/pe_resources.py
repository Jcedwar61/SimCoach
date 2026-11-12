"""Read the Windows resources (icon, manifest, version info) out of a .exe."""
import struct, sys, json
def read_resources(path):
    d = open(path, 'rb').read()
    pe = struct.unpack_from('<I', d, 0x3c)[0]
    nsec = struct.unpack_from('<H', d, pe + 6)[0]; opt = struct.unpack_from('<H', d, pe + 20)[0]
    # data directory 2 = resources (PE32+: data dirs start at opt offset 112)
    rva, size = struct.unpack_from('<II', d, pe + 24 + 112 + 8 * 2)
    secs = []
    for i in range(nsec):
        o = pe + 24 + opt + i * 40
        vsz, va, rsz, raw = struct.unpack_from('<IIII', d, o + 8); secs.append((va, max(vsz, rsz), raw))
    def r2o(r):
        for va, sz, raw in secs:
            if va <= r < va + sz: return raw + r - va
    base = r2o(rva); out = []
    def name_of(e):
        if e & 0x80000000:
            o = base + (e & 0x7fffffff); n = struct.unpack_from('<H', d, o)[0]
            return d[o + 2:o + 2 + 2 * n].decode('utf-16-le')
        return e
    def walk(off, path):
        nn, ni = struct.unpack_from('<HH', d, base + off + 12)
        for k in range(nn + ni):
            nm, ptr = struct.unpack_from('<II', d, base + off + 16 + 8 * k)
            if ptr & 0x80000000: walk(ptr & 0x7fffffff, path + [name_of(nm)])
            else:
                drva, dsz, cp, _ = struct.unpack_from('<IIII', d, base + ptr)
                out.append((path[0], path[1], name_of(nm), d[r2o(drva):r2o(drva) + dsz]))
    walk(0, []); return out
if __name__ == '__main__':
    for t, n, l, b in read_resources(sys.argv[1]): print(t, n, l, len(b))
