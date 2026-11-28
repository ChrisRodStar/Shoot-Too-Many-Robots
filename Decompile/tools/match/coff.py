"""Minimal i386 COFF object reader used by the matching harness."""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

IMAGE_SCN_CNT_CODE = 0x20
IMAGE_SYM_CLASS_EXTERNAL = 2
IMAGE_SYM_CLASS_STATIC = 3
IMAGE_SYM_DTYPE_FUNCTION = 2

# i386 relocation types we care about for masking/validation.
REL_NAMES = {
    0x00: "ABS",
    0x06: "DIR32",
    0x07: "DIR32NB",
    0x0A: "SECTION",
    0x0B: "SECREL",
    0x14: "REL32",
}
REL_SIZES = {0x00: 0, 0x06: 4, 0x07: 4, 0x0A: 2, 0x0B: 4, 0x14: 4}


def undecorate(name: str) -> str:
    """Best-effort i386 C decoration removal; C++ names are left alone."""
    if name.startswith("?"):
        return name
    if name.startswith("_") and "@" in name:
        base = name[1:]
        return base.rsplit("@", 1)[0]
    if name.startswith("@"):
        return name[1:].rsplit("@", 1)[0]
    if name.startswith("_"):
        return name[1:]
    return name


@dataclass
class Section:
    name: str
    virtual_size: int
    va: int
    raw_size: int
    raw_off: int
    reloc_off: int
    nreloc: int
    characteristics: int
    data: bytes = b""

    @property
    def is_code(self) -> bool:
        return bool(self.characteristics & IMAGE_SCN_CNT_CODE)


@dataclass
class Symbol:
    name: str
    value: int
    section: int
    typ: int
    storage_class: int

    @property
    def is_function(self) -> bool:
        return (self.typ >> 4) == IMAGE_SYM_DTYPE_FUNCTION or self.name.startswith("_")


@dataclass
class Reloc:
    offset: int
    symbol_index: int
    typ: int
    size: int


@dataclass
class Coff:
    path: Path
    machine: int
    sections: list[Section]
    symbols: list[Symbol] = field(default_factory=list)
    relocations: dict[int, list[Reloc]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "Coff":
        p = Path(path)
        d = p.read_bytes()
        (machine, nsec, _, ptr_sym, n_sym, opt_size,
         _) = struct.unpack_from("<HHIIIHH", d, 0)
        sec_off = 20 + opt_size
        str_off = ptr_sym + 18 * n_sym
        str_size = struct.unpack_from("<I", d, str_off)[0] if str_off + 4 <= len(d) else 4

        def coff_string(off: int) -> str:
            if off == 0:
                return ""
            start = str_off + off
            end = d.index(b"\0", start)
            return d[start:end].decode("latin-1")

        sections = []
        for i in range(nsec):
            o = sec_off + 40 * i
            raw = d[o:o + 8]
            if raw[:1] == b"/":
                name = coff_string(int(raw[1:].rstrip(b"\0") or b"0"))
            else:
                name = raw.rstrip(b"\0").decode("latin-1")
            vsize, va, rsize, roff, poff, _, nrel, _, ch = struct.unpack_from(
                "<IIIIIIHHI", d, o + 8)
            data = d[roff:roff + rsize] if roff else b""
            sections.append(Section(name, vsize, va, rsize, roff, poff, nrel, ch, data))

        syms = []
        for i in range(n_sym):
            o = ptr_sym + 18 * i
            raw = d[o:o + 8]
            if raw[:4] == b"\0\0\0\0":
                name = coff_string(struct.unpack_from("<I", raw, 4)[0])
            else:
                name = raw.rstrip(b"\0").decode("latin-1")
            value, secn, typ, sclass, naux = struct.unpack_from("<IhHBB", d, o + 8)
            syms.append(Symbol(name, value, secn, typ, sclass))

        relocs: dict[int, list[Reloc]] = {}
        for si, s in enumerate(sections):
            if not s.reloc_off:
                continue
            rs = []
            for r in range(s.nreloc):
                o = s.reloc_off + 10 * r
                off, symidx, typ = struct.unpack_from("<IIH", d, o)
                rs.append(Reloc(off, symidx, typ, REL_SIZES.get(typ, 4)))
            relocs[si] = rs

        return cls(p, machine, sections, syms, relocs)

    def code_section(self) -> Section:
        for s in self.sections:
            if s.name == ".text":
                return s
        for s in self.sections:
            if s.is_code:
                return s
        raise ValueError("no code section")

    def functions(self) -> list[tuple[Symbol, int, Section]]:
        """(symbol, size, section) for each function symbol, by address."""
        out = []
        for si, s in enumerate(self.sections):
            if not s.is_code:
                continue
            sec_syms = [x for x in self.symbols
                        if x.section == si + 1
                        and (x.typ >> 4) == IMAGE_SYM_DTYPE_FUNCTION
                        and x.storage_class in (IMAGE_SYM_CLASS_EXTERNAL, IMAGE_SYM_CLASS_STATIC)]
            sec_syms.sort(key=lambda x: x.value)
            for i, sym in enumerate(sec_syms):
                end = sec_syms[i + 1].value if i + 1 < len(sec_syms) else len(s.data)
                out.append((sym, max(0, end - sym.value), s))
        return out

    def relocations_for(self, sym: Symbol, size: int) -> list[Reloc]:
        sec_idx = sym.section - 1
        return [r for r in self.relocations.get(sec_idx, [])
                if sym.value <= r.offset < sym.value + size]
