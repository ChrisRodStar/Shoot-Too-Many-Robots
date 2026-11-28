"""Resolve COFF relocation targets to original virtual addresses.

Used by the relocation-aware comparison. It knows three things:

  * functions from build/<module>/units.json, by their `FUN_XXXXXXXX` placeholder
  * PE exports (the Seoul Engine API)
  * imported names, mapped to their IAT slot

Constants and string literals are resolved by matching the object's bytes
against the original image; that is deliberately conservative and returns None
when the match is ambiguous.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from coff import Coff
from pe import PE


class Resolver:
    def __init__(self, pe: PE, units_path: str | Path | None = None,
                 extra: dict[str, int] | None = None):
        self.pe = pe
        self.by_name: dict[str, int] = {}

        if units_path and Path(units_path).is_file():
            data = json.loads(Path(units_path).read_text(encoding="utf-8"))
            for unit in data.get("units", []):
                for f in unit.get("functions", []):
                    va = int(f["address"], 16)
                    self._add(f"FUN_{va:08X}", va)
                    self._add(f"FUN_{va:08x}", va)
                    self._add(f"sub_{va:08X}", va)
                    self._add(f"sub_{va:08x}", va)

        for name, va in pe.exports():
            self._add(name, va)
            self._add(name.lstrip("_"), va)

        for name, va in (extra or {}).items():
            self._add(name, va if isinstance(va, int) else int(va, 16))

        for _dll, name, iat in pe.imports():
            for alias in (name, f"_{name}", f"__imp_{name}", f"__imp__{name}",
                          f"_imp_{name}", f"_imp__{name}",
                          f"__imp_{name}@0", f"__imp__{name}@0"):
                self._add(alias, iat)
            # stdcall decorations are not known here; strip @N at lookup time.

    def _add(self, name: str, va: int) -> None:
        if name:
            self.by_name.setdefault(name, va)

    def _variants(self, name: str):
        yield name
        n = name
        if n.startswith("_"):
            n = n[1:]
            yield n
        for base in (name, n):
            stripped = re.sub(r"@\d+$", "", base)
            if stripped != base:
                yield stripped
        # __imp__name -> name, with/without C decoration
        for base in (name, n):
            m = re.match(r"^_{0,2}imp_{1,2}(.+)$", base)
            if m:
                rest = re.sub(r"@\d+$", "", m.group(1))
                yield rest
                yield "_" + rest

    def resolve(self, name: str) -> int | None:
        for cand in self._variants(name):
            if cand in self.by_name:
                return self.by_name[cand]
        m = re.search(r"(?:FUN|sub)_([0-9A-Fa-f]{8})", name)
        if m:
            return int(m.group(1), 16)
        return None

    def resolve_data(self, coff: Coff, sym, addend: int, length: int = 16) -> int | None:
        """Find the original VA of an object data symbol by matching its bytes."""
        sec_idx = sym.section - 1
        if sec_idx < 0 or sec_idx >= len(coff.sections):
            return None
        sec = coff.sections[sec_idx]
        off = sym.value + addend
        if off < 0 or off >= len(sec.data):
            return None
        blob = sec.data[off:off + length]
        if len(blob) < 4:
            return None
        # A longer probe is safer; trim to what is available.
        for probe in (blob, blob[:8], blob[:4]):
            if len(probe) < 4:
                continue
            hits: list[int] = []
            for s in self.pe.sections:
                if not s.raw_size:
                    continue
                data = self.pe.data[s.raw_off:s.raw_off + s.raw_size]
                start = 0
                while True:
                    i = data.find(probe, start)
                    if i < 0:
                        break
                    hits.append(self.pe.image_base + s.va + i)
                    start = i + 1
                    if len(hits) > 3:
                        break
                if len(hits) > 3:
                    break
            if len(hits) == 1:
                return hits[0]
        return None
