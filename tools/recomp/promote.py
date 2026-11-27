#!/usr/bin/env python3
"""Promote hot Unicorn fallbacks into the default native build.

The host already records every guest entry that fell back to Unicorn.  This
command turns that feedback into a new entry set:

  1. take the game.exe fallbacks from the last run (or explicit addresses);
  2. close over direct calls so the promoted functions do not immediately
     fall back again;
  3. write a new P-code subset and re-emit the startup build;
  4. gate on `verify --changed`;
  5. rebuild the host and run the tutorial, reporting the new fallback count.

The entry set lives in ``work/recomp-dev/entry-set.json`` and the generated C in
``work/smr-entry-generated``.  A copy of the previous generated directory is
kept under ``work/recomp-dev/backups/`` so a failed promotion can be reverted.

    ./scripts/recomp promote --dry-run
    ./scripts/recomp promote
    ./scripts/recomp promote 0x5c88f0 --no-closure
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import common, run, verify

SUBSET = common.WORK / "smr-entrypoints.jsonl"
EMIT = common.RUNTIME / "tools" / "translate" / "emit.py"
GAME_LO, GAME_HI = 0x400000, 0x1080000


def in_game(address: int) -> bool:
    return GAME_LO <= address < GAME_HI


def call_graph() -> dict[int, list[int]]:
    """entry -> direct in-game call/branch targets, cached by P-code file identity."""
    cache_path = common.ensure_dev() / "callgraph.json"
    stat = common.PCODE.stat()
    cached = common.load_json(cache_path, None)
    if cached and cached.get("size") == stat.st_size and cached.get("mtime") == int(stat.st_mtime):
        return {int(key): value for key, value in cached["calls"].items()}

    calls: dict[int, list[int]] = {}
    with common.PCODE.open("rb") as handle:
        for line in handle:
            if not line.startswith(b'{"entry":'):
                continue
            fn = json.loads(line)
            entry = fn["entry"]
            if not in_game(entry):
                continue
            targets = set()
            for insn in fn.get("insns", []):
                for opcode, _, inputs in insn.get("ops", []):
                    if opcode not in ("CALL", "BRANCH", "CBRANCH"):
                        continue
                    if not inputs or inputs[0] is None or inputs[0][0] != "const":
                        continue
                    target = inputs[0][1]
                    if in_game(target):
                        targets.add(target)
            calls[entry] = sorted(targets)
    common.save_json(
        cache_path,
        {"size": stat.st_size, "mtime": int(stat.st_mtime),
         "calls": {str(k): v for k, v in calls.items()}},
    )
    return calls


def load_entry_set() -> set[int]:
    data = common.load_json(common.DEV / "entry-set.json", None)
    if data and data.get("addresses"):
        return {int(a) for a in data["addresses"]}
    if SUBSET.is_file():
        return {json.loads(line)["entry"] for line in SUBSET.open()}
    return set()


def pcode_entries() -> set[int]:
    from . import status

    return set(status.pcode_index())


def closure(roots: set[int], calls: dict[int, list[int]], known: set[int], limit: int) -> set[int]:
    seen = set(roots)
    queue = list(roots)
    while queue and len(seen) < limit:
        current = queue.pop(0)
        for target in calls.get(current, ()):
            if target in seen or target not in known:
                continue
            seen.add(target)
            queue.append(target)
            if len(seen) >= limit:
                break
    return seen


STATE_FILES = ("entry-set.json", "smr-entrypoints.jsonl", "smr-entrypoints.jsonl.userops.json")


def state_path(name: str) -> Path:
    return (common.DEV if name == "entry-set.json" else common.WORK) / name


def backup_state(generated: Path) -> Path | None:
    if not (generated / "table.c").is_file() and not any(state_path(n).is_file() for n in STATE_FILES):
        return None
    backups = common.ensure_dev() / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    target = backups / f"entry-{time.strftime('%Y%m%d-%H%M%S')}"
    target.mkdir(parents=True, exist_ok=True)
    exists = {}
    if (generated / "table.c").is_file():
        shutil.copytree(generated, target / "generated", dirs_exist_ok=True)
    for name in STATE_FILES:
        source = state_path(name)
        exists[name] = source.is_file()
        if source.is_file():
            shutil.copy2(source, target / name)
    common.save_json(target / "manifest.json", exists)
    keep = sorted(backups.glob("entry-*"))[:-6]
    for old in keep:
        shutil.rmtree(old, ignore_errors=True)
    return target


def restore_state(backup: Path, generated: Path):
    """Put the entry set and generated C back after a failed promotion."""
    failed = backup.parent / f"failed-{time.strftime('%Y%m%d-%H%M%S')}"
    if (generated / "table.c").is_file():
        shutil.copytree(generated, failed / "generated", dirs_exist_ok=True)
    if (backup / "generated").is_dir():
        shutil.rmtree(generated, ignore_errors=True)
        shutil.copytree(backup / "generated", generated)
    exists = common.load_json(backup / "manifest.json", {}) or {}
    for name in STATE_FILES:
        destination = state_path(name)
        if exists.get(name):
            shutil.copy2(backup / name, destination)
        elif destination.exists():
            destination.unlink()
    for old in sorted(backup.parent.glob("failed-*"))[:-2]:
        shutil.rmtree(old, ignore_errors=True)


def write_subset(addresses: set[int]) -> int:
    tmp = SUBSET.with_suffix(".jsonl.tmp")
    wanted = set(addresses)
    written = 0
    prefix = b'{"entry":'
    with common.PCODE.open("rb") as source, tmp.open("wb") as out:
        for line in source:
            if not line.startswith(prefix):
                continue
            end = line.find(b",", len(prefix))
            if end < 0:
                continue
            if int(line[len(prefix):end]) in wanted:
                out.write(line)
                written += 1
    if written != len(wanted):
        tmp.unlink(missing_ok=True)
        common.fail(f"only {written} of {len(wanted)} entries were found in {common.PCODE.name}")
    os.replace(tmp, SUBSET)
    userops = common.WORK / "smr-fixed.jsonl.userops.json"
    if userops.is_file():
        shutil.copyfile(userops, SUBSET.with_suffix(".jsonl.userops.json"))
    return written


def emit_subset(generated: Path) -> dict:
    proc = subprocess.run(
        [common.python(), str(EMIT), str(SUBSET), str(generated)],
        cwd=str(common.ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if proc.returncode != 0:
        tail = "\n".join(proc.stdout.splitlines()[-25:])
        common.fail(f"emit failed:\n{tail}", 1)
    report = common.emit_report(generated)
    return report


def rebuild() -> tuple[bool, str]:
    """Build the windowed host: the promotion experiment validates the tutorial run."""
    env = os.environ.copy()
    env["SMR_BUILD_ONLY"] = "1"
    env["SMR_WINDOW"] = "1"
    code, out, elapsed, timed_out = common.run_with_timeout(
        [str(common.STARTUP_PROBE)], env=env, timeout=900
    )
    if code != 0 or timed_out:
        print(out[-3000:], file=os.sys.stderr)
        return False, "failed"
    reused = compiled = "?"
    for line in out.splitlines():
        if "Native objects:" in line:
            parts = line.replace(",", "").split()
            try:
                reused, compiled = parts[2], parts[4]
            except (IndexError, ValueError):
                pass
    return True, f"{common.seconds(elapsed)} ({reused} cached / {compiled} compiled)"


def main(argv=None):
    parser = argparse.ArgumentParser(prog="recomp promote", description=__doc__.splitlines()[0])
    parser.add_argument("addresses", nargs="*", help="guest addresses (default: game.exe fallbacks from the last run)")
    parser.add_argument("--dry-run", action="store_true", help="show the promotion set without changing anything")
    parser.add_argument("--no-closure", action="store_true", help="do not add direct callees")
    parser.add_argument("--max-add", type=int, default=512, help="cap on the promoted closure")
    parser.add_argument("--no-run", action="store_true", help="stop after verify and build")
    parser.add_argument("--no-build", action="store_true", help="emit and verify only")
    parser.add_argument("--keep-on-failure", action="store_true", help="leave the failed entry set in place")
    parser.add_argument("--revert", action="store_true", help="restore a previous entry set and rebuild")
    parser.add_argument("--from-backup", type=Path, help="backup directory for --revert (default: newest)")
    parser.add_argument("--force", action="store_true", help="promote even if verify reports a real mismatch")
    args = parser.parse_args(argv)

    if args.revert:
        backups = sorted((common.ensure_dev() / "backups").glob("entry-*"))
        backup = args.from_backup.resolve() if args.from_backup else (backups[-1] if backups else None)
        if not backup or not backup.is_dir():
            common.fail("no backup to restore")
        source = backup / "generated" if (backup / "generated" / "table.c").is_file() else backup
        if not (source / "table.c").is_file():
            common.fail(f"no generated C in {backup}")
        generated = common.VARIANTS["entry"]["generated"]
        shutil.rmtree(generated, ignore_errors=True)
        shutil.copytree(source, generated)
        addresses = set(common.table_addresses(generated))
        written = write_subset(addresses)
        common.save_json(
            common.DEV / "entry-set.json",
            {"updated": time.strftime("%Y-%m-%dT%H:%M:%S"), "addresses": sorted(addresses)},
        )
        print()
        print(f"  restored      {written} entries from {backup.relative_to(common.ROOT)}")
        if args.no_build:
            print()
            return 0
        code = verify.main(["--changed"])
        if code != 0 and not args.force:
            common.fail("restored set did not verify", code)
        ok, detail = rebuild()
        if not ok:
            common.fail("host rebuild failed", 1)
        print(f"  rebuilt       {detail}")
        print()
        return 0

    if not common.PCODE.is_file() or not EMIT.is_file():
        common.fail("missing P-code export or emit.py")

    last = common.load_json(common.DEV / "last-run.json", {}) or {}
    if args.addresses:
        requested = set(common.parse_int_list(" ".join(args.addresses)))
        source = "command line"
    else:
        requested = {int(a) for a in last.get("fallback_exe", [])}
        source = "last run"
        if not requested:
            common.fail("no game.exe fallbacks in work/recomp-dev/last-run.json")

    known = pcode_entries()
    outside = sorted(a for a in requested if not in_game(a))
    unexported = sorted(a for a in requested if in_game(a) and a not in known)
    roots = {a for a in requested if in_game(a) and a in known}

    print()
    print(f"  source        {source}: {len(requested)} address(es)")
    if outside:
        print("  ignored       not game.exe: " + ", ".join(f"0x{a:x}" for a in outside))
    if unexported:
        print(
            "  needs export  not in P-code: "
            + ", ".join(f"0x{a:x}" for a in unexported)
            + "  (run a DumpPcode pass first)"
        )
    if not roots:
        common.fail("nothing promotable")

    current = load_entry_set()
    add = roots - current
    if not args.no_closure:
        add = closure(add, call_graph(), known, args.max_add) - current
    if not add:
        print("  already native")
        print()
        return 0

    names = {}
    preview = sorted(add)
    if args.dry_run:
        with common.PCODE.open("rb") as handle:
            wanted = set(preview)
            for line in handle:
                if not line.startswith(b'{"entry":'):
                    continue
                fn = json.loads(line)
                if fn["entry"] in wanted:
                    names[fn["entry"]] = fn.get("name", "?")
        for address in preview:
            print(f"    + 0x{address:<8x} {names.get(address, '')}")
        print()
        print(f"  would add     {len(add)} function(s), {len(current)} -> {len(current | add)}")
        print()
        return 0

    print(f"  promoting     {len(add)} function(s), {len(current)} -> {len(current | add)}")
    generated = common.VARIANTS["entry"]["generated"]
    backup = backup_state(generated)
    if backup:
        print(f"  backup        {backup.relative_to(common.ROOT)}")

    entry_set = current | add
    written = write_subset(entry_set)
    common.save_json(
        common.DEV / "entry-set.json",
        {"updated": time.strftime("%Y-%m-%dT%H:%M:%S"), "addresses": sorted(entry_set)},
    )
    try:
        report = emit_subset(generated)
    except SystemExit:
        if backup and not args.keep_on_failure:
            restore_state(backup, generated)
            print("  restored      previous entry set after emit failure", file=os.sys.stderr)
        raise
    print(f"  emitted       {report.get('emitted', '?')} functions, {report.get('skipped', 0)} skipped")

    code = verify.main(["--changed"])
    if code != 0 and not args.force:
        if backup and not args.keep_on_failure:
            restore_state(backup, generated)
            print("  restored      previous entry set; failed C kept under backups/failed-*", file=os.sys.stderr)
        common.fail("verification failed; the host was not rebuilt", code)
    if args.no_build:
        print()
        return 0

    ok, detail = rebuild()
    if not ok:
        if backup and not args.keep_on_failure:
            restore_state(backup, generated)
            print("  restored      previous entry set after rebuild failure", file=os.sys.stderr)
        common.fail("host rebuild failed", 1)
    print(f"  rebuilt       {detail}")

    if args.no_run:
        print()
        return 0

    before = last
    code = run.main(["--to", "tutorial", "--no-build"])
    after = common.load_json(common.DEV / "last-run.json", {}) or {}
    print()
    print("  promotion result")
    old = set(before.get("fallback_exe", []))
    new = set(after.get("fallback_exe", []))
    print(
        f"    game.exe fallbacks  {len(old)} -> {len(new)}"
        + (f"  (remaining: {', '.join(f'0x{a:x}' for a in sorted(new))})" if new else "")
    )
    old_perf = (before.get("perf") or {}).get("fps")
    new_perf = (after.get("perf") or {}).get("fps")
    if old_perf and new_perf:
        print(f"    fps                 {old_perf} -> {new_perf} ({new_perf - old_perf:+.1f})")

    progress = len(new) < len(old)
    regressed = bool(old_perf and new_perf and new_perf < old_perf - 1.0)
    if (regressed or not progress) and backup and not args.force:
        restore_state(backup, generated)
        ok, detail = rebuild()
        print()
        print(
            "  reverted      promotion did not pay off ("
            + ("slower" if regressed else "no fallback progress")
            + "); restored the previous entry set"
        )
        if ok:
            print(f"  rebuilt       {detail}")
        print()
        return 1
    print()
    return 0 if code == 0 else 1
