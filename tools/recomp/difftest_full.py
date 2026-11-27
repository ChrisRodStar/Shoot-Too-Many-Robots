#!/usr/bin/env python3
"""Run the upstream differential harness with the guest's *whole* address space mapped.

The pinned harness maps only the image, a scratch heap, a stack and the TEB.  A
randomized pointer that lands anywhere else makes the original x86 fault, so a
large share of functions are reported "untestable" for a reason that does not
exist in the real host: the host maps all 4 GB (``MEM`` in ``rt.h``).

This wrapper adds the missing regions as lazily-zeroed anonymous mappings while
deliberately leaving the import-thunk window (0xFEE00000..0xFEE10000) unmapped.
Calls into Windows APIs therefore still fail cleanly on both sides instead of
silently executing zeros.

It reuses the pinned ``difftest.py`` unmodified; only the Worker subclass and the
worker respawn path are local.  The import window is the same magic the upstream
harness already installs in the PE's IAT.
"""
from __future__ import annotations

import ctypes
import importlib.util
import mmap
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIFFTEST = ROOT / "vendor" / "macos-runtime" / "tools" / "differential" / "difftest.py"

spec = importlib.util.spec_from_file_location("difftest_upstream", DIFFTEST)
upstream = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = upstream
spec.loader.exec_module(upstream)

from unicorn import UC_PROT_ALL  # noqa: E402


def aligned(n: int) -> int:
    return (n + 0xFFF) & ~0xFFF


class FullMemoryWorker(upstream.Worker):
    """Upstream Worker plus the unmapped gaps of the 4 GB guest address space."""

    def __init__(self, exe, lib, regs):
        super().__init__(exe, lib, regs)
        # The PE is packed and may write outside its declared writable sections.
        # Reset the whole image (not just IMAGE_SCN_MEM_WRITE) for every trial.
        self.pristine = {self.image_base: self.img}
        image_end = self.image_base + aligned(len(self.img))
        windows = [
            (0, self.image_base),
            (image_end, upstream.SCRATCH),
            (upstream.SCRATCH + upstream.SCRATCH_SIZE, upstream.STACK),
            (upstream.STACK + upstream.STACK_SIZE, upstream.TEB),
            (upstream.TEB + upstream.TEB_SIZE, upstream.IAT_MAGIC),
            (upstream.IAT_MAGIC + 0x10000, 1 << 32),
        ]
        self._gaps = []
        self._libc = ctypes.CDLL(None)
        for base, end in windows:
            size = end - base
            if size <= 0:
                continue
            buffer = mmap.mmap(-1, size, flags=mmap.MAP_ANON | mmap.MAP_PRIVATE,
                               prot=mmap.PROT_READ | mmap.PROT_WRITE)
            pointer = ctypes.addressof(ctypes.c_char.from_buffer(buffer))
            try:
                self.mu.mem_map_ptr(base, size, UC_PROT_ALL, pointer)
            except Exception as exc:  # pragma: no cover - platform dependent
                print(f"recomp: could not map {base:#x}..{end:#x}: {exc}", file=sys.stderr)
                buffer.close()
                continue
            self._gaps.append((base, size, buffer))

    def _reset_gaps(self):
        """Drop pages touched by the previous trial.

        The randomized regions are re-poked by every trial, but the full-memory
        gaps are not: without this, a function that writes into guest heap space
        leaves state for the next function, and native/x86 diverge for reasons
        that have nothing to do with the translation.  MADV_DONTNEED zero-fills
        anonymous pages lazily on both engines and costs ~2 ms for the full map.
        """
        for base, size, buffer in self._gaps:
            buffer.madvise(mmap.MADV_DONTNEED)
            if self.mem:
                self._libc.madvise(ctypes.c_void_p(self.mem + base), ctypes.c_size_t(size), 4)

    def trial(self, entry, rng):
        self._reset_gaps()
        return super().trial(entry, rng)


# run_pool() respawns the interpreter with this module's __file__, and worker_main
# constructs `upstream.Worker`; both see the subclass.
upstream.Worker = FullMemoryWorker
upstream.__file__ = str(Path(__file__).resolve())


def judge(entry, results):
    """Upstream's judge can report a flags-only detail on a verdict of `fail`.

    Keep the same verdict rules but prefer the actual mismatch detail, and keep
    the per-trial verdicts so `verify` can show which input diverged.
    """
    valid = [item for item in results if item[0] != "invalid"]
    if not valid:
        verdict = "untestable"
    elif any(item[0] == "fail" for item in valid):
        verdict = "fail"
    elif any(item[0] == "flags" for item in valid):
        verdict = "flags-only"
    else:
        verdict = "pass"
    detail = next((item[1] for item in valid if item[0] == "fail"), "")
    if not detail:
        detail = next((item[1] for item in valid if item[0] == "flags"), "")
    if not valid and results:
        detail = results[0][1]
    return {"entry": entry, "verdict": verdict, "valid": len(valid), "detail": detail,
            "trial_verdicts": [item[0] for item in results]}


upstream.judge = judge

# With the whole space mapped, a wild jump can now execute zero bytes instead of
# faulting.  Cap the wasted instruction budget well below the upstream 2M default:
# a real recompiled function is orders of magnitude shorter, and trials that hit
# the cap are still reported as invalid rather than passing.
upstream.BUDGET = int(os.environ.get("SMR_DIFF_BUDGET", "250000"))

if __name__ == "__main__":
    sys.exit(upstream.main())
