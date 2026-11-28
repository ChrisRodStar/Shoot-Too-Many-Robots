"""Minimal PE32 reader for matching checks.

Only reads the original image the user already owns; never copies bytes out.
"""
from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Section:
    name: str
    va: int
    vsize: int
    raw_off: int
    raw_size: int
    characteristics: int

    def contains(self, rva: int) -> bool:
        return self.va <= rva < self.va + max(self.vsize, self.raw_size)


class PE:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        if self.data[:2] != b"MZ":
            raise ValueError("not an MZ image")
        pe = struct.unpack_from("<I", self.data, 0x3C)[0]
        if self.data[pe:pe + 4] != b"PE\0\0":
            raise ValueError("not a PE image")
        (self.machine, nsec, self.timestamp, self.ptr_sym, self.num_sym,
         opt_size, self.characteristics) = struct.unpack_from("<HHIIIHH", self.data, pe + 4)
        self.opt = pe + 24
        magic = struct.unpack_from("<H", self.data, self.opt)[0]
        if magic != 0x10B:
            raise ValueError(f"expected PE32 optional header, got {magic:#x}")
        self.image_base = struct.unpack_from("<I", self.data, self.opt + 28)[0]
        self.entry = self.image_base + struct.unpack_from("<I", self.data, self.opt + 16)[0]
        self.size_of_image = struct.unpack_from("<I", self.data, self.opt + 56)[0]
        self.num_dirs = struct.unpack_from("<I", self.data, self.opt + 92)[0]
        self.dirs = [struct.unpack_from("<II", self.data, self.opt + 96 + 8 * i)
                     for i in range(self.num_dirs)]
        sec_off = self.opt + opt_size
        self.sections = []
        for i in range(nsec):
            o = sec_off + 40 * i
            name = self.data[o:o + 8].rstrip(b"\0").decode("latin-1")
            vsize, va, rsize, roff, _, _, _, _, ch = struct.unpack_from(
                "<IIIIIIHHI", self.data, o + 8)
            self.sections.append(Section(name, va, vsize, roff, rsize, ch))

    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    def section_for_rva(self, rva: int) -> Section | None:
        for s in self.sections:
            if s.contains(rva):
                return s
        return None

    def rva_to_off(self, rva: int) -> int:
        s = self.section_for_rva(rva)
        if s is None:
            raise ValueError(f"RVA {rva:#x} is not in a section")
        delta = rva - s.va
        if delta >= s.raw_size:
            raise ValueError(f"RVA {rva:#x} is uninitialized data in {s.name}")
        return s.raw_off + delta

    def read_rva(self, rva: int, size: int) -> bytes:
        off = self.rva_to_off(rva)
        if off + size > len(self.data):
            raise ValueError("read past end of file")
        return self.data[off:off + size]

    def read_va(self, va: int, size: int) -> bytes:
        return self.read_rva(va - self.image_base, size)

    def function_bytes(self, va: int, size: int) -> bytes:
        return self.read_va(va, size)

    def cstring_rva(self, rva: int) -> str:
        off = self.rva_to_off(rva)
        end = self.data.index(b"\0", off)
        return self.data[off:end].decode("latin-1")

    def exports(self) -> list[tuple[str, int]]:
        """Return (decorated name, VA) for each named export."""
        if not self.dirs or self.dirs[0][0] == 0:
            return []
        rva, _ = self.dirs[0]
        (_, _, _, _, name_rva, _, nfunc, nname,
         af, an, ao) = struct.unpack_from("<IIHHIIIIIII", self.read_rva(rva, 40), 0)
        out = []
        for i in range(nname):
            nr = struct.unpack_from("<I", self.read_rva(an + 4 * i, 4))[0]
            name = self.cstring_rva(nr)
            ordinal = struct.unpack_from("<H", self.read_rva(ao + 2 * i, 2))[0]
            frva = struct.unpack_from("<I", self.read_rva(af + 4 * ordinal, 4))[0]
            out.append((name, self.image_base + frva))
        return out

    def check(self, sha256: str | None = None) -> None:
        if sha256 and self.sha256() != sha256:
            raise SystemExit(
                f"image fingerprint mismatch\n  expected {sha256}\n  got      {self.sha256()}")
