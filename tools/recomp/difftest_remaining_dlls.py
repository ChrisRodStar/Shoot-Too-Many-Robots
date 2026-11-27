"""Compare leaf functions from the remaining runtime DLLs with the original x86.

The 7 DLLs lifted for the zero-Unicorn workstream used to run through the
Unicorn fallback.  Each sample below is a leaf: it calls no imports and touches
no TEB/GS state, so a randomized register/memory fixture is enough to execute
the same inputs on both sides.  Division helpers get non-zero divisors from the
deterministic seed; the string/CRT helpers read the harness scratch heap.

Run after a --full build:

    .venv/bin/python tools/recomp/difftest_remaining_dlls.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "work"
DYLD = WORK / "window-host-full" / "libfnv-differential.dylib"
DIFFTEST = ROOT / "tools" / "recomp" / "difftest_full.py"

# (module, dll in its Ghidra project, {entry: description})
MODULES = [
    (
        "physxloader",
        "PhysXLoader.dll",
        {
            0x1000481B: "CPtoLCID: locale-id lookup",
            0x10005260: "_strlen: CRT string length",
            0x100054C0: "__aulldvrm: unsigned 64-bit divide/remainder",
        },
    ),
    (
        "cudart",
        "cudart32_30_9.dll",
        {
            0x11004D00: "cudaCreateChannelDesc: channel-descriptor store",
        },
    ),
    (
        "physxcooking",
        "PhysXCooking.dll",
        {
            0x11805512: "__hw_cw: x87 control-word helper",
            0x11807325: "siglookup: signal-table lookup",
            0x1180EE60: "__aulldvrm: unsigned 64-bit divide/remainder",
        },
    ),
    (
        "physxdevice",
        "PhysXDevice.dll",
        {
            0x119013D0: "physxDevClose: close device",
            0x119015B0: "physxDevErrorString: error-string switch",
            0x119059A0: "_strcspn: CRT span",
            0x11905AA0: "_strcmp: CRT compare",
            0x11905EA0: "_strlen: CRT string length",
        },
    ),
    (
        "d3dcompiler",
        "d3dcompiler_43.dll",
        {
            0x121ECE10: "__aulldvrm: unsigned 64-bit divide/remainder",
            0x121ECFC0: "__allmul: signed 64-bit multiply",
            0x121ED0A0: "__alldiv: signed 64-bit divide",
            0x121ED150: "__aulldiv: unsigned 64-bit divide",
            0x121ED2D0: "__alldvrm: signed 64-bit divide/remainder",
        },
    ),
    (
        "msvcp90",
        "msvcp90.dll",
        {
            0x78484EB9: "char_traits::eq",
            0x78484ED6: "char_traits::lt",
            0x78484F9C: "char_traits::to_char_type",
            0x78484FE3: "char_traits::not_eof",
            0x7848D935: "basic_string::length",
        },
    ),
    (
        "msvcr90",
        "msvcr90.dll",
        {
            0x7855B8E0: "strcmp: CRT compare",
            0x7855B9C0: "strlen: CRT string length",
            0x7855C0E0: "__allmul: signed 64-bit multiply",
            0x7855C1E0: "__allshl: signed 64-bit shift",
            0x7855C240: "__aulldiv: unsigned 64-bit divide",
            0x7855C350: "__aullrem: unsigned 64-bit remainder",
        },
    ),
]

REAL_MISMATCH = {"fail", "crash", "invalid"}


def main() -> int:
    if not DYLD.is_file():
        raise SystemExit(f"missing {DYLD}; build the merged full host first")
    total = 0
    mismatches = []
    for name, dll_name, entries in MODULES:
        project = WORK / f"ghidra-{name}"
        dll = project / dll_name
        regs = project / "functions.jsonl.regs.json"
        if not dll.is_file() or not regs.is_file():
            raise SystemExit(f"missing lifted {name} sources under {project}")
        report = WORK / f"{name}-remaining-diff.json"
        command = [
            sys.executable, str(DIFFTEST), str(dll), str(DYLD), str(regs), str(report),
            "--jobs", "2", "--trials", "4", "--only", ",".join(hex(e) for e in entries),
        ]
        # difftest_full exits non-zero on flags-only as well; inspect the report instead.
        subprocess.run(command, check=False)
        results = json.loads(report.read_text())["results"]
        covered = {result["entry"] for result in results}
        missing = set(entries) - covered
        if missing:
            raise SystemExit(f"{name}: missing results for " + ", ".join(hex(e) for e in sorted(missing)))
        bad = [result for result in results if result["verdict"] in REAL_MISMATCH or result["valid"] == 0]
        if bad:
            for result in bad:
                print(
                    f"{name}: {hex(result['entry'])} {result['verdict']} "
                    f"valid={result['valid']} {result['detail']}",
                    file=sys.stderr,
                )
            mismatches.extend(bad)
        total += len(results)
        verdicts = {}
        for result in results:
            verdicts[result["verdict"]] = verdicts.get(result["verdict"], 0) + 1
        summary = ", ".join(f"{key} {value}" for key, value in sorted(verdicts.items()))
        print(f"{name}: {len(results)} sampled functions ({summary})")
    if mismatches:
        raise SystemExit(f"{len(mismatches)} real mismatches")
    print(f"remaining runtime DLLs: {total} sampled functions, 0 real mismatches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
