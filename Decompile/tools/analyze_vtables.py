#!/usr/bin/env python3
"""Recover MSVC RTTI class names and vtables from the original image.

Writes, under build/<module>/:
  vtables.csv       vtable VA, class, number of slots
  vtable_slots.csv  vtable VA, class, slot index, function VA, current name
  vtable_names.csv  function VA, proposed Class::vfunc_XX (unnamed functions only)

The scanner understands the x86 MSVC RTTI layout:

  vtable[-1] -> CompleteObjectLocator
  locator+0  signature (0/1), +12 TypeDescriptor VA, +20 self VA
  descriptor+8 -> ".?AVClass@Namespace@@"

Nothing here guesses a vtable: the self-pointer and the type descriptor must
agree, and every slot must point into .text.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import re
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "match"))
from pe import PE  # noqa: E402

DECOMPILE = HERE.parent
ROOT = DECOMPILE.parent


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def readable_class(raw: str) -> str:
    """Turn .?AVSomervilleGameApp@Seoul@@ into SomervilleGameApp (best effort)."""
    name = raw[4:] if raw.startswith(".?AV") else raw
    name = name.split("@@", 1)[0]
    if name.startswith("?$"):
        name = name.replace("?$", "").replace("$", "")
    parts = [p for p in name.split("@") if p]
    cls = parts[0] if parts else name
    cls = re.sub(r"[^A-Za-z0-9_]", "_", cls)
    return cls or "RTTI"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image", default=str(ROOT / "work/inputs/exe/ShootManyRobots.exe"))
    ap.add_argument("--module", default="game")
    ap.add_argument("--units", default=str(DECOMPILE / "build/game/units.json"))
    args = ap.parse_args()

    pe = PE(args.image)
    base = pe.image_base
    text = next(s for s in pe.sections if s.name == ".text")
    text_lo = base + text.va
    text_hi = text_lo + max(text.vsize, text.raw_size)

    def in_text(va: int) -> bool:
        return text_lo <= va < text_hi

    # --- type descriptors (name string at +8) ---
    descriptors: dict[int, str] = {}
    for s in pe.sections:
        if not s.raw_size:
            continue
        data = pe.data[s.raw_off:s.raw_off + s.raw_size]
        for m in re.finditer(rb"\.\?AV[A-Za-z0-9_@?$<>]+", data):
            va = base + s.va + m.start()
            name = m.group().decode("latin-1")
            descriptors[va - 8] = name

    # --- complete object locators ---
    locators: dict[int, tuple[int, str]] = {}
    for s in pe.sections:
        if not s.raw_size:
            continue
        data = pe.data[s.raw_off:s.raw_off + s.raw_size]
        for off in range(0, len(data) - 24, 4):
            val = u32(data, off)
            if val not in descriptors:
                continue
            col_va = base + s.va + off - 12
            col_off = pe.rva_to_off(col_va - base)
            sig, _off, _cd, td, _cd2, self_va = struct.unpack_from("<IIIIII", pe.data, col_off)
            if sig not in (0, 1) or td != val:
                continue
            # x86 locators may carry pSelf == 0; when it is present it must be exact.
            if self_va not in (0, col_va):
                continue
            locators[col_va] = (td, descriptors[val])

    # --- vtables (pointer immediately after a locator pointer) ---
    vtables: dict[int, tuple[str, list[int]]] = {}
    for s in pe.sections:
        if not s.raw_size:
            continue
        data = pe.data[s.raw_off:s.raw_off + s.raw_size]
        for off in range(0, len(data) - 8, 4):
            val = u32(data, off)
            if val not in locators:
                continue
            vt_va = base + s.va + off + 4
            vt_off = pe.rva_to_off(vt_va - base)
            slots = []
            for k in range(256):
                if vt_off + 4 * (k + 1) > len(pe.data):
                    break
                fn = u32(pe.data, vt_off + 4 * k)
                if not in_text(fn):
                    break
                slots.append(fn)
            if not slots:
                continue
            td, raw = locators[val]
            vtables[vt_va] = (readable_class(raw), slots)

    # --- current function names ---
    names: dict[int, str] = {}
    units_path = Path(args.units)
    if units_path.is_file():
        for u in json.loads(units_path.read_text(encoding="utf-8"))["units"]:
            for f in u["functions"]:
                names[int(f["address"], 16)] = f["name"]

    out = Path(args.module)
    build = DECOMPILE / "build" / out
    build.mkdir(parents=True, exist_ok=True)

    with (build / "vtables.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["vtable", "class", "slots"])
        for vt, (cls, slots) in sorted(vtables.items()):
            w.writerow([f"0x{vt:08x}", cls, len(slots)])

    slot_rows = []
    proposed: dict[int, str] = {}
    for vt, (cls, slots) in sorted(vtables.items()):
        for i, fn in enumerate(slots):
            slot_rows.append([f"0x{vt:08x}", cls, i, f"0x{fn:08x}", names.get(fn, "")])
            if fn not in proposed and names.get(fn, "").startswith(("FUN_", "thunk_")):
                proposed[fn] = f"{cls}::vfunc_{i:02d}"

    with (build / "vtable_slots.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["vtable", "class", "slot", "function", "current_name"])
        w.writerows(slot_rows)

    with (build / "vtable_names.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["address", "current_name", "proposed_name", "vtable_class"])
        for fn, prop in sorted(proposed.items()):
            w.writerow([f"0x{fn:08x}", names.get(fn, ""), prop, prop.split("::")[0]])

    classes = {cls for cls, _ in vtables.values()}
    hits = sum(1 for r in slot_rows if r[3] in proposed)
    print(f"type descriptors {len(descriptors):,} in {len(descriptors and set(descriptors.values())):,} names")
    print(f"locators         {len(locators):,}")
    print(f"vtables          {len(vtables):,} across {len(classes):,} classes")
    print(f"virtual slots    {len(slot_rows):,} ({hits:,} still unnamed)")
    print(f"wrote            {build}/vtables.csv, vtable_slots.csv, vtable_names.csv")

    top = collections.Counter(r[1] for r in slot_rows)
    print("\nlargest vtables")
    for cls, n in top.most_common(15):
        print(f"  {n:4d}  {cls}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
