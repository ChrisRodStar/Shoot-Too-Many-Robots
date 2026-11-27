#!/usr/bin/env python3
"""Coverage and health dashboard for the port.

Shows what is actually native, what still falls back to Unicorn, what the last
run and the last equivalence check said, and the next concrete action.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from . import common


def pcode_index() -> dict:
    """Guest address -> byte offset in the P-code JSONL, cached by file identity."""
    cache_path = common.ensure_dev() / "pcode-index.json"
    if not common.PCODE.is_file():
        return {}
    stat = common.PCODE.stat()
    cached = common.load_json(cache_path, None)
    if cached and cached.get("size") == stat.st_size and cached.get("mtime") == int(stat.st_mtime):
        return {int(k): v for k, v in cached["entries"].items()}
    entries = {}
    offset = 0
    prefix = b'{"entry":'
    with common.PCODE.open("rb") as handle:
        for line in handle:
            if line.startswith(prefix):
                end = line.find(b",", len(prefix))
                if end > 0:
                    entries[int(line[len(prefix):end])] = offset
            offset += len(line)
    common.save_json(cache_path, {"size": stat.st_size, "mtime": int(stat.st_mtime), "entries": entries})
    return entries


def last_run() -> tuple[dict, Path | None, bool]:
    """Return (summary, log path, is_live_fallback)."""
    data = common.load_json(common.DEV / "last-run.json", None)
    if data:
        return data, common.ROOT / data["log"] if data.get("log") else None, False
    logs = sorted(common.LOGS.glob("window*-startup.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs:
        logs = sorted(common.LOGS.glob("native*-startup.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs:
        return {}, None, False
    log = logs[0]
    parsed = common.parse_log(log.read_text(errors="replace"))
    parsed.update(
        {
            "when": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(log.stat().st_mtime)),
            "variant": "full" if "full" in log.name else "entry",
            "mode": "window" if log.name.startswith("window") else "headless",
            "log": str(log.relative_to(common.ROOT)),
        }
    )
    return parsed, log, True


def dir_size(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return total


def main(argv=None):
    parser = argparse.ArgumentParser(prog="recomp status", description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    run, run_log, live = last_run()
    full_missing: list[int] = []
    index = pcode_index()
    report = {"run": run, "variants": {}, "verify": {}}

    print()
    print("  Shoot Too Many Robots — recomp status")
    print()
    inputs_ok = common.EXE.is_file()
    pcode_note = f"{len(index):,} functions" if index else "missing"
    print(f"  guest input    {'game.exe present' if inputs_ok else 'game.exe MISSING'} · pcode {pcode_note}")

    for variant, spec in common.VARIANTS.items():
        addresses = common.table_addresses(spec["generated"])
        emit = common.emit_report(spec["generated"])
        binaries = sorted(spec["build"].glob("fnv-*")) if spec["build"].is_dir() else []
        binaries = [p for p in binaries if p.is_file() and os.access(p, os.X_OK)]
        built_at = (
            time.strftime("%Y-%m-%d %H:%M", time.localtime(max(p.stat().st_mtime for p in binaries)))
            if binaries
            else "not built"
        )
        info = {
            "addresses": len(addresses),
            "emitted": emit.get("emitted"),
            "skipped": emit.get("skipped"),
            "built": built_at,
        }
        report["variants"][variant] = info
        print(
            f"  {variant:<13} {len(addresses):>6} native · "
            f"{emit.get('emitted', '?'):>6} emitted · {emit.get('skipped', 0):>3} skipped · built {built_at}"
        )
        if emit.get("skipped_fns"):
            for item in emit["skipped_fns"][:8]:
                reason = item.get("reason") or str(item)
                reason = reason.replace("callother in", "I/O port read (`in`)").replace(
                    "callother out", "I/O port write (`out`)"
                )
                print(f"                skipped 0x{int(item.get('entry', 0)):x}: {reason}")

    def verify_line(label, path):
        data = common.load_json(path, None)
        if not data:
            return None
        summary = data.get("summary", {})
        breakdown = data.get("breakdown")
        if breakdown is None:
            detail = " · ".join(f"{k} {v}" for k, v in summary.items() if v)
        else:
            blocked = sum(v for k, v in breakdown.items() if k.startswith("blocked"))
            harness = sum(v for k, v in breakdown.items() if k.startswith("harness"))
            real = sum(v for k, v in breakdown.items() if k.startswith("fail")) + breakdown.get("crash", 0)
            detail = (
                f"pass {summary.get('pass', 0)} · flags-only {summary.get('flags-only', 0)}"
                f" · blocked {blocked} · harness {harness} · real {real}"
            )
        report["verify"][label] = {"when": data.get("when"), "selection": data.get("selection"), "detail": detail}
        print(
            f"  verify ({label:<5}) {data.get('when', '?')} · {data.get('selection', 'all')} · {detail}"
        )
        return data

    last_verify_path = common.DEV / "verify-entry-last.json"
    verify_line("entry", last_verify_path)
    verify_line("full", common.DEV / "verify-full-last.json")
    if run:
        perf = run.get("perf") or {}
        print()
        print(
            f"  last run       {run.get('when', '?')} · {run.get('variant', '?')}/{run.get('mode', '?')}"
            + (f" · exit {run['exit']}" if run.get("exit") is not None else "")
            + (" · live log (no summary yet)" if live else "")
        )
        if perf:
            print(
                f"                 {perf.get('fps')} fps · {run.get('draws_last') or perf.get('draws')} draws · "
                f"cpu {perf.get('main_cpu_ms')} ms · gpu {perf.get('gpu_ms')} ms"
            )
        faults = run.get("faults") or []
        traps = run.get("traps") or []
        print(f"                 faults {len(faults)} · traps {len(traps)} · log {run.get('log')}")
        roots = run.get("fallback_roots") or []
        by_module = run.get("fallback_by_module") or {}
        if roots:
            detail = ", ".join(f"{name} {count}" for name, count in sorted(by_module.items()))
            print(f"                 fallbacks {len(roots)} unique ({detail})")
            exe = run.get("fallback_exe") or []
            if exe:
                missing = [a for a in exe if a not in index]
                print(
                    "                 game.exe gaps "
                    + ", ".join(f"0x{a:x}" for a in exe[:12])
                    + (f"  ({len(exe)} total)" if len(exe) > 12 else "")
                )
                if missing:
                    print(
                        "                 not in pcode export: "
                        + ", ".join(f"0x{a:x}" for a in missing)
                        + " (needs an export pass)"
                    )
        else:
            print("                 fallbacks none — every dispatched function was native")

    # The full build is the reference for what is still missing from the game image.
    full_log = common.LOGS / "window-full-startup.log"
    full_gaps = []
    if full_log.is_file() and (not run_log or full_log.resolve() != run_log.resolve()):
        full_gaps = common.parse_log(full_log.read_text(errors="replace")).get("fallback_exe") or []
    elif run.get("variant") == "full":
        full_gaps = run.get("fallback_exe") or []
    if full_gaps:
        missing = [a for a in full_gaps if a not in index]
        full_missing = missing
        print(
            "  full-mode gaps "
            + ", ".join(f"0x{a:x}" for a in full_gaps)
            + (
                "  · not in P-code export: " + ", ".join(f"0x{a:x}" for a in missing)
                if missing
                else "  · all exported (emit/skip is the gap)"
            )
        )

    testlib = common.DEV / "testlib"
    if testlib.is_dir():
        print()
        print(f"  dev caches     testlib {common.human_size(dir_size(testlib))} · verify reports in work/recomp-dev/")

    print()
    print("  next")
    if full_missing:
        print(
            "    export first: "
            + ", ".join(f"0x{a:x}" for a in full_missing)
            + " are not in the P-code export (re-run DumpPcode for their containing functions)"
        )
    if not last_verify_path.is_file():
        print("    ./scripts/recomp verify           # equivalence-check the startup subset offline")
    else:
        data = common.load_json(last_verify_path, {}) or {}
        breakdown = data.get("breakdown") or {}
        real = sum(v for k, v in breakdown.items() if k.startswith("fail")) + breakdown.get("crash", 0)
        if real:
            print("    ./scripts/recomp verify --failures --all")
        else:
            print("    ./scripts/recomp run --to tutorial   # hands-free boot to the tutorial")
    print("    ./scripts/recomp run --to tutorial --full   # same, using all 46k native functions")
    print()

    if args.json:
        print(json.dumps(report, indent=1))
    return 0
