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
        try:
            detail = str(path.relative_to(common.ROOT))
        except ValueError:
            detail = str(path)
        required_ok &= check(label, path.exists(), detail)

    for variant, spec in common.VARIANTS.items():
        check(
            f"generated ({variant})",
            (spec["generated"] / "table.c").is_file(),
            str(spec["generated"].relative_to(common.ROOT)),
            required=variant == "entry",
        )

    for label, path in [
        ("vc90 DLLs", common.DATA / "vc90" / "dlls"),
        ("D3DX DLLs", common.DATA / "d3dx"),
        ("game binaries", common.DATA / "installed" / "app" / "ShootManyRobots" / "Binaries"),
    ]:
        detail = str(path)
        try:
            detail = str(path.relative_to(common.ROOT))
        except ValueError:
            pass
        check(label, path.is_dir(), detail, required=False)

    check(
        "vendored runtime",
        (common.RUNTIME / "tools" / "startup_build.py").is_file(),
        str(common.RUNTIME.relative_to(common.ROOT)),
    )

    usage = shutil.disk_usage(common.WORK if common.WORK.exists() else common.ROOT)
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
