#!/usr/bin/env python3
"""Compile and byte-verify every function in config/matched.json.

    python3 Decompile/tools/match/verify.py
    python3 Decompile/tools/match/verify.py --no-build --verbose
    python3 Decompile/tools/match/verify.py --strict-relocs

Requires the MSVC 2008 Docker toolchain; see docs/MSVC2008.md.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]          # Decompile/
REPO = ROOT.parent              # repository root
sys.path.insert(0, str(HERE))

from coff import Coff, undecorate  # noqa: E402
from compare import compare_one, norm_addr  # noqa: E402
from pe import PE  # noqa: E402
from symbols import Resolver  # noqa: E402


def object_name(source: str) -> str:
    return "work/match/obj/" + source.rsplit("/", 1)[-1].rsplit(".", 1)[0] + ".obj"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(ROOT / "config/matched.json"))
    ap.add_argument("--image", default=str(REPO / "work/inputs/exe/ShootManyRobots.exe"))
    ap.add_argument("--no-build", action="store_true")
    ap.add_argument("--units", default=str(ROOT / "build/game/units.json"))
    ap.add_argument("--strict-relocs", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    entries = cfg["functions"]
    flags = cfg.get("flags", ["/O2", "/TC"])

    groups: dict[tuple[str, tuple[str, ...]], list[dict]] = {}
    for e in entries:
        groups.setdefault((e["source"], tuple(e.get("flags", flags))), []).append(e)

    (REPO / "work/match/obj").mkdir(parents=True, exist_ok=True)
    objects: dict[str, Path] = {}
    for (source, group_flags), group in groups.items():
        obj = REPO / object_name(source)
        objects[source] = obj
        if args.no_build and obj.is_file():
            continue
        src = REPO / "Decompile" / source
        if not src.is_file():
            print(f"missing source: {src}", file=sys.stderr)
            return 2
        cmd = [str(ROOT / "tools/msvc/cl.sh"), "/nologo", "/c", *group_flags,
               f"/Fo{object_name(source)}", str(src.relative_to(REPO))]
        print("compile:", " ".join(cmd))
        res = subprocess.run(cmd, cwd=REPO)
        if res.returncode != 0 or not obj.is_file():
            print(f"compile failed: {source}", file=sys.stderr)
            return 2

    obj_map = {}
    for source, obj in objects.items():
        co = Coff.load(obj)
        for sym, size, sec in co.functions():
            obj_map[sym.name] = (sym, size, sec, co)
            obj_map.setdefault(undecorate(sym.name), (sym, size, sec, co))

    pe = PE(args.image)
    extra = {}
    for e in entries:
        for name, va in e.get("relocations", {}).items():
            extra[name] = int(va, 16)
    resolver = Resolver(pe, args.units, extra)
    symbol_map = {norm_addr(e["address"]): e["symbol"] for e in entries}
    results = []
    for e in entries:
        rec = {
            "address": e["address"],
            "name": e.get("symbol", e["address"]),
            "size": e["size"],
        }
        results.append(compare_one(pe, rec, obj_map, symbol_map,
                                   args.strict_relocs, args.verbose, resolver))

    matched_bytes = 0
    counts = {"match": 0, "mismatch": 0, "missing": 0, "unresolved": 0}
    for r in results:
        counts[r["status"]] += 1
        if r["status"] == "match":
            matched_bytes += r.get("size", 0)
        if r["status"] != "match" or args.verbose:
            print(f"{r['status'].upper():8s} {r['addr']}  {r['name']}  {r['detail']}")

    print(f"\n{counts['match']}/{len(results)} matched, {matched_bytes} bytes; "
          f"{counts['mismatch']} mismatch, {counts['missing']} missing, "
          f"{counts['unresolved']} unresolved reloc")
    flavor = os.environ.get("SMR_MSVC_FLAVOR", "sp1")
    version = {"sp1": "15.00.30729.01", "rtm": "15.00.21022.08"}.get(
        flavor, cfg.get("cl_version"))
    print(f"compiler: msvc9-{flavor} {version}")
    return 0 if (counts["mismatch"] == 0 and counts["missing"] == 0
                 and counts["unresolved"] == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
