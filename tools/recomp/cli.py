#!/usr/bin/env python3
"""Backend for ./scripts/recomp — the static-recompilation dev loop."""
from __future__ import annotations

import argparse
import sys

from . import doctor, explain, promote, run, status, verify

COMMANDS = {
    "status": status.main,
    "verify": verify.main,
    "run": run.main,
    "build": None,  # handled below
    "promote": promote.main,
    "explain": explain.main,
    "clean": None,  # handled below
    "doctor": doctor.main,
}


def clean(rest) -> int:
    """Drop rebuildable caches; never touches the guest, generated C or run history."""
    import argparse
    import shutil
    from pathlib import Path

    from . import common

    parser = argparse.ArgumentParser(prog="recomp clean")
    parser.add_argument("--all", action="store_true", help="also drop run summaries and verify results")
    args = parser.parse_args(rest)
    freed = 0

    def drop(path):
        nonlocal freed
        if not path.exists():
            return
        if path.is_dir():
            for root, _, files in os.walk(path):
                for name in files:
                    try:
                        freed += (Path(root) / name).stat().st_size
                    except OSError:
                        pass
            shutil.rmtree(path)
        else:
            freed += path.stat().st_size
            path.unlink()

    drop(common.DEV / "testlib")
    for pattern in ("tu-*.json", "pcode-index.json", "verify-*.json", "verify-*-last.json"):
        for path in common.DEV.glob(pattern):
            drop(path)
    if args.all:
        for pattern in ("last-run.json", "runs.jsonl"):
            drop(common.DEV / pattern)
        drop(common.DEV / "runs")
    print(f"recomp clean: freed {common.human_size(freed)}" + (" (everything)" if args.all else ""))
    return 0


def usage() -> str:
    return """recomp — static-recompilation dev loop

usage: ./scripts/recomp <command> [options]

  status                 coverage, last run, last equivalence check, next action
  verify [addresses...]  offline native-vs-x86 differential test (no game launch)
  run [--to tutorial]    build (incrementally) and run the guest hands-free
  promote [addresses]    make hot Unicorn fallbacks native, then verify + run
  build [--full]         rebuild the host only, with cache statistics
  explain <address>      original instructions, calls, generated C, last verdict
  clean [--all]          drop rebuildable caches (testlib, indexes, reports)
  doctor                 check local inputs and tools

common examples:
  ./scripts/recomp verify                     check the startup subset
  ./scripts/recomp verify --changed           only what was recompiled since last time
  ./scripts/recomp verify --full              check every exported game function
  ./scripts/recomp verify 0x83ed3e --all      one function, full failure detail
  ./scripts/recomp verify --failures          re-run the last failures
  ./scripts/recomp explain 0x83ed3e            why did this one mismatch?
  ./scripts/recomp promote --dry-run          what would become native?
  ./scripts/recomp promote                    take the last run's fallbacks native
  ./scripts/recomp run --to tutorial          build + boot + summarize
  ./scripts/recomp run --to tutorial --full   same with all 46k functions native
  ./scripts/recomp build --full               rebuild only

Run './scripts/recomp <command> --help' for command-specific help.
"""


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(usage())
        return 0
    command, rest = argv[0], argv[1:]
    if command not in COMMANDS:
        print(f"recomp: unknown command '{command}'\n", file=sys.stderr)
        print(usage(), file=sys.stderr)
        return 2
    if command == "build":
        return run.main(["--build-only", *rest])
    if command == "clean":
        return clean(rest)
    return COMMANDS[command](rest)


if __name__ == "__main__":
    raise SystemExit(main())
