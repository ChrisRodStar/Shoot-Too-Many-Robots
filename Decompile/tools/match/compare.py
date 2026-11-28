#!/usr/bin/env python3
"""Compare a compiled COFF object against the original PE, function by function.

This is the byte-exact half of the decompilation loop. It does not compile
anything: point it at an object built by MSVC 2008 (or any COFF compiler) and a
bank from build/<module>/units.json.

    # one hand-written function
    compare.py --image work/inputs/exe/ShootManyRobots.exe \
               --object build/test/fun.o --addr 0x401050

    # a whole bank
    compare.py --image ... --object ... --bank bank_0000

Matching rules:
  * a function matches only if its bytes at the original address are identical;
  * relocations are ignored unless --strict-relocs is given, and the ignored
    spans are reported so a "match" is never silent about them;
  * a missing symbol or a size difference is a mismatch.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from coff import Coff, undecorate  # noqa: E402
from pe import PE  # noqa: E402

ROOT = HERE.parents[2]


def norm_addr(a: str) -> str:
    a = a.lower()
    if a.startswith("0x"):
        a = a[2:]
    return a.zfill(8)


def load_units(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for u in data["units"]:
        for f in u["functions"]:
            out[norm_addr(f["address"][2:] if f["address"].startswith("0x") else f["address"])] = f
    return out


def format_bytes(b: bytes) -> str:
    return " ".join(f"{x:02x}" for x in b)


def first_diff(a: bytes, b: bytes) -> int | None:
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    if len(a) != len(b):
        return min(len(a), len(b))
    return None


def _reloc_target(pe: PE, coff: Coff, reloc_sym, addend: int, resolver):
    if resolver is None:
        return None
    if reloc_sym.section > 0:
        sec = coff.sections[reloc_sym.section - 1]
        if not sec.is_code:
            return resolver.resolve_data(coff, reloc_sym, addend)
    return resolver.resolve(reloc_sym.name)


def _data_fallback(pe: PE, coff: Coff, reloc_sym, addend: int, want: bytes,
                   off: int, typ: int):
    """Use the original instruction's pointer, validated by data bytes.

    Constants and string literals are not symbols in the PE. The original
    field already holds their VA; accept it only when the object's bytes at the
    referenced data symbol equal the bytes at that VA.
    """
    if reloc_sym.section <= 0 or off < 0 or off + 4 > len(want):
        return None
    sec = coff.sections[reloc_sym.section - 1]
    start = reloc_sym.value + addend
    if start < 0 or start >= len(sec.data):
        return None
    field = struct.unpack_from("<I", want, off)[0]
    cand = field - addend
    if typ == 0x07:  # DIR32NB stores an RVA
        cand += pe.image_base
    if cand < pe.image_base or cand >= pe.image_base + pe.size_of_image:
        return None
    for ln in (16, 8, 4):
        blob = sec.data[start:start + ln]
        if len(blob) < 4:
            continue
        try:
            orig = pe.read_va(cand, len(blob))
        except ValueError:
            continue
        if orig == blob:
            return cand
    return None


def compare_one(pe: PE, rec: dict, obj_map: dict, symbol_map: dict,
                strict_relocs: bool, verbose: bool, resolver=None):
    addr_hex = rec["address"][2:] if rec["address"].startswith("0x") else rec["address"]
    addr_hex = norm_addr(addr_hex)
    va = int(addr_hex, 16)
    name = rec["name"]
    want_size = int(rec["size"])
    want = pe.function_bytes(va, want_size)

    sym_name = symbol_map.get(addr_hex, name)
    entry = obj_map.get(sym_name) or obj_map.get(undecorate(sym_name))
    if entry is None and name.startswith("FUN_"):
        entry = obj_map.get(name)
    if entry is None:
        return {"addr": addr_hex, "name": name, "status": "missing",
                "detail": f"no object symbol {sym_name!r}"}

    sym, size, sec, coff = entry
    got = sec.data[sym.value:sym.value + size]
    relocs = coff.relocations_for(sym, size)

    if strict_relocs:
        d = first_diff(want, got)
        if d is None and len(want) == len(got):
            return {"addr": addr_hex, "name": name, "status": "match",
                    "detail": f"{len(want)} bytes (strict, {len(relocs)} reloc)",
                    "size": len(want)}
        detail = f"first diff +{d:#x}: want {format_bytes(want[d:d+8])} got {format_bytes(got[d:d+8])}"
        return {"addr": addr_hex, "name": name, "status": "mismatch", "detail": detail}

    # Apply every resolvable relocation to a copy of the object's bytes, using
    # the original function's VA as the place-relative base. Unresolved spans
    # are reported, never silently counted as matched.
    patched = bytearray(got)
    unresolved: set[int] = set()
    resolved = 0
    for r in relocs:
        off = r.offset - sym.value
        if off < 0 or off + 4 > len(patched):
            unresolved.update(range(max(off, 0), min(off + 4, len(patched))))
            continue
        addend = struct.unpack_from("<i", got, off)[0]
        reloc_sym = coff.symbols[r.symbol_index]
        target = _reloc_target(pe, coff, reloc_sym, addend, resolver)
        if target is None and r.typ in (0x06, 0x07):
            target = _data_fallback(pe, coff, reloc_sym, addend, want, off, r.typ)
        if target is None:
            unresolved.update(range(off, off + 4))
            continue
        if r.typ == 0x14:          # REL32
            expected = target + addend - (va + off + 4)
        elif r.typ == 0x06:        # DIR32
            expected = target + addend
        elif r.typ == 0x07:        # DIR32NB
            expected = target + addend - pe.image_base
        else:
            unresolved.update(range(off, off + 4))
            continue
        struct.pack_into("<I", patched, off, expected & 0xFFFFFFFF)
        resolved += 1
    got = bytes(patched)

    n = min(len(want), len(got))
    diffs = [i for i in range(n) if i not in unresolved and want[i] != got[i]]
    if not diffs and len(want) == len(got):
        if unresolved:
            return {"addr": addr_hex, "name": name, "status": "unresolved",
                    "detail": f"{len(unresolved)} relocation byte(s) unresolved"}
        detail = f"{len(want)} bytes"
        if resolved:
            detail += f", {resolved} relocation(s) resolved"
        return {"addr": addr_hex, "name": name, "status": "match",
                "detail": detail, "size": len(want)}

    d = diffs[0] if diffs else n
    detail = f"first diff +{d:#x}: want {format_bytes(want[d:d+8])} got {format_bytes(got[d:d+8])}"
    if len(want) != len(got):
        detail += f"; size want {len(want)} got {len(got)}"
    if unresolved:
        detail += f"; {len(unresolved)} unresolved reloc byte(s)"
    if verbose:
        return {"addr": addr_hex, "name": name, "status": "mismatch",
                "detail": detail, "want": format_bytes(want), "got": format_bytes(got)}
    return {"addr": addr_hex, "name": name, "status": "mismatch", "detail": detail}


def selftest(pe: PE) -> int:
    print(f"image       {pe.path}")
    print(f"sha256      {pe.sha256()}")
    print(f"image base  {pe.image_base:#x}")
    print(f"entry       {pe.entry:#x}")
    print(f"sections    {', '.join(s.name for s in pe.sections)}")
    exports = pe.exports()
    print(f"exports     {len(exports)}")
    assert len(exports) == 200, "expected 200 Seoul Engine exports"
    got = pe.function_bytes(0x401050, 5)
    assert got == bytes.fromhex("33 c0 c2 10 00"), got.hex()
    print("bytes       0x401050 = 33 c0 c2 10 00")
    print("pe reader   OK")

    # COFF parser: compile a tiny object with clang when available.
    import shutil
    import subprocess
    import tempfile
    clang = shutil.which("clang")
    if not clang:
        print("coff reader skipped (clang not found)")
        return 0
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "t.c"
        obj = Path(td) / "t.o"
        src.write_text("__stdcall int f(int a,int b,int c,int d){return 0;}\n")
        subprocess.run([clang, "--target=i686-pc-windows-msvc", "-c", "-O2",
                        "-o", str(obj), str(src)], check=True)
        c = Coff.load(obj)
        funcs = c.functions()
        assert funcs, "no functions parsed from COFF"
        sym, size, sec = funcs[0]
        print(f"coff reader OK: {sym.name} {size} bytes, {len(c.relocations)} reloc section(s)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image", default=str(ROOT / "work/inputs/exe/ShootManyRobots.exe"))
    ap.add_argument("--object", action="append", default=[], help="COFF object (repeatable)")
    ap.add_argument("--units", default=str(ROOT / "Decompile/build/game/units.json"))
    ap.add_argument("--bank", help="bank name, e.g. bank_0000")
    ap.add_argument("--addr", action="append", default=[], help="function address (repeatable)")
    ap.add_argument("--symbol-map", help="JSON {addr: object symbol}")
    ap.add_argument("--reloc-symbols", help="JSON {object symbol: original VA}")
    ap.add_argument("--strict-relocs", action="store_true")
    ap.add_argument("--no-resolve", action="store_true",
                    help="mask relocation spans instead of resolving them")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    pe = PE(args.image)
    if args.selftest:
        return selftest(pe)

    if not args.object:
        ap.error("--object is required (or use --selftest)")
    obj_map = {}
    for path in args.object:
        c = Coff.load(path)
        for sym, size, sec in c.functions():
            obj_map[sym.name] = (sym, size, sec, c)
            obj_map.setdefault(undecorate(sym.name), (sym, size, sec, c))

    units_path = Path(args.units)
    units = load_units(units_path) if units_path.is_file() else {}
    if args.addr:
        wanted = []
        for a in args.addr:
            spec = a.split(":", 1)
            k = norm_addr(spec[0])
            if k in units:
                rec = dict(units[k])
                if len(spec) == 2:
                    rec["size"] = int(spec[1], 0)
                wanted.append(rec)
            elif len(spec) == 2:
                wanted.append({"address": "0x" + k, "name": f"FUN_{k}",
                               "size": int(spec[1], 0)})
            else:
                ap.error(f"address {a} not in {args.units}; pass addr:size for a raw check")
    elif args.bank:
        data = json.loads(Path(args.units).read_text(encoding="utf-8"))
        unit = next((u for u in data["units"] if u["name"] == args.bank), None)
        if unit is None:
            ap.error(f"no such bank: {args.bank}")
        wanted = unit["functions"]
    else:
        ap.error("select functions with --bank or --addr")

    symbol_map = {}
    if args.symbol_map:
        symbol_map = {norm_addr(k): v for k, v in json.loads(Path(args.symbol_map).read_text()).items()}

    resolver = None
    if not args.no_resolve:
        from symbols import Resolver
        extra = {}
        if args.reloc_symbols:
            extra = {k: int(v, 16) for k, v in
                     json.loads(Path(args.reloc_symbols).read_text()).items()}
        resolver = Resolver(pe, units_path, extra)
    results = [compare_one(pe, r, obj_map, symbol_map, args.strict_relocs,
                           args.verbose, resolver)
               for r in wanted]

    counts = {"match": 0, "mismatch": 0, "missing": 0, "unresolved": 0}
    matched_bytes = 0
    for r in results:
        counts[r["status"]] += 1
        if r["status"] == "match":
            matched_bytes += r.get("size", 0)
    if args.json:
        print(json.dumps({"counts": counts, "matched_bytes": matched_bytes,
                          "results": results}, indent=1))
    else:
        for r in results:
            if r["status"] == "match" and not args.verbose:
                continue
            print(f"{r['status'].upper():8s} {r['addr']}  {r['name']}  {r['detail']}")
        total = len(results)
        print(f"\n{counts['match']}/{total} functions match "
              f"({matched_bytes} bytes); {counts['mismatch']} mismatch, "
              f"{counts['missing']} missing, {counts['unresolved']} unresolved reloc")
    return 0 if (counts["mismatch"] == 0 and counts["missing"] == 0
                 and counts["unresolved"] == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
