#!/usr/bin/env python3
"""One deterministic, summarized run of the guest.

The old loop was: edit, rebuild, launch, click through the menus, watch frames,
quit, then guess whether anything changed.  This command keeps the same host
but makes the run reproducible and machine-readable:

  * a checked-in input script drives title -> tutorial (no manual clicking)
  * a wall-clock timeout kills the whole process tree instead of leaking it
  * the log is parsed into draws / fps / CPU / GPU / fallbacks / faults
  * the result is compared with the previous run, so a change is measurable
  * frames and logs are kept in the shared artifact directories as before

Examples:

    ./scripts/recomp run --to tutorial
    ./scripts/recomp run --to tutorial --full
    ./scripts/recomp run --to tutorial --verify      # equivalence gate first
    ./scripts/recomp run --build-only
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import time
from pathlib import Path

from . import common, verify

SCRIPTS = {
    "tutorial": common.ROOT / "scripts" / "smr-tutorial.script",
    "title": common.ROOT / "scripts" / "smr-title.script",
}

MODE_ENV = {
    "window": {"SMR_WINDOW": "1"},
    "metal": {"SMR_METAL": "1"},
    "headless": {},
}


def variant_flags(variant: str) -> dict:
    return {"SMR_FULL": "1"} if variant == "full" else {}


def artifacts(variant: str, mode: str) -> tuple[Path, Path | None]:
    suffix = "-full" if variant == "full" else ""
    if mode == "window":
        return (
            common.BOOT / f"window{suffix}-startup.log",
            common.BOOT / f"window{suffix}-frames",
        )
    if mode == "metal":
        return common.BOOT / f"native{suffix}-startup.log", common.BOOT / f"metal{suffix}-frames"
    return common.BOOT / f"native{suffix}-startup.log", None


def probe_env(args) -> dict:
    env = os.environ.copy()
    env.update(MODE_ENV[args.mode])
    env.update(variant_flags(args.variant))
    if args.no_build:
        env["SMR_SKIP_BUILD"] = "1"
    if args.to and args.mode == "window":
        script = Path(args.script) if args.script else SCRIPTS.get(args.to)
        if script and script.is_file():
            env["FNV_INPUT_SCRIPT"] = str(script)
    elif args.script:
        env["FNV_INPUT_SCRIPT"] = str(Path(args.script))
    if args.frames:
        env["FNV_DUMP_FRAMES"] = args.frames
    if args.trace:
        env["SMR_TRACE"] = "1"
    if args.seconds:
        env["SMR_PROBE_SECONDS"] = str(args.seconds)
    return env


def build(args) -> tuple[int, float, str]:
    env = probe_env(args)
    env["SMR_BUILD_ONLY"] = "1"
    code, out, elapsed, _ = common.run_with_timeout([str(common.STARTUP_PROBE)], env=env, timeout=3600)
    if code != 0:
        print(out[-4000:], end="", file=os.sys.stderr)
        common.fail(f"build failed (exit {code})", 1)
    reused = compiled = "?"
    for line in out.splitlines():
        if "Native objects:" in line:
            parts = line.replace(",", "").split()
            try:
                reused, compiled = parts[2], parts[4]
            except (IndexError, ValueError):
                pass
    return code, elapsed, f"{reused} cached / {compiled} compiled"


def previous_run() -> dict:
    return common.load_json(common.DEV / "last-run.json", {}) or {}


def delta_line(label, before, after, unit="", better="higher"):
    if before is None or after is None:
        return f"  {label:<16} {after}{unit}"
    change = after - before
    if abs(change) < 0.05:
        mark = "="
    elif (change > 0) == (better == "higher"):
        mark = "+"
    else:
        mark = "-"
    return f"  {label:<16} {after:.1f}{unit}  ({mark}{abs(change):.1f} vs previous)"


def summarize(variant, mode, log_path, frames_dir, elapsed, timed_out, exit_code, before, started_at) -> dict:
    text = log_path.read_text(errors="replace") if log_path.is_file() else ""
    parsed = common.parse_log(text)
    if frames_dir and frames_dir.is_dir():
        parsed["captures"] = sorted(
            str(p.relative_to(common.ROOT))
            for p in frames_dir.glob("frame_*.png")
            if p.stat().st_mtime >= started_at - 1
        )
        parsed["frames_dir"] = str(frames_dir.relative_to(common.ROOT))
    else:
        parsed["frames_dir"] = None
    perf = parsed["perf"]
    entry = {
        "when": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "host": socket.gethostname(),
        "variant": variant,
        "mode": mode,
        "entry_size": len(common.table_addresses(common.VARIANTS[variant]["generated"])),
        "exit": exit_code,
        "timed_out": timed_out,
        "elapsed_s": round(elapsed, 1),
        "log": str(log_path.relative_to(common.ROOT)) if log_path.is_file() else None,
        "frames_dir": str(frames_dir.relative_to(common.ROOT)) if frames_dir else None,
        **parsed,
    }
    previous = before or {}
    same_setup = (
        previous.get("variant") == variant
        and previous.get("mode") == mode
        and previous.get("entry_size") == entry["entry_size"]
    )
    old_fallbacks = set(previous.get("fallback_roots", [])) if same_setup else set()
    new_fallbacks = [a for a in parsed["fallback_roots"] if a not in old_fallbacks] if same_setup else []
    entry["new_fallbacks"] = new_fallbacks

    print()
    print(f"  run            {variant}/{mode} — exit {exit_code}" + (" (timeout)" if timed_out else ""))
    print(f"  wall time      {common.seconds(elapsed)}")
    if not perf:
        print("  no [perf] windows were recorded")
        print(f"  log            {entry['log'] or '(missing)'}")
        return entry

    fps_line = (
        f"  fps            {perf['fps']} (range {perf['fps_min']}–{perf['fps_max']} over "
        f"{perf['windows']} windows)"
    )
    previous_perf = previous.get("perf") or {}
    comparable = bool(
        previous_perf
        and previous.get("variant") == variant
        and previous.get("mode") == mode
        and previous.get("entry_size") == entry["entry_size"]
    )
    if previous_perf and not comparable:
        print("  (previous run used a different variant/mode/native set; deltas omitted)")
    if comparable and previous_perf.get("fps") is not None and perf.get("fps") is not None:
        fps_line += f"  · {perf['fps'] - previous_perf['fps']:+.1f} vs previous"
    print(fps_line)
    if comparable:
        print(delta_line("main cpu", previous_perf.get("main_cpu_ms"), perf["main_cpu_ms"], " ms", "lower"))
        print(delta_line("gpu", previous_perf.get("gpu_ms"), perf["gpu_ms"], " ms", "lower"))
    print(f"  draws           last {parsed['draws_last']}, peak {parsed['draws_max']}")
    if perf.get("compile_ms_total"):
        print(f"  shader compile  {perf['compile_ms_total']:.0f} ms in window")
    if parsed["captures"]:
        print(f"  frames          {len(parsed['captures'])} dumped under {frames_dir.relative_to(common.ROOT)}")
    if parsed["fallback_roots"]:
        by_module = ", ".join(
            f"{name} {count}" for name, count in sorted(parsed["fallback_by_module"].items())
        )
        print(f"  fallbacks       {len(parsed['fallback_roots'])} unique ({by_module})")
        if variant == "entry":
            print("                  (the default build still interprets some paths; use --full for fps)")
        if parsed["fallback_exe"]:
            print(
                "  game.exe gaps   "
                + ", ".join(f"0x{a:x}" for a in parsed["fallback_exe"][:10])
            )
        if new_fallbacks:
            print("  new fallbacks   " + ", ".join(f"0x{a:x}" for a in new_fallbacks[:10]))
    else:
        print("  fallbacks       none (everything ran native)")
    if parsed["faults"]:
        print("  faults          " + parsed["faults"][0])
    if parsed["traps"]:
        print(f"  traps           {len(parsed['traps'])}")
    if parsed["entry_states"]:
        print(f"  entry states    {len(parsed['entry_states'])} captured")
    print(f"  log             {entry['log']}")
    return entry


def main(argv=None):
    parser = argparse.ArgumentParser(prog="recomp run", description=__doc__.splitlines()[0])
    parser.add_argument("--full", action="store_true", help="use the full 46k-function build")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--window", dest="mode", action="store_const", const="window", help="AppKit window (default)")
    group.add_argument("--metal", dest="mode", action="store_const", const="metal", help="offscreen Metal probe")
    group.add_argument("--headless", dest="mode", action="store_const", const="headless", help="no GPU renderer")
    parser.set_defaults(mode="window")
    parser.add_argument("--to", choices=["tutorial", "title"], help="drive the checked-in input script")
    parser.add_argument("--script", help="custom input script (overrides --to)")
    parser.add_argument("--frames", help="FNV_DUMP_FRAMES value, e.g. 1,300,600")
    parser.add_argument("--seconds", type=int, help="headless probe time limit (default 60)")
    parser.add_argument("--timeout", type=int, default=360, help="kill the run after this many seconds")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--no-build", action="store_true", help="launch the existing binary")
    parser.add_argument("--verify", action="store_true", help="gate on the changed translation units before launching")
    parser.add_argument("--trace", action="store_true", help="log individual Windows API calls")
    args = parser.parse_args(argv)

    if not common.STARTUP_PROBE.is_file():
        common.fail(f"missing {common.STARTUP_PROBE}")
    args.variant = "full" if args.full else "entry"
    if args.to and args.mode != "window":
        common.fail("--to only applies to windowed runs (input scripts are driven by presents)")
    if args.to and args.script:
        common.fail("choose either --to or --script")

    if args.verify:
        args_for_verify = ["--changed"] + (["--full"] if args.full else [])
        code = verify.main(args_for_verify)
        if code != 0:
            common.fail("equivalence gate failed; not launching the guest", code)

    if not args.no_build:
        print(f"recomp build: {args.variant}", file=os.sys.stderr)
        _, build_elapsed, stats = build(args)
        print(f"  built in {common.seconds(build_elapsed)} ({stats})")
        if args.build_only:
            return 0
    elif args.build_only:
        common.fail("--build-only and --no-build are mutually exclusive")

    log_path, frames_dir = artifacts(args.variant, args.mode)
    if frames_dir:
        frames_dir.mkdir(parents=True, exist_ok=True)
    before = previous_run()
    if args.mode == "window" and not log_path.is_file():
        # The host writes this file; its absence after a failure is still informative.
        pass

    print(f"recomp run: {args.variant}/{args.mode}", file=os.sys.stderr)
    wall_start = time.time()
    code, out, elapsed, timed_out = common.run_with_timeout(
        [str(common.STARTUP_PROBE)], env=probe_env(args), timeout=args.timeout
    )
    if timed_out:
        print(
            f"recomp: run exceeded {args.timeout}s and was terminated "
            "(the input script may not have reached its quit step)",
            file=os.sys.stderr,
        )
    entry = summarize(
        args.variant, args.mode, log_path, frames_dir, elapsed, timed_out, code, before, wall_start
    )
    entry["script"] = args.script or (f"{args.to}" if args.to else None)

    common.save_json(common.DEV / "last-run.json", entry)
    with (common.DEV / "runs.jsonl").open("a") as handle:
        handle.write(json.dumps(entry) + "\n")
    run_dir = common.RUNS / time.strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    if log_path.is_file():
        shutil.copy2(log_path, run_dir / "startup.log")
    common.save_json(run_dir / "summary.json", entry)
    print(f"  saved           {run_dir.relative_to(common.ROOT)}")
    return 1 if timed_out else 0
