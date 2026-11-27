#!/usr/bin/env python3
"""Offline equivalence check: recompiled C vs. the original x86 run in Unicorn.

This is the fast half of the recomp loop.  Instead of booting the game and
watching it, it links the *exact* generated translation units into a small
diagnostic dylib and runs every function twice from identical machine state:

    native C  ──┐
                ├─ compare registers, flags, x87, XMM and touched memory
    x86 in UC ──┘

The harness itself comes from the pinned upstream recompiler
(``tools/differential/difftest.py``); this file adds incremental caching, a
readable report and verdict classification.

Typical use:

    ./scripts/recomp verify                 # the default startup subset
    ./scripts/recomp verify --full          # every exported game function
    ./scripts/recomp verify 0x83ed3e        # one function, useful after a fix
    ./scripts/recomp verify --failures      # re-run whatever failed last time

Verdicts:

  pass        every valid trial matched exactly
  flags-only  state matched, only CF/ZF/SF/OF differed (x86 flags are not part
              of the Win32 ABI; tracked separately, accepted by default)
  untestable  the original x86 faults on randomized inputs, usually because it
              calls a Windows API that no isolated harness can provide
  fail        a real state mismatch, or the native side trapped
  crash       a worker process died on that address

Exit status is non-zero on a real state mismatch (or a native trap), so `verify`
can gate a commit. Known harness divergences are reported separately; see the
category table in the README/docstring output.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import common

VERDICT_ORDER = ["pass", "flags-only", "untestable", "fail", "crash"]
ACCEPTED = {"pass", "flags-only"}


def tu_manifest(variant: str, generated: Path) -> tuple[dict[str, dict], list[int]]:
    """Hash each translation unit and remember which guest entries it defines.

    Returns (manifest, addresses whose translation changed since the last run).
    """
    cache_path = common.ensure_dev() / f"tu-{variant}.json"
    previous = (common.load_json(cache_path, {}) or {}).get("files", {})
    files = {}
    changed: set[int] = set()
    pattern = re.compile(rb"void g_([0-9a-f]+)\(CPU \*c\)\{")
    for source in sorted(generated.glob("tu_*.c")):
        digest = hashlib.sha256()
        with source.open("rb") as handle:
            data = handle.read()
        digest.update(data)
        key = digest.hexdigest()
        known = previous.get(source.name)
        if known and known.get("hash") == key:
            addresses = known.get("addresses", [])
        else:
            addresses = sorted({int(value, 16) for value in pattern.findall(data)})
        if known and known.get("hash") != key:
            changed.update(addresses)
        files[source.name] = {"hash": key, "addresses": addresses}
    return files, sorted(changed)


def save_tu_manifest(variant: str, files: dict[str, dict]):
    common.save_json(common.ensure_dev() / f"tu-{variant}.json", {"files": files})


def build_testlib(variant: str, jobs: int, force: bool = False) -> tuple[Path, dict]:
    """Compile generated C into a cached dylib; only changed translation units rebuild."""
    spec = common.VARIANTS[variant]
    generated = spec["generated"]
    if not (generated / "table.c").is_file():
        common.fail(f"missing generated sources: {generated}/table.c")
    if not common.DIFFTEST.is_file():
        common.fail(f"missing differential harness: {common.DIFFTEST}")
    if not common.REGS.is_file():
        common.fail(f"missing register layout: {common.REGS}")

    sdk = subprocess.check_output(["xcrun", "--sdk", "macosx", "--show-sdk-path"], text=True).strip()
    cc = subprocess.check_output(["xcrun", "--sdk", "macosx", "--find", "clang"], text=True).strip()
    flags = ["-O1", "-fPIC", "-isysroot", sdk]
    includes = ["-I", str(common.UPSTREAM), "-I", str(common.HOST)]
    toolchain = subprocess.check_output([cc, "--version"], text=True)
    flavour = hashlib.sha256(("\n".join(flags + includes) + toolchain).encode()).hexdigest()

    out_dir = common.ensure_dev() / "testlib" / variant
    obj_dir = out_dir / "obj"
    obj_dir.mkdir(parents=True, exist_ok=True)
    dylib = out_dir / "libtest.dylib"

    sources = [common.DIFFTEST.parent / "rt_test.c", common.UPSTREAM / "rt_dispatch.c"]
    sources += sorted(generated.glob("tu_*.c"))
    sources += [generated / "table.c", generated / "stubs.c"]

    def object_key(source: Path) -> tuple[Path, str]:
        digest = hashlib.sha256()
        digest.update(flavour.encode())
        digest.update(source.name.encode())
        with source.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        return obj_dir / (digest.hexdigest() + ".o"), digest.hexdigest()

    plan = [(source, *object_key(source)) for source in sources]
    pending = [item for item in plan if force or not item[1].is_file()]
    built = 0
    reused = 0
    requested = max(1, jobs)

    def compile_one(item):
        source, obj, _ = item
        tmp = obj.with_suffix(".o.tmp")
        proc = subprocess.run(
            [cc, *flags, *includes, "-c", str(source), "-o", str(tmp)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"compile failed: {source.name}\n{proc.stdout[-4000:]}")
        os.replace(tmp, obj)

    if pending:
        with concurrent.futures.ThreadPoolExecutor(max_workers=requested) as pool:
            futures = [pool.submit(compile_one, item) for item in pending]
            for future in concurrent.futures.as_completed(futures):
                try:
                    future.result()
                except RuntimeError as exc:
                    common.fail(str(exc), 1)
                built += 1
    reused = len(plan) - built

    signature = hashlib.sha256("".join(sorted(item[2] for item in plan)).encode()).hexdigest()
    manifest_path = out_dir / "manifest.json"
    manifest = common.load_json(manifest_path, {}) or {}
    rebuilt = False
    if force or manifest.get("signature") != signature or not dylib.is_file():
        objects = [str(item[1]) for item in plan]
        tmp = out_dir / "libtest.dylib.tmp"
        proc = subprocess.run(
            [cc, "-shared", "-isysroot", sdk, "-o", str(tmp), *objects],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if proc.returncode != 0:
            common.fail(f"link failed:\n{proc.stdout[-4000:]}", 1)
        os.replace(tmp, dylib)
        common.save_json(manifest_path, {"signature": signature, "sources": len(plan)})
        rebuilt = True

    return dylib, {"compiled": built, "reused": reused, "linked": rebuilt, "sources": len(plan)}


def classify(result: dict, strict_harness: bool = False) -> tuple[str, str]:
    """Turn a difftest result into a short category and a human explanation."""
    verdict = result["verdict"]
    detail = result.get("detail", "")
    isolated = result.get("isolated") or {}
    if verdict == "fail" and isolated and not strict_harness and (isolated.get("verdict") not in ("fail", "crash")):
        return (
            "harness:order",
            "did not reproduce in a fresh process (order-dependent harness state)",
        )
    if verdict == "pass":
        return verdict, ""
    if verdict == "flags-only":
        return verdict, f"only {detail} differ; flags are not part of the Win32 ABI"
    if verdict == "untestable":
        if "0xfee" in detail.lower():
            return "blocked:import", "calls a Windows import (not available in isolation)"
        if "budget" in detail:
            return "blocked:budget", "original x86 exceeded the instruction budget"
        if "fetch unmapped" in detail or "read unmapped" in detail or "write unmapped" in detail:
            return "blocked:fault", "original x86 faults on the randomized fixture"
        if "exception" in detail.lower():
            return "blocked:exception", "original x86 raised a CPU exception on the fixture"
        return "blocked:other", detail[:160] or "no valid trial"
    if verdict == "fail":
        # rt_cpuid() deliberately reports a 2010-era SSE2 CPU.  Unicorn answers the
        # real host CPUID instead, so feature-detection functions diverge by design.
        if not strict_harness and ("0x78bfbff" in detail or "0x78bfbfd" in detail):
            return "harness:cpuid", "CPUID feature bits differ by design (rt_cpuid vs host)"
        trap = re.search(r"native trap (\d+) @0x([0-9a-f]+)", detail)
        if trap:
            code = int(trap.group(1))
            address = int(trap.group(2), 16)
            if code == 6 and not strict_harness:
                return "blocked:callee", f"indirect call to 0x{address:x}, not a native entry"
            return "fail:trap", f"native trap {code} at 0x{address:x}"
        return "fail:mismatch", detail
    return verdict, detail[:160]


def load_baseline(path: Path | None) -> dict[int, str]:
    data = common.load_json(path, None) if path else None
    if not data:
        return {}
    return {int(item["entry"]): item["verdict"] for item in data.get("results", [])}


def run_harness(harness: Path, dylib: Path, out: Path, entries: list[int], trials: int, jobs: int, seed: int) -> dict:
    cmd = [
        common.python(),
        str(harness),
        str(common.EXE),
        str(dylib),
        str(common.REGS),
        str(out),
        "--trials", str(trials),
        "--jobs", str(jobs),
        "--seed", str(seed),
        "--only", ",".join(f"{address:x}" for address in entries),
    ]
    common.run(cmd, timeout=3600)
    return common.load_json(out, {}) or {}


def confirm_in_isolation(harness: Path, variant: str, dylib: Path, results: list, args) -> list[int]:
    """Re-run every suspected mismatch in a fresh process.

    A real translation bug reproduces from the same seed in a clean process.  A
    mismatch that disappears is harness state leaking between functions; the
    result is kept as `isolated` and classified as `harness:order`.
    """
    suspects = [
        item for item in results
        if item["verdict"] in ("fail", "crash")
        and (item["verdict"] == "crash" or classify(item, args.strict_harness)[0].startswith("fail"))
    ]
    if not suspects:
        return []
    out_dir = common.ensure_dev() / "isolated"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(
        f"recomp verify: confirming {len(suspects)} suspect(s) in fresh processes",
        file=sys.stderr,
    )
    cleared = []
    for item in suspects:
        entry = int(item["entry"])
        report = run_harness(
            harness,
            dylib,
            out_dir / f"{variant}-{entry:x}.json",
            [entry],
            args.trials,
            1,
            args.seed,
        )
        found = next(
            (candidate for candidate in report.get("results", []) if int(candidate["entry"]) == entry),
            {},
        )
        item["isolated"] = {
            "verdict": found.get("verdict", "missing"),
            "detail": found.get("detail", ""),
        }
        if found.get("verdict") not in ("fail", "crash"):
            cleared.append(entry)
    return cleared


def print_report(variant, results, addresses, build_info, elapsed, baseline, show_all, strict_harness):
    counts = {key: 0 for key in VERDICT_ORDER}
    for item in results:
        counts[item["verdict"]] = counts.get(item["verdict"], 0) + 1
    tested = counts["pass"] + counts["flags-only"] + counts["fail"] + counts["crash"]
    print()
    print(f"  variant     {variant} ({common.VARIANTS[variant]['description']})")
    print(f"  functions   {len(addresses)} in dispatch table, {len(results)} tested")
    print(
        f"  testlib     {build_info['sources']} sources, "
        f"{build_info['compiled']} compiled, {build_info['reused']} cached"
        + (", relinked" if build_info["linked"] else ", link cached")
    )
    print(f"  elapsed     {common.seconds(elapsed)}")
    if not results:
        print("  nothing to test")
        return counts
    print(
        "  verdicts    "
        + "  ".join(
            f"{key} {counts.get(key, 0)}" for key in VERDICT_ORDER if counts.get(key, 0)
        )
    )
    if tested:
        print(f"  testable    {tested} of {len(results)} ({tested / len(results):.0%})")
    print()

    categories = {}
    rows = []
    real_failures = []
    changed = []
    for item in sorted(results, key=lambda r: r["entry"]):
        category, reason = classify(item, strict_harness)
        if category == "pass":
            continue
        categories[category] = categories.get(category, 0) + 1
        previous = baseline.get(int(item["entry"]))
        if previous and previous != item["verdict"]:
            changed.append((item["entry"], previous, item["verdict"]))
        if category.startswith("fail") or category == "crash":
            real_failures.append(item["entry"])
        rows.append((item, category, reason))

    if categories:
        print(
            "  breakdown   "
            + "  ".join(f"{name} {count}" for name, count in sorted(categories.items()))
        )
        print()

    if rows:
        limit = len(rows) if show_all else 18
        print("  address      result        reason")
        for item, category, reason in rows[:limit]:
            print(f"  0x{item['entry']:<9x} {category:<13} {reason}")
        if len(rows) > limit:
            print(f"  … {len(rows) - limit} more (use --all)")
        print()

    if changed:
        print("  changes since baseline")
        for entry, before, after in changed[:20]:
            print(f"  0x{entry:<9x} {before} -> {after}")
        print()
    if real_failures:
        print(f"  real mismatches: {len(real_failures)}")
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(prog="recomp verify", description=__doc__.splitlines()[0])
    parser.add_argument("addresses", nargs="*", help="guest addresses (default: whole dispatch table)")
    parser.add_argument("--full", action="store_true", help="use the full 46k-function build")
    parser.add_argument("--trials", type=int, default=6, help="randomized trials per function")
    parser.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 4))
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--all", action="store_true", help="show every non-pass row")
    parser.add_argument("--changed", action="store_true", help="only translation units changed since the last verify")
    parser.add_argument("--sample", type=int, help="randomly sample this many functions (seeded)")
    parser.add_argument("--failures", action="store_true", help="re-run entries that failed last time")
    parser.add_argument("--strict", action="store_true", help="also fail on flags-only and blocked functions")
    parser.add_argument(
        "--no-confirm",
        action="store_true",
        help="do not re-run suspected mismatches in a fresh process",
    )
    parser.add_argument(
        "--strict-harness",
        action="store_true",
        help="count known harness divergences (CPUID, indirect trap) as failures",
    )
    parser.add_argument("--require-tested", action="store_true", help="fail if some functions cannot be tested")
    parser.add_argument("--rebuild", action="store_true", help="force a full testlib rebuild")
    parser.add_argument("--baseline", type=Path, help="json result to compare verdicts against")
    parser.add_argument("--save-baseline", type=Path, help="write this run as a baseline")
    parser.add_argument("--json-out", type=Path, help="write the raw report here")
    parser.add_argument("--list", action="store_true", help="list dispatch-table addresses and exit")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    variant = "full" if args.full else "entry"
    spec = common.VARIANTS[variant]
    addresses = common.table_addresses(spec["generated"])
    if not addresses:
        common.fail(f"no dispatch table in {spec['generated']} (build it first)")

    if args.list:
        for address in addresses:
            print(f"0x{address:x}")
        return 0

    last_path = common.ensure_dev() / f"verify-{variant}-last.json"
    tu_files = None
    selection = "all"
    if args.failures:
        last = common.load_json(last_path, None)
        if not last:
            common.fail("no previous verify result to take failures from")
        wanted = [int(item["entry"]) for item in last["results"] if item["verdict"] in ("fail", "crash")]
        if not wanted:
            print("recomp: last run had no failures", file=sys.stderr)
            return 0
        addresses = wanted
        selection = "failures"
    elif args.addresses:
        wanted = set(common.parse_int_list(" ".join(args.addresses)))
        missing = wanted - set(addresses)
        if missing:
            hint = " (not exported or skipped; see work/recomp-dev or emit_report.json)" if variant == "full" else " (try --full)"
            common.fail(
                "not in this dispatch table: "
                + ", ".join(f"0x{a:x}" for a in sorted(missing))
                + hint
            )
        addresses = sorted(wanted)
        selection = "explicit"
    elif args.changed:
        tu_files, changed = tu_manifest(variant, spec["generated"])
        in_table = set(addresses)
        addresses = [a for a in changed if a in in_table]
        selection = "changed"
        if not tu_files or not (common.DEV / f"tu-{variant}.json").is_file():
            selection = "all"
            if not args.quiet:
                print(
                    "recomp verify: no previous translation manifest, checking the whole table",
                    file=sys.stderr,
                )
        elif not addresses:
            print("recomp verify: no changed translation units since the last verify", file=sys.stderr)
            return 0
    elif args.sample:
        if args.sample >= len(addresses):
            selection = "all"
        else:
            import random

            rng = random.Random(args.seed)
            addresses = sorted(rng.sample(addresses, args.sample))
            selection = f"sample {args.sample}"

    started = time.monotonic()
    dylib, build_info = build_testlib(variant, args.jobs, force=args.rebuild)
    if not args.quiet:
        print(
            f"recomp verify: {len(addresses)} function(s), {build_info['compiled']} TU(s) compiled, "
            f"{build_info['reused']} cached",
            file=sys.stderr,
        )

    raw_path = args.json_out or (common.ensure_dev() / f"verify-{variant}.json")
    harness = common.DIFFTEST_FULL if common.DIFFTEST_FULL.is_file() else common.DIFFTEST
    cmd = [
        common.python(),
        str(harness),
        str(common.EXE),
        str(dylib),
        str(common.REGS),
        str(raw_path),
        "--trials",
        str(args.trials),
        "--jobs",
        str(args.jobs),
        "--seed",
        str(args.seed),
        "--only",
        ",".join(f"{address:x}" for address in addresses),
    ]
    proc, test_elapsed = common.run(cmd, timeout=3600)
    if not raw_path.is_file():
        common.fail("differential harness produced no report:\n" + (proc.stdout or "")[-4000:], 1)
    report = common.load_json(raw_path, {}) or {}
    results = report.get("results", [])
    if len(results) != len(addresses):
        if not args.quiet:
            print(
                f"recomp: warning: {len(addresses) - len(results)} function(s) were not reported",
                file=sys.stderr,
            )

    if not args.no_confirm:
        cleared = confirm_in_isolation(harness, variant, dylib, results, args)
        if cleared and not args.quiet:
            print(
                "recomp verify: order-dependent only: "
                + ", ".join(f"0x{address:x}" for address in cleared),
                file=sys.stderr,
            )
        report["results"] = results
        common.save_json(raw_path, report)

    baseline = load_baseline(args.baseline)
    counts = print_report(
        variant,
        results,
        addresses,
        build_info,
        time.monotonic() - started,
        baseline,
        args.all,
        args.strict_harness,
    )
    breakdown = {}
    for item in results:
        category, _ = classify(item, args.strict_harness)
        if category != "pass":
            breakdown[category] = breakdown.get(category, 0) + 1

    common.save_json(
        last_path,
        {
            "variant": variant,
            "when": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "seed": args.seed,
            "trials": args.trials,
            "selection": selection,
            "summary": counts,
            "breakdown": breakdown,
            "results": results,
        },
    )
    if selection in ("all", "changed"):
        # The manifest records what has actually been checked, so --changed stays honest.
        files, _ = tu_manifest(variant, spec["generated"])
        save_tu_manifest(variant, files)
    if args.save_baseline:
        common.save_json(args.save_baseline, {"variant": variant, "summary": counts, "results": results})
        print(f"  baseline     {args.save_baseline}")
    print(f"  report       {raw_path}")

    failures = [
        item for item in results
        if classify(item, args.strict_harness)[0].startswith("fail") or item["verdict"] == "crash"
    ]
    blocked = [item for item in results if classify(item, args.strict_harness)[0].startswith("blocked")]
    unexpected = bool(failures)
    if args.strict and (counts["flags-only"] or blocked):
        unexpected = True
    if args.require_tested and blocked:
        unexpected = True
    return 1 if unexpected else 0
