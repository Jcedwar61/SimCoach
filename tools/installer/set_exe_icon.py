"""Put an .ico's images into a Windows .exe as its icon (the one Explorer and the taskbar show), in place.

    python tools/installer/set_exe_icon.py SimCoach.exe SimCoach.ico

Works when the resource section (.rsrc) is the last section of the file, as in SimCoach.exe: the new images are
added at the end of that section and the icon entries pointed at them; the program code isn't touched. Refuses a
signed .exe (a signature would no longer match). Needs pefile (pip install pefile).
"""
import struct
import sys

import pefile


def align(x, a):
    return (x + a - 1) // a * a


def read_ico(path):
    raw = open(path, "rb").read()
    _res, typ, count = struct.unpack_from("<HHH", raw, 0)
    if typ != 1:
        raise ValueError("not an .ico file")
    out = []
    for i in range(count):
        w, h, colors, _r, planes, bpp, size, off = struct.unpack_from("<BBBBHHII", raw, 6 + 16 * i)
        out.append((w, h, colors, planes, bpp, raw[off:off + size]))
    return out


def main(exe, ico):
    pe = pefile.PE(exe)
    opt = pe.OPTIONAL_HEADER
    if opt.DATA_DIRECTORY[4].Size:
        sys.exit("the .exe is signed: changing its icon would break the signature")
    rsrc = next(s for s in pe.sections if s.Name.rstrip(b"\0") == b".rsrc")
    if rsrc is not max(pe.sections, key=lambda s: s.PointerToRawData) or \
            rsrc is not max(pe.sections, key=lambda s: s.VirtualAddress):
        sys.exit(".rsrc isn't the last section: not supported")
    if rsrc.PointerToRawData + rsrc.SizeOfRawData != len(pe.__data__):
        sys.exit("the .exe has data after its last section: not supported")
    icons, group = {}, None
    for t in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        for n in t.directory.entries:
            for lang in n.directory.entries:
                if t.id == pefile.RESOURCE_TYPE["RT_ICON"]:
                    icons[n.id] = lang.data.struct
                elif t.id == pefile.RESOURCE_TYPE["RT_GROUP_ICON"] and group is None:
                    group = lang.data.struct
    images = read_ico(ico)
    if group is None or len(images) > len(icons):
        sys.exit(f"the .exe has {len(icons)} icon images, the .ico {len(images)}: not supported")
    ids = sorted(icons)[:len(images)]
    base_off = align(rsrc.Misc_VirtualSize, 8)              # new data goes after what's there, in the same section
    blob = bytearray()
    grp = bytearray(struct.pack("<HHH", 0, 1, len(images)))
    for (w, h, colors, planes, bpp, data), rid in zip(images, ids):
        off = base_off + len(blob)
        icons[rid].OffsetToData, icons[rid].Size = rsrc.VirtualAddress + off, len(data)
        blob += data + b"\0" * (align(len(data), 8) - len(data))
        grp += struct.pack("<BBBBHHIH", w, h, colors, 0, planes or 1, bpp or 32, len(data), rid)
    group.OffsetToData, group.Size = rsrc.VirtualAddress + base_off + len(blob), len(grp)
    blob += grp
    vsize = base_off + len(blob)
    rsrc.Misc_VirtualSize = vsize
    rsrc.SizeOfRawData = align(vsize, opt.FileAlignment)
    opt.DATA_DIRECTORY[2].Size = vsize
    opt.SizeOfImage = align(rsrc.VirtualAddress + vsize, opt.SectionAlignment)
    data = bytearray(pe.write())
    section = bytearray(data[rsrc.PointerToRawData:rsrc.PointerToRawData + base_off])
    section += b"\0" * (base_off - len(section)) + blob
    section += b"\0" * (rsrc.SizeOfRawData - len(section))
    out = data[:rsrc.PointerToRawData] + section
    pe.close()
    open(exe, "wb").write(out)
    print(f"{exe}: {len(images)} icon images from {ico}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
