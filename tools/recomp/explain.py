#!/usr/bin/env python3
"""Show one guest function: original instructions, calls, generated C, last verdict.

Useful the moment `verify` reports a mismatch, because it puts the P-code, the
translation and the test result in one place.

    ./scripts/recomp explain 0x83ed3e
    ./scripts/recomp explain 0x83ed3e --calls
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from . import common, verify


def pcode_entry(address: int) -> dict:
    cache = common.load_json(common.ensure_dev() / "pcode-index.json", None)
    if not common.PCODE.is_file():
        common.fail(f"missing {common.PCODE}")
    stat = common.PCODE.stat()
    if not cache or cache.get("size") != stat.st_size:
        from . import status

        status.pcode_index()
        cache = common.load_json(common.ensure_dev() / "pcode-index.json", {})
    offset = (cache.get("entries") or {}).get(str(address)) or (cache.get("entries") or {}).get(address)
    if offset is None:
        return {}
    with common.PCODE.open("rb") as handle:
        handle.seek(int(offset))
        return json.loads(handle.readline())


def generated_source(variant: str, address: int) -> tuple[Path | None, str]:
    generated = common.VARIANTS[variant]["generated"]
    files, _ = verify.tu_manifest(variant, generated)
    owner = None
    for name, info in files.items():
        if address in info.get("addresses", []):
            owner = generated / name
            break
    if owner is None:
        return None, ""
    text = owner.read_text(errors="replace")
    start = text.find(f"void g_{address:x}(CPU *c){{")
    if start < 0:
        return owner, ""
    following = text.find("\nvoid g_", start + 10)
    end = following if following > 0 else len(text)
    block = text[start:end]
    lines = block.splitlines()
    if len(lines) > 60:
        lines = lines[:60] + [f"/* … {len(block.splitlines()) - 60} more lines in {owner.name} */"]
    return owner, "\n".join(lines)


def last_verdict(address: int) -> tuple[str, dict]:
    for variant in ("entry", "full"):
        data = common.load_json(common.DEV / f"verify-{variant}-last.json", None)
        if not data:
            continue
        for item in data.get("results", []):
            if int(item["entry"]) == address:
                return variant, item
    return "", {}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="recomp explain", description=__doc__.splitlines()[0])
    parser.add_argument("address", help="guest entry address, e.g. 0x83ed3e")
    parser.add_argument("--full", action="store_true", help="look in the full build for the C")
    parser.add_argument("--calls", action="store_true", help="list direct call targets")
    parser.add_argument("--max-insns", type=int, default=40)
    args = parser.parse_args(argv)

    address = common.parse_int_list(args.address)[0]
    fn = pcode_entry(address)
    if not fn:
        common.fail(f"0x{address:x} is not a function entry in the P-code export")

    print()
    print(f"  0x{address:x}  {fn.get('name', '?')}  ({len(fn.get('insns', []))} instructions)")

    calls = []
    for insn in fn.get("insns", []):
        for opc, _, inputs in insn.get("ops", []):
            if opc in ("CALL", "CALLIND") and inputs:
                target = inputs[0]
                if target and target[0] == "const":
                    calls.append(target[1])
    if calls:
        unique = sorted(set(calls))
        print(
            "  calls       "
            + ", ".join(f"0x{c:x}" for c in unique[:24])
            + (f" … {len(unique) - 24} more" if len(unique) > 24 else "")
        )
    if args.calls:
        from collections import Counter

        for target, count in sorted(Counter(calls).items()):
            print(f"             0x{target:<8x} x{count}")

    variant = "full" if args.full else "entry"
    owner, source = generated_source(variant, address)
    if owner:
        print(f"  source      {owner.relative_to(common.ROOT)}")
    print()
    insns = fn.get("insns", [])[: args.max_insns]
    for insn in insns:
        print(f"    0x{insn['a']:<8x} {insn['m']}")
    if len(fn.get("insns", [])) > len(insns):
        print(f"    … {len(fn['insns']) - len(insns)} more")

    if source:
        print()
        print("  translated C")
        for line in source.splitlines():
            if len(line) > 400 and line.lstrip().startswith("void g_"):
                print("    " + line[: line.index("{") + 1] + " … declarations …")
            elif len(line) > 240:
                print("    " + line[:240] + " …")
            else:
                print("    " + line)

    variant, result = last_verdict(address)
    if result:
        category, reason = verify.classify(result, strict_harness=False)
        print()
        print(f"  last verify {variant}: {category}" + (f" — {reason}" if reason else ""))
    print()
    return 0
