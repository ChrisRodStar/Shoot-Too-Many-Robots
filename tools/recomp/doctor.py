#!/usr/bin/env python3
"""Check the local inputs and tools the recomp loop needs."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys

from . import common


def check(label: str, ok: bool, detail: str = "", required: bool = True) -> bool:
    mark = "ok  " if ok else ("warn" if not required else "FAIL")
    print(f"  [{mark}] {label:<24} {detail}")
    return ok or not required


def main(argv=None):
    print()
    print("  recomp doctor")
    print()
    required_ok = True

    required_ok &= check(
        "host",
        platform.system() == "Darwin" and platform.machine() == "arm64",
        f"{platform.system()} {platform.machine()}",
    )
    clang = shutil.which("clang")
    required_ok &= check("clang", bool(clang), clang or "not found")
    required_ok &= check("sandbox-exec", os.path.exists("/usr/bin/sandbox-exec"), "/usr/bin/sandbox-exec")
    py = common.python()
    try:
        version = subprocess.check_output([py, "-c", "import sys;print(sys.version.split()[0])"], text=True).strip()
        modules = subprocess.check_output(
            [py, "-c", "import unicorn,numpy;print(unicorn.__version__, numpy.__version__)"], text=True
        ).strip()
        python_ok = True
        detail = f"{version} · unicorn/numpy {modules}"
    except (OSError, subprocess.CalledProcessError) as exc:
        python_ok = False
        detail = f"{py}: {exc}"
    required_ok &= check("diagnostic python", python_ok, detail)

    for label, path in [
        ("guest executable", common.EXE),
        ("P-code export", common.PCODE),
        ("register layout", common.REGS),
        ("upstream rt.h", common.UPSTREAM / "rt.h"),
        ("differential harness", common.DIFFTEST),
        ("startup host", common.STARTUP_PROBE),
    ]:
        required_ok &= check(label, path.exists(), str(path.relative_to(common.ROOT)))

    for variant, spec in common.VARIANTS.items():
        check(
            f"generated ({variant})",
            (spec["generated"] / "table.c").is_file(),
            str(spec["generated"].relative_to(common.ROOT)),
            required=variant == "entry",
        )

    for label, path in [
        ("vc90 DLLs", common.WORK / "vc90" / "dlls"),
        ("D3DX DLLs", common.WORK / "d3dx"),
        ("game binaries", common.WORK / "installed" / "app" / "ShootManyRobots" / "Binaries"),
    ]:
        check(label, path.is_dir(), str(path.relative_to(common.ROOT)), required=False)

    if (common.RUNTIME / ".git").is_dir():
        patch = common.ROOT / "patches" / "macos-startup-host.patch"
        applied = subprocess.run(
            ["git", "-C", str(common.RUNTIME), "apply", "--reverse", "--check", str(patch)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0
        can_apply = subprocess.run(
            ["git", "-C", str(common.RUNTIME), "apply", "--check", str(patch)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0
        check("host patch", applied or can_apply, "applied" if applied else "will apply on next run")

    usage = shutil.disk_usage(common.WORK)
    check(
        "disk space",
        usage.free > 10 * 2**30,
        f"{common.human_size(usage.free)} free under work/",
        required=False,
    )

    print()
    print("  next: ./scripts/recomp status")
    print()
    return 0 if required_ok else 1
