#!/usr/bin/env python3
"""Apply a rename map to the generated tree, in place and idempotently.

Input is a CSV with at least `address,proposed_name` (the format written by
analyze_vtables.py), or `address,new_name`. Only functions whose current name
is still a placeholder are renamed, so a sourced name is never overwritten.

Every rename is recorded in build/<module>/names_applied.csv with its source,
and the per-bank metadata is updated too, so a later `export.sh` merge keeps
the names.

    python3 Decompile/tools/apply_names.py            # vtable_names.csv
    python3 Decompile/tools/apply_names.py --map my.csv --source community
    python3 Decompile/tools/apply_names.py --dry-run
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def norm_addr(a: str) -> str:
    a = a.strip().lower()
    if a.startswith("0x"):
        a = a[2:]
    return a.zfill(8)


def load_map(path: Path) -> list[tuple[str, str]]:
    out = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        name_col = "proposed_name" if "proposed_name" in (reader.fieldnames or []) else "new_name"
        for row in reader:
            addr = norm_addr(row.get("address", ""))
            new = (row.get(name_col) or "").strip()
            if addr and new:
                out.append((addr, new))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--module", default="game")
    ap.add_argument("--map", default=None)
    ap.add_argument("--source", default="vtable:RTTI",
                    help="provenance recorded for every rename")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    build = ROOT / "build" / args.module
    src = ROOT / "src" / args.module
    map_path = Path(args.map) if args.map else build / "vtable_names.csv"
    if not map_path.is_file():
        raise SystemExit(f"missing rename map: {map_path}")
    if not (build / "functions.jsonl").is_file():
        raise SystemExit("missing functions index; run export.sh first")

    records = [json.loads(line) for line in
               (build / "functions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    by_addr = {r["addr"]: r for r in records}
    wanted = load_map(map_path)

    rename: dict[str, str] = {}
    for addr, new in wanted:
        rec = by_addr.get(addr)
        if rec is None:
            continue
        if not rec["name"].startswith(("FUN_", "thunk_")):
            continue
        if rec["name"] == new:
            continue
        rename[rec["name"]] = new

    if not rename:
        print("nothing to rename (all targets are already named or absent)")
        return 0

    print(f"{len(rename)} placeholder function(s) -> names")
    for old, new in list(rename.items())[:10]:
        print(f"  {old} -> {new}")

    if args.dry_run:
        print("dry run: no files changed")
        return 0

    # Replace whole-token placeholders in every generated source bank.
    pat = re.compile(r"\b(" + "|".join(re.escape(k) for k in rename) + r")\b")
    changed_banks = 0
    for path in sorted(src.glob("*.c")):
        text = path.read_text(encoding="utf-8")
        new_text, n = pat.subn(lambda m: rename[m.group(1)], text)
        if n:
            path.write_text(new_text, encoding="utf-8")
            changed_banks += 1
    print(f"rewrote {changed_banks} bank file(s)")

    # Update metadata used by merges and by the CLI.
    renamed = set(rename)
    for path in sorted((build / "meta").glob("*.jsonl")):
        lines = path.read_text(encoding="utf-8").splitlines()
        out = []
        hit = False
        for line in lines:
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("name") in renamed:
                old = rec["name"]
                rec["placeholder"] = old
                rec["name"] = rename[old]
                rec["name_source"] = args.source
                if rec.get("signature"):
                    rec["signature"] = rec["signature"].replace(old, rec["name"])
                hit = True
            out.append(json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
        if hit:
            path.write_text("\n".join(out) + "\n", encoding="utf-8")

    for rec in records:
        if rec.get("name") in renamed:
            old = rec["name"]
            rec["placeholder"] = old
            rec["name"] = rename[old]
            rec["name_source"] = args.source
            if rec.get("signature"):
                rec["signature"] = rec["signature"].replace(old, rec["name"])
    (build / "functions.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in records) + "\n",
        encoding="utf-8")

    with (build / "symbols.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["address", "size", "name", "source", "decompiled"])
        for r in records:
            w.writerow([r["addr"], r["size"], r["name"], r.get("source", ""),
                        r["decompiled"]])

    # Prototypes and the string index carry names too.
    proto = build / "prototypes.h"
    if proto.is_file():
        proto.write_text(pat.sub(lambda m: rename[m.group(1)],
                                 proto.read_text(encoding="utf-8")), encoding="utf-8")
    strings = build / "strings.tsv"
    if strings.is_file():
        lines = []
        for line in strings.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t", 2)
            if len(parts) == 3 and parts[1] in renamed:
                parts[1] = rename[parts[1]]
                line = "\t".join(parts)
            lines.append(line)
        strings.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with (build / "names_applied.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["address", "placeholder", "name", "source"])
        for addr, new in wanted:
            rec = by_addr.get(addr)
            if rec and rec.get("name") == new:
                w.writerow([addr, rec.get("placeholder", ""), new, args.source])

    print(f"updated {build}/functions.jsonl and symbols.csv")
    print("run `decompile.py units` to refresh the build recipe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
