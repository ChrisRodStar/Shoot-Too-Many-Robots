"""Rebase a PE32 DLL's file-backed HIGHLOW references for static analysis."""
import argparse
import struct
from pathlib import Path


def relocate(image, base):
    def u32(offset):
        return struct.unpack_from("<I", image, offset)[0]

    def u16(offset):
        return struct.unpack_from("<H", image, offset)[0]

    pe = u32(0x3c)
    opt = pe + 24
    if (image[:2] != b"MZ" or image[pe:pe+4] != b"PE\0\0" or u16(pe+4) != 0x14c
            or u16(opt) != 0x10b or not u16(pe+22) & 0x2000):
        raise ValueError("expected an x86 PE32 DLL")
    if base % 65536 or base < 0 or base + u32(opt+56) > 2**32:
        raise ValueError("invalid module base")
    delta = base - u32(opt+28)
    if not delta:
        return image
    sections = opt + u16(pe+20)

    def offset(rva, size):
        for i in range(u16(pe+6)):
            section = sections + 40*i
            start, length, raw = struct.unpack_from("<III", image, section+12)
            if start <= rva and rva+size <= start+length and raw+length <= len(image):
                return raw + rva-start
        raise ValueError(f"unbacked RVA {rva:#x}")

    if u32(opt+92) < 6 or not u32(opt+140):
        raise ValueError("DLL has no relocation directory")
    rva, size = struct.unpack_from("<II", image, opt+136)
    pos = offset(rva, size)
    end = pos + size
    while pos < end:
        page, length = struct.unpack_from("<II", image, pos)
        if length < 8 or length % 2 or pos+length > end:
            raise ValueError("invalid relocation block")
        for entry in range(pos+8, pos+length, 2):
            kind, within = divmod(u16(entry), 4096)
            if kind == 0:
                continue
            if kind != 3:
                raise ValueError(f"unsupported relocation type {kind}")
            addr = offset(page+within, 4)
            struct.pack_into("<I", image, addr, (u32(addr)+delta) % 2**32)
        pos += length
    struct.pack_into("<I", image, opt+28, base)
    return image


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dll", type=Path)
    parser.add_argument("base", type=lambda n: int(n, 0))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.dll.resolve() == args.output.resolve():
        parser.error("use a separate analysis copy")
    args.output.write_bytes(relocate(bytearray(args.dll.read_bytes()), args.base))
