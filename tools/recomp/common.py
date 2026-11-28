"""Shared paths and parsers for the recomp dev-loop tools.

Everything here is project-local: nothing is copied into ``vendor/macos-runtime``
and nothing changes the pinned upstream checkout.  The tools read the artifacts
the existing pipeline already writes (generated C, emit reports, host logs).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "work"
VENDOR = ROOT / "vendor"
RUNTIME = VENDOR / "macos-runtime"
UPSTREAM = RUNTIME / "upstream" / "recomp"
HOST = UPSTREAM / "host"
LOCAL_HOST = ROOT / "src" / "host"
CONFIG = ROOT / "config"
# Shared read-only guest inputs and P-code exports. Override per worktree with
# SMR_DATA_ROOT; writable generated/build state always stays under ROOT/work.
DATA = Path(os.environ.get("SMR_DATA_ROOT", str(WORK))).expanduser()
INPUTS = DATA / "inputs"
LOGS = ROOT / "logs"
GHIDRA = WORK / "ghidra"
GENERATED = WORK / "generated"
BUILD = WORK / "build"
REPORTS = WORK / "reports"
RUN = WORK / "run"
DEV = WORK / "dev"
RUNS = DEV / "runs"
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
EXE = INPUTS / "exe" / "ShootManyRobots.exe"
PCODE = DATA / "pcode" / "smr-fixed.jsonl"
REGS = DATA / "pcode" / "smr-fixed.jsonl.regs.json"
DIFFTEST = RUNTIME / "tools" / "differential" / "difftest.py"
DIFFTEST_FULL = ROOT / "tools" / "recomp" / "difftest_full.py"
STARTUP_PROBE = ROOT / "scripts" / "startup-probe"

VARIANTS = {
    "entry": {
        "generated": GENERATED / "game-entry",
        "build": BUILD / "window-host",
        "cache": BUILD / "startup-cache",
        "description": "startup subset (fast, default)",
    },
    "full": {
        "generated": GENERATED / "game",
        "build": BUILD / "window-host-full",
        "cache": BUILD / "startup-full-cache",
        "description": "all 46k exported game functions",
    },
}

FALLBACK_RE = re.compile(r"fallback-root\] target=(0x[0-9a-f]+)")
PERF_RE = re.compile(r"^\[perf\] (.+)$", re.M)
METAL_RE = re.compile(r"\[metal\] frame (\d+): ([\d.]+) fps, (\d+) draws/frame")
ENTRY_STATE_RE = re.compile(r"\[entry-state\] entry=(0x[0-9a-f]+)")
THUNK_BASE = 0xFEE00000


def python() -> str:
    """Prefer the project venv (it is the one that has Unicorn + numpy)."""
    if VENV_PYTHON.is_file():
        return str(VENV_PYTHON)
    return sys.executable


def ensure_dev() -> Path:
    DEV.mkdir(parents=True, exist_ok=True)
    RUNS.mkdir(parents=True, exist_ok=True)
    return DEV


def fail(message: str, code: int = 2):
    print(f"recomp: {message}", file=sys.stderr)
    raise SystemExit(code)


def which(tool: str):
    return shutil.which(tool)


def run(cmd, *, env=None, timeout=None, cwd=None, check=False, capture=True):
    """Run a child in its own process group so a timeout can kill the whole tree."""
    started = time.monotonic()
    proc = subprocess.run(
        cmd,
        cwd=str(cwd or ROOT),
        env=env,
        timeout=timeout,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        start_new_session=True,
    )
    return proc, time.monotonic() - started


def run_with_timeout(cmd, *, env=None, timeout=None, cwd=None):
    """Like run() but kills the process group on timeout instead of leaking a window."""
    import signal

    started = time.monotonic()
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd or ROOT),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        out, _ = proc.communicate(timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            out, _ = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            out, _ = proc.communicate()
    return proc.returncode, out or "", time.monotonic() - started, timed_out


def load_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def save_json(path: Path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    os.replace(tmp, path)


def human_size(n: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GiB"


def seconds(n: float) -> str:
    if n < 1:
        return f"{n * 1000:.0f} ms"
    if n < 120:
        return f"{n:.1f} s"
    return f"{n // 60:.0f}m {n % 60:.0f}s"


def table_addresses(generated: Path) -> list[int]:
    """Guest entry addresses, in dispatch-table order, parsed from the generated table."""
    table = Path(generated) / "table.c"
    if not table.is_file():
        return []
    text = table.read_text()
    match = re.search(r"const uint32_t rt_fn_addr\[\] = \{([^}]*)\}", text)
    if not match:
        return []
    return [int(value, 16) for value in re.findall(r"0x([0-9a-fA-F]+)u?", match.group(1))]


def emit_report(generated: Path) -> dict:
    return load_json(Path(generated) / "emit_report.json", {}) or {}


def module_of(addr: int) -> str:
    """Coarse module bucket for a guest address (enough for a dashboard)."""
    if 0x00400000 <= addr < 0x01080000:
        return "game.exe"
    if addr >= THUNK_BASE and addr < THUNK_BASE + 0x10000:
        return "imports"
    known = {
        0x10000000: "PhysXLoader.dll",
        0x11000000: "cudart32_30_9.dll",
        0x11400000: "PhysXCore.dll",
        0x11800000: "PhysXCooking.dll",
        0x11900000: "PhysXDevice.dll",
        0x12000000: "d3dcompiler_43.dll",
        0x12400000: "d3dx9_43.dll",
        0x13000000: "fmodex.dll",
        0x13200000: "fmod_event.dll",
        0x78480000: "msvcp90.dll",
        0x78520000: "msvcr90.dll",
    }
    best = None
    for base, name in known.items():
        if addr >= base and (best is None or base > best[0]):
            best = (base, name)
    return best[1] if best else f"guest@{addr >> 24:#x}"


def parse_int_list(text: str) -> list[int]:
    values = []
    for chunk in re.split(r"[,\s]+", text.strip()):
        if not chunk:
            continue
        values.append(int(chunk, 0))
    return values


def perf_summary(log_text: str) -> dict:
    """Last performance window plus the most interesting extremes."""
    windows = []
    for match in PERF_RE.finditer(log_text):
        fields = {}
        for token in match.group(1).split():
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            try:
                fields[key] = float(value)
            except ValueError:
                fields[key] = value
        windows.append(fields)
    if not windows:
        return {}
    last = windows[-1]
    intervals = [w.get("interval_ms") for w in windows if w.get("interval_ms")]
    return {
        "windows": len(windows),
        "fps": round(1000.0 / last["interval_ms"], 1) if last.get("interval_ms") else None,
        "fps_min": round(1000.0 / max(intervals), 1) if intervals else None,
        "fps_max": round(1000.0 / min(intervals), 1) if intervals else None,
        "main_cpu_ms": last.get("main_cpu_ms"),
        "gpu_ms": last.get("gpu_ms"),
        "draws": last.get("draws"),
        "compile_ms_total": last.get("compile_ms_total"),
        "footprint_mib": last.get("footprint_mib"),
    }


def parse_log(log_text: str, frames_dir: Path | None = None) -> dict:
    roots = [int(value, 16) for value in FALLBACK_RE.findall(log_text)]
    unique = sorted(set(roots))
    metal = METAL_RE.findall(log_text)
    fps_series = [(int(frame), float(fps), int(draws)) for frame, fps, draws in metal]
    entry_states = [int(value, 16) for value in ENTRY_STATE_RE.findall(log_text)]
    faults = [line.strip() for line in log_text.splitlines() if "[host] FAULT" in line]
    traps = [
        line.strip()
        for line in log_text.splitlines()
        if "[fallback] left executable guest code" in line or "engine nesting limit" in line
    ]
    captures = []
    if frames_dir and frames_dir.is_dir():
        captures = sorted(
            str(p.relative_to(ROOT)) for p in frames_dir.glob("frame_*.png")
        )
    return {
        "fallback_roots": unique,
        "fallback_counts": dict(Counter(hex(a) for a in roots)),
        "fallback_exe": [a for a in unique if module_of(a) == "game.exe"],
        "fallback_by_module": dict(Counter(module_of(a) for a in roots)),
        "fps_series": fps_series,
        "draws_max": max((d for _, _, d in fps_series), default=0),
        "draws_last": fps_series[-1][2] if fps_series else 0,
        "entry_states": sorted(set(entry_states)),
        "faults": faults,
        "traps": traps,
        "captures": captures,
        "perf": perf_summary(log_text),
    }
