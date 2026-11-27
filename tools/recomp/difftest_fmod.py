"""Compare lifted fmodex.dll / fmod_event.dll audio helpers with x86.

The samples are the mixer DSP helpers FMOD's background thread runs on every
buffer: SSE stereo accumulation, the MMX PACKSSDW float -> int16 converter, the
RCPSS/RCPPS resampler, an x87 vector lerp and a thiscall constructor. Each is a
leaf function (no imports, no TEB), so a fixture that seeds its arguments and
buffers is enough to compare the translation against the original code.
"""
import json
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "work"
STACK_ARGS = 0x2fff8004
DST, SRC = 0x20001000, 0x20002000
MODULES = [
    ("fmodex", 0x13000000, {"executable": "fmodex.dll"}),
    ("fmod_event", 0x13200000, {"executable": "fmod_event.dll"}),
]


def write(address, fmt, *values):
    return {"address": address, "hex": struct.pack("<" + fmt, *values).hex()}


def sha256(path):
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fmodex_cases(case):
    # 0x1308a360: dst[2i] += mono[i] * left; dst[2i+1] += mono[i] * right.
    for i in range(4):
        frames = 5 + 2 * i
        case(0x1308a360, write(STACK_ARGS, "IIIff", SRC, DST, frames, 0.5 + i / 4, 1.0 - i / 8),
             write(SRC, f"{frames + 8}f", *[0.125 * (i + j) for j in range(frames + 8)]),
             write(DST, f"{2 * frames + 16}f", *[0.25 * j for j in range(2 * frames + 16)]))
    # 0x1308a41c: same accumulation for an interleaved stereo source.
    for i in range(4):
        frames = 7 + i
        case(0x1308a41c, write(STACK_ARGS, "IIIff", SRC, DST, frames, 0.25 + i / 4, 0.75),
             write(SRC, f"{2 * frames + 16}f", *[0.0625 * (i + j) for j in range(2 * frames + 16)]),
             write(DST, f"{2 * frames + 16}f", *[0.5 * j for j in range(2 * frames + 16)]))
    # 0x1308a8f0: MMX CVTTPS2PI + PACKSSDW conversion, including saturation.
    samples = [[0.5 * i for i in range(16)],
               [40000.0, -40000.0, 1.0, -1.0, 32767.0, -32768.0, 3.5, -3.5, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0],
               [-1e9, 1e9, 0.0, -0.0, 0.25, -0.25, 123.75, -123.75, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]]
    for i in range(4):
        count = 5 + i
        case(0x1308a8f0, write(STACK_ARGS, "IIIIIf", DST, SRC, count, 1 + i % 2, 1, 0.5 + i / 4),
             write(SRC, "16f", *samples[i % 3]), write(DST, "16I", *range(16)))
    # 0x1308a9e0: RCPSS/RCPPS envelope resampler over a * b samples.
    for i in range(4):
        count = 7 + 4 * i
        case(0x1308a9e0, write(STACK_ARGS, "IIIIIf", SRC, DST, count, 1, 0, 0.5 + i / 4),
             write(SRC, f"{count + 8}f", *[0.5 * j + 1 for j in range(count + 8)]),
             write(DST, f"{count + 8}I", *range(count + 8)))
        case(0x1308a9e0, write(STACK_ARGS, "IIIIIf", SRC, DST, 3, 5 + i, 0, 1.0),
             write(SRC, "24f", *[0.25 * j + 1 for j in range(24)]),
             write(DST, "24I", *range(24)))


def fmod_event_cases(case):
    # 0x13214100: dst[0..1] = lerp of the two 3-vectors at src, factor in arg 3.
    for i in range(4):
        case(0x13214100, write(STACK_ARGS, "IIf", DST, SRC, 0.25 * i),
             write(SRC, "8f", *[1.5 * (i + j) - 2 for j in range(8)]),
             write(DST, "8f", *[-0.5 * j for j in range(8)]))
    # 0x13235fd0: thiscall constructor; ECX is `this`, four 0x4c-byte blocks are built.
    for i in range(4):
        case(0x13235fd0,
             write(DST, "8I", 0, 0x3F800000, 0x3F800000, 0x100 + i,
                   0x40 + i, 0, 0, 0),
             registers={"ECX": DST})


def main():
    fixtures = ROOT / "work"
    commands = []
    reports = {}
    for name, _, meta in MODULES:
        project = WORK / f"ghidra-{name}"
        entries = {}

        def case(entry, *writes, _entries=entries, **fixture):
            entry_fixture = {"df": 0, "writes": list(writes)}
            entry_fixture.update(fixture)
            _entries.setdefault(hex(entry), []).append(entry_fixture)

        if name == "fmodex":
            fmodex_cases(case)
        else:
            fmod_event_cases(case)

        spec = fixtures / f"{name}-fixtures.json"
        spec.write_text(json.dumps({
            "executable_sha256": sha256(project / meta["executable"]),
            "entries": entries}))
        report = fixtures / f"{name}-diff.json"
        reports[name] = (report, set(entries))
        commands.append([sys.executable, str(ROOT / "tools/recomp/difftest_full.py"),
                         str(project / meta["executable"]),
                         str(WORK / "window-host-full/libfnv-differential.dylib"),
                         str(project / "functions.jsonl.regs.json"), str(report),
                         "--jobs", "2", "--trials", "4", "--fixtures", str(spec),
                         "--only", ",".join(entries)])

    for command in commands:
        subprocess.run(command, check=True)
    for name, (report, expected) in reports.items():
        results = json.loads(report.read_text())["results"]
        covered = {hex(r["entry"]) for r in results if r["valid"] > 0}
        if covered != expected:
            raise SystemExit(f"Incomplete {name} sample")
        if any(r["verdict"] != "pass" for r in results):
            raise SystemExit(f"{name} mismatches")
        print(f"{name}: {len(results)} sampled functions, 0 real mismatches")


if __name__ == "__main__":
    main()
