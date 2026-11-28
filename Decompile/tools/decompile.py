#!/usr/bin/env python3
"""Query the decompiled source tree.

Reads the indexes written by tools/export.sh; no Ghidra needed.

    python3 Decompile/tools/decompile.py status
    python3 Decompile/tools/decompile.py stats
    python3 Decompile/tools/decompile.py search lobby --limit 20
    python3 Decompile/tools/decompile.py explain 0x401000
    python3 Decompile/tools/decompile.py callers 0x821270
    python3 Decompile/tools/decompile.py strings weapon
    python3 Decompile/tools/decompile.py unit 3
    python3 Decompile/tools/decompile.py units        # write build/units.json
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODULE = "game"


def addr_key(a: str) -> str:
    a = a.strip().lower()
    if a.startswith("0x"):
        a = a[2:]
    if not re.fullmatch(r"[0-9a-f]+", a):
        raise SystemExit(f"not an address: {a!r}")
    return a.zfill(8)[-8:]


def load_index(module: str):
    path = ROOT / "build" / module / "functions.jsonl"
    if not path.is_file():
        raise SystemExit(f"missing {path}; run Decompile/tools/export.sh first")
    out = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def bank_path(module: str, bank: str) -> Path:
    return ROOT / "src" / module / f"{bank}.c"


_BLOCK = re.compile(r"^/\* ([0-9a-fA-F]{8})  size (\d+)", re.M)


def function_text(module: str, rec: dict) -> str:
    path = bank_path(module, rec["bank"])
    if not path.is_file():
        return f"/* missing {path} */\n"
    text = path.read_text(encoding="utf-8", errors="replace")
    spans = list(_BLOCK.finditer(text))
    for i, m in enumerate(spans):
        if m.group(1).lower() == rec["addr"].lower():
            end = spans[i + 1].start() if i + 1 < len(spans) else len(text)
            return text[m.start():end].rstrip() + "\n"
    return f"/* function {rec['addr']} not found in {path} */\n"


def norm(pattern: str) -> re.Pattern:
    try:
        return re.compile(pattern, re.I)
    except re.error as exc:
        raise SystemExit(f"bad regex: {exc}")


def cmd_status(args):
    idx = load_index(args.module)
    named = [r for r in idx if not r["name"].startswith(("FUN_", "thunk_"))]
    print(f"module          {args.module}")
    print(f"functions       {len(idx):,}")
    print(f"named           {len(named):,} ({len(named)/max(1,len(idx)):.1%})")
    print(f"decompile fails {sum(not r['decompiled'] for r in idx):,}")
    src = ROOT / "src" / args.module
    banks = len(list(src.glob("*.c"))) if src.is_dir() else 0
    print(f"bank files      {banks:,}")
    total = ROOT / "src" / args.module
    if total.is_dir():
        size = sum(p.stat().st_size for p in total.glob("*.c"))
        print(f"source size     {size/1e6:.1f} MB")
    strings = sum(1 for r in idx if r.get("strings"))
    print(f"funcs w/strings {strings:,}")
    idxp = ROOT / "build" / args.module / "functions.jsonl"
    if idxp.is_file():
        print(f"index           {idxp}")
    print(f"Ghidra project  <repo>/work/ghidra/game (smr / ShootManyRobots.exe)")


def cmd_search(args):
    idx = load_index(args.module)
    pat = norm(args.pattern)
    fields = args.field
    limit = args.limit
    hits = 0
    for r in idx:
        hay = []
        if fields in ("all", "name"):
            hay.append(r["name"])
        if fields in ("all", "strings"):
            hay.extend(r.get("strings", []))
        if fields in ("all", "calls"):
            hay.extend(r.get("calls", []))
        if fields == "addr":
            hay.append(r["addr"])
        blob = "\n".join(hay)
        if pat.search(blob):
            print(f"{r['addr']}  {r['size']:6d}  {r['name']}")
            for s in r.get("strings", [])[:3]:
                if pat.search(s):
                    print(f"           \"{s[:110]}\"")
            hits += 1
            if limit and hits >= limit:
                break
    print(f"\n{hits} match(es)", file=sys.stderr)


def cmd_explain(args):
    idx = load_index(args.module)
    key = addr_key(args.address)
    rec = next((r for r in idx if r["addr"] == key), None)
    if rec is None:
        raise SystemExit(f"no function at {key}")
    print(f"address   {rec['addr']}  size {rec['size']}")
    print(f"name      {rec['name']}")
    if rec.get("source"):
        print(f"source    {rec['source']}")
    print(f"bank      {rec['bank']}")
    if rec.get("calls"):
        print("calls     " + " ".join(rec["calls"][:20]))
    if rec.get("strings"):
        print("strings")
        for s in rec["strings"]:
            print(f"  - {s}")
    print()
    print(function_text(args.module, rec))


def cmd_callers(args):
    idx = load_index(args.module)
    key = addr_key(args.address)
    callers = [r for r in idx if key in r.get("calls", [])]
    print(f"{len(callers)} caller(s) of {key}")
    for r in callers:
        print(f"  {r['addr']}  {r['size']:6d}  {r['name']}")
    rec = next((r for r in idx if r["addr"] == key), None)
    if rec:
        print(f"\n{key} calls {len(rec.get('calls', []))} function(s):")
        for c in rec.get("calls", []):
            target = next((x for x in idx if x["addr"] == c), None)
            print(f"  {c:12s} {target['name'] if target else '(external)'}")


def cmd_strings(args):
    path = ROOT / "build" / args.module / "strings.tsv"
    if not path.is_file():
        raise SystemExit(f"missing {path}")
    pat = norm(args.pattern) if args.pattern else None
    hits = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        addr, name, strings = (line.split("\t", 2) + ["", ""])[:3]
        if pat and not pat.search(strings):
            continue
        print(f"{addr}  {name}")
        for s in strings.split(" | "):
            if not pat or pat.search(s):
                print(f"    \"{s[:120]}\"")
        hits += 1
        if args.limit and hits >= args.limit:
            break
    print(f"\n{hits} function(s)", file=sys.stderr)


def cmd_unit(args):
    path = ROOT / "src" / args.module / f"bank_{int(args.bank):04d}.c"
    if not path.is_file():
        raise SystemExit(f"missing {path}")
    print(path.read_text(encoding="utf-8", errors="replace"))


def cmd_stats(args):
    idx = load_index(args.module)
    total_bytes = sum(r["size"] for r in idx)
    unnamed = sum(1 for r in idx if r["name"].startswith(("FUN_", "thunk_")))
    strings = [r for r in idx if r.get("strings")]
    edges = sum(len(r.get("calls", [])) for r in idx)
    ext = collections.Counter(
        c[4:] for r in idx for c in r.get("calls", []) if c.startswith("ext:"))
    namespaces = collections.Counter()
    for r in idx:
        if "::" in r["name"]:
            namespaces[r["name"].rsplit("::", 1)[0]] += 1
    buckets = collections.Counter()
    for r in idx:
        s = r["size"]
        b = "<=32" if s <= 32 else "<=128" if s <= 128 else "<=512" if s <= 512 else ">512"
        buckets[b] += 1

    print(f"functions        {len(idx):,}")
    print(f"code bytes       {total_bytes:,} (Ghidra bodies)")
    print(f"unnamed          {unnamed:,} ({unnamed/max(1,len(idx)):.1%})")
    print(f"call edges       {edges:,} ({edges/max(1,len(idx)):.2f}/function)")
    print(f"with strings     {len(strings):,}")
    print("size buckets     " + "  ".join(f"{k}:{buckets[k]:,}" for k in ("<=32", "<=128", "<=512", ">512")))
    if namespaces:
        print("\ntop namespaces")
        for n, c in namespaces.most_common(15):
            print(f"  {c:6d}  {n}")
    if ext:
        print("\ntop imports called")
        for n, c in ext.most_common(20):
            print(f"  {c:6d}  {n}")


_SLUG = re.compile(r"[^a-z0-9]+")
_GENERIC = {
    "true", "false", "null", "none", "error", "failed", "failure", "warning",
    "assert", "assertion", "invalid", "unknown", "string", "value", "name",
    "file", "open", "close", "read", "write", "load", "save", "init",
}


def _slug(text: str) -> str:
    text = text.strip().lower()
    text = _SLUG.sub("_", text).strip("_")
    return text[:48]


def cmd_suggest(args):
    idx = load_index(args.module)
    freq = collections.Counter()
    for r in idx:
        for s in set(r.get("strings", [])):
            freq[s] += 1

    rows = []
    for r in idx:
        if not r["name"].startswith("FUN_"):
            continue
        best = None
        for s in r.get("strings", []):
            slug = _slug(s)
            if len(slug) < 4 or slug in _GENERIC:
                continue
            # prefer identifier-shaped UI keys and readable sentences
            score = len(slug)
            if re.fullmatch(r"[a-z][a-z0-9_]*", s.strip()):
                score += 30
            if " " in s.strip():
                score += 10
            if freq[s] == 1:
                score += 20
            if best is None or score > best[0]:
                best = (score, s, slug)
        if best is None:
            continue
        _, evidence, slug = best
        rows.append({
            "address": r["addr"],
            "current": r["name"],
            "suggestion": slug,
            "confidence": "high" if freq[evidence] == 1 and len(slug) > 8 else "medium",
            "uses": freq[evidence],
            "evidence": evidence,
        })

    dest = ROOT / "build" / args.module / "suggested_names.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    import csv
    with dest.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["address", "current", "suggestion",
                                           "confidence", "uses", "evidence"])
        w.writeheader()
        w.writerows(rows)
    for row in rows[:args.limit]:
        print(f"{row['address']}  {row['confidence']:6s}  {row['suggestion']}")
        print(f"           \"{row['evidence'][:110]}\"")
    print(f"\n{len(rows)} suggestion(s) -> {dest}", file=sys.stderr)


def cmd_units(args):
    idx = load_index(args.module)
    units = collections.defaultdict(list)
    for r in idx:
        units[r["bank"]].append({
            "address": "0x" + r["addr"],
            "size": r["size"],
            "name": r["name"],
        })
    out = {
        "module": args.module,
        "image": "ShootManyRobots.exe",
        "compiler": "msvc9",
        "note": "One unit per 250-function address-range bank. Not yet byte-exact.",
        "units": [
            {
                "name": b,
                "source": f"src/{args.module}/{b}.c",
                "functions": sorted(fns, key=lambda x: x["address"]),
            }
            for b, fns in sorted(units.items())
        ],
    }
    dest = ROOT / "build" / args.module / "units.json"
    dest.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {dest} ({len(units)} units, {len(idx)} functions)")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--module", default=DEFAULT_MODULE)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status").set_defaults(func=cmd_status)
    sub.add_parser("stats").set_defaults(func=cmd_stats)

    p = sub.add_parser("search")
    p.add_argument("pattern")
    p.add_argument("--field", choices=["all", "name", "strings", "calls", "addr"], default="all")
    p.add_argument("--limit", type=int, default=40)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("explain")
    p.add_argument("address")
    p.set_defaults(func=cmd_explain)

    p = sub.add_parser("callers")
    p.add_argument("address")
    p.set_defaults(func=cmd_callers)

    p = sub.add_parser("strings")
    p.add_argument("pattern", nargs="?", default="")
    p.add_argument("--limit", type=int, default=40)
    p.set_defaults(func=cmd_strings)

    p = sub.add_parser("unit")
    p.add_argument("bank")
    p.set_defaults(func=cmd_unit)

    sub.add_parser("units").set_defaults(func=cmd_units)

    p = sub.add_parser("suggest")
    p.add_argument("--limit", type=int, default=25)
    p.set_defaults(func=cmd_suggest)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
