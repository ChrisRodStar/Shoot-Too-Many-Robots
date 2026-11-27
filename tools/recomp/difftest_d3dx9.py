"""Compare the June 2010 D3DX9 scalar math path and an effect method with x86."""
import json
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "work"
PROJECT = WORK / "ghidra-d3dx9"
STACK_ARGS = 0x2fff8004
DST, SRC = 0x20001000, 0x20002000


def write(address, fmt, *values):
    return {"address": address, "hex": struct.pack("<" + fmt, *values).hex()}


def main():
    entries = {}

    def case(entry, args, *memory):
        entries.setdefault(hex(entry), []).append({"df": 0, "writes": [args, *memory]})

    # The DLL's CPU selector at 0x124469f2 copies its scalar function table
    # into writable slots, then installs the Vec3 helper at 0x1244705e.
    # Supply this initialized state on both sides without running Windows APIs.
    for i in range(4):
        case(0x12418777, write(STACK_ARGS, "II", 32, 43 + i))  # D3DXCheckVersion
        case(0x1243409b, write(STACK_ARGS, "ff", 0.25 * i, 1.5))  # FresnelTerm
        case(0x12434050, write(STACK_ARGS, "IIf", DST, SRC, 0.5 + i / 4),
             write(SRC, "4f", 0.125, 0.25, 0.75, 1))  # ColorAdjustContrast
        case(0x12431174, write(STACK_ARGS, "II", DST, SRC),
             write(SRC, "16f", *range(i, i + 16)), write(0x125ca100, "I", 0x1243117f))
        # The fallback log identifies this effect method. Its bounds check
        # compares the index with this+0xc4 before indexing the technique array.
        case(0x124fb808, write(STACK_ARGS, "II", SRC, i), write(SRC + 0xc4, "II", 2, DST))
        for entry, slot, target, size in [
                (0x12433555, 0x125ca0bc, 0x12433560, 4),  # QuaternionNormalize
                (0x12433bc8, 0x125ca0c0, 0x12433bd3, 4),  # PlaneNormalize
                (0x124301d9, 0x125ca084, 0x12446d90, 3)]:  # Vec3Normalize
            values = [0.] * size
            values[i % size] = i + 1
            case(entry, write(STACK_ARGS, "II", DST, SRC), write(SRC, f"{size}f", *values),
                 write(slot, "I", target))

    fixtures = WORK / "d3dx9-fixtures.json"
    fixtures.write_text(json.dumps({
        "executable_sha256": "8f28dcef5d6f8ccb8b9d040c3a93281f8c28d631a40a2e2e6b77044af0ed333b",
        "entries": entries}))
    report = WORK / "d3dx9-diff.json"
    subprocess.run([sys.executable, str(ROOT / "tools/recomp/difftest_full.py"),
                    PROJECT / "d3dx9_43.dll", WORK / "window-host-full/libfnv-differential.dylib",
                    PROJECT / "functions.jsonl.regs.json", report, "--jobs", "2", "--trials", "4",
                    "--fixtures", fixtures, "--only", ",".join(entries)], check=True)
    results = json.loads(report.read_text())["results"]
    if {hex(r["entry"]) for r in results if r["valid"] > 0} != entries.keys():
        raise SystemExit("Incomplete D3DX9 sample")


if __name__ == "__main__":
    main()
