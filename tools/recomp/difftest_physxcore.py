"""Compare a clean sample of lifted PhysXCore.dll leaf methods with x86."""
import json
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "work"
PROJECT = WORK / "ghidra-physxcore"
STACK_ARGS = 0x2fff8004
SELF = 0x20002000
DST = 0x20001000


def write(address, fmt, *values):
    return {"address": address, "hex": struct.pack("<" + fmt, *values).hex()}


def main():
    entries = {}

    def case(entry, *memory, registers=None):
        entries.setdefault(hex(entry), []).append({
            "df": 0,
            "registers": {"ECX": SELF, **(registers or {})},
            "writes": list(memory),
        })

    # Plain inline getters: the whole method is a load from a fixed offset.
    for entry, offset, value in [
            (0x114f0ce0, 0x1c, 0x114f0ce0),   # get1c
            (0x114f5a40, 0x48c, 0x115aecf0),  # Scene::get48c
            (0x11524df0, 0x1c, 0x11524df0),   # NpActor::getScene
            (0x1157e4e0, 0x10, 0x1157e4e0),   # Shape::get10
            (0x1157e520, 0x38, 0x1157e520),   # Shape::get38
            (0x115aecf0, 0x14c, 0x7f4a3c29),  # Body::getActorFlags
    ]:
        case(entry, write(SELF + offset, "I", value))

    # Boolean queries: both outcomes, including the flag-setting SETNZ path.
    case(0x11525f70, write(SELF + 0x20, "I", 1))  # NpActor::isDynamic body != 0
    case(0x11525f70, write(SELF + 0x20, "I", 0))  # NpActor::isDynamic null body
    case(0x115aed30, write(SELF + 0x1b8, "B", 1))  # Body::isSleeping
    case(0x115aed30, write(SELF + 0x1b8, "B", 0))
    case(0x115261c0, write(STACK_ARGS, "I", 0x20),
         write(SELF + 0x2c, "I", 0x3f))  # NpActor::readFlag2c
    case(0x115261c0, write(STACK_ARGS, "I", 0x10),
         write(SELF + 0x2c, "I", 0x3f))

    # Vector/quaternion copies: x87 loads from the object, stores to the out param.
    for entry, offset, size in [
            (0x115aeec0, 0x1a0, 3),  # Body::getLinearVelocity
            (0x115af100, 0x1c8, 4),  # Body::getGlobalOrientationQuat
            (0x115af130, 0x1bc, 3),  # Body::getGlobalPosition
    ]:
        values = [0.0] * size
        values[0] = 1.25
        values[-1] = -2.5
        case(entry, write(STACK_ARGS, "I", DST),
             write(SELF + offset, f"{size}f", *values))

    fixtures = WORK / "physxcore-fixtures.json"
    fixtures.write_text(json.dumps({
        "executable_sha256": "1128dc74963c3162247e03f4fc0dc669eae0c7ce3170e9204c49a46d140072f9",
        "entries": entries}))
    dylib = WORK / "window-host-full/libfnv-differential.dylib"
    if not dylib.is_file():
        raise SystemExit(f"missing {dylib}; build the merged full host first")
    report = WORK / "physxcore-diff.json"
    subprocess.run([sys.executable, str(ROOT / "tools/recomp/difftest_full.py"),
                    PROJECT / "PhysXCore.dll", dylib,
                    PROJECT / "functions.jsonl.regs.json", report, "--jobs", "2",
                    "--trials", "4", "--fixtures", fixtures,
                    "--only", ",".join(entries)], check=True)
    results = json.loads(report.read_text())["results"]
    if {hex(r["entry"]) for r in results if r["valid"] > 0} != entries.keys():
        raise SystemExit("Incomplete PhysXCore sample")


if __name__ == "__main__":
    main()
