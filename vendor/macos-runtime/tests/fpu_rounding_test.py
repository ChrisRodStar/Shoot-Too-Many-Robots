"""Unit tests for x87 FPUControlWord (FRND) and SSE MXCSR (MXRND) rounding in rt.h and emitters."""
from pathlib import Path
import importlib.util
import subprocess
import tempfile
from native_test_toolchain import COMPILER, PLATFORM_FLAGS, LIBRARIES

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]

HARNESS = r"""
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "rt.h"

uint8_t *MEM = NULL;
int64_t rt_budget = 0;

void rt_trap(CPU *c, int code, uint32_t addr) {
    (void)c; (void)code; (void)addr;
    __builtin_trap();
}

static void set_fcw(CPU *c, uint16_t fcw) {
    memcpy(c->r + 4256, &fcw, 2);
}

static void set_mxcsr(CPU *c, uint32_t mxcsr) {
    memcpy(c->r + 4244, &mxcsr, 4);
}

int main(void) {
    CPU c;
    memset(&c, 0, sizeof(c));

    // x87 FPUControlWord rounding modes (bits 10..11)
    set_fcw(&c, 0x027Fu); // nearest-even
    assert(FRND(c.r, 0.99) == 1.0);
    assert(FRND(c.r, 1.5) == 2.0);
    assert(FRND(c.r, 2.5) == 2.0);
    assert(FRND(c.r, -2.7) == -3.0);

    set_fcw(&c, 0x067Fu); // floor (-inf)
    assert(FRND(c.r, 0.99) == 0.0);
    assert(FRND(c.r, 2.7) == 2.0);
    assert(FRND(c.r, -2.1) == -3.0);

    set_fcw(&c, 0x0A7Fu); // ceil (+inf)
    assert(FRND(c.r, 0.01) == 1.0);
    assert(FRND(c.r, -2.9) == -2.0);

    set_fcw(&c, 0x0E7Fu); // truncate (0xC00 OR'd into FPUCW, used by g_580dc0)
    assert(FRND(c.r, 0.99) == 0.0);
    assert(FRND(c.r, 2.7) == 2.0);
    assert(FRND(c.r, -2.7) == -2.0);
    assert(FRND(c.r, -0.5) == 0.0);

    // SSE MXCSR rounding modes (bits 13..14)
    set_mxcsr(&c, 0x1F80u); // nearest-even
    assert(MXRND(c.r, 0.99) == 1.0);
    assert(MXRND(c.r, 2.5) == 2.0);
    assert(MXRND(c.r, -2.7) == -3.0);

    set_mxcsr(&c, 0x3F80u); // floor (-inf)
    assert(MXRND(c.r, 0.99) == 0.0);
    assert(MXRND(c.r, -2.1) == -3.0);

    set_mxcsr(&c, 0x5F80u); // ceil (+inf)
    assert(MXRND(c.r, 0.01) == 1.0);
    assert(MXRND(c.r, -2.9) == -2.0);

    set_mxcsr(&c, 0x7F80u); // truncate (towards zero)
    assert(MXRND(c.r, 0.99) == 0.0);
    assert(MXRND(c.r, 2.7) == 2.0);
    assert(MXRND(c.r, -2.7) == -2.0);

    puts("fpu_rounding_test: PASS");
    return 0;
}
"""


def load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


for inc in [ROOT / "upstream/recomp", REPO / "vendor/recompiler/recomp"]:
    with tempfile.TemporaryDirectory(prefix="smr-fpu-rnd-") as temp:
        src = Path(temp) / "test.c"
        binary = Path(temp) / "fpu-rounding-test"
        src.write_text(HARNESS)
        subprocess.run([
            *COMPILER, *PLATFORM_FLAGS, "-O2",
            "-I", str(inc),
            str(src), "-lm", *LIBRARIES, "-o", str(binary),
        ], check=True)
        out = subprocess.check_output([str(binary)], text=True).strip()
        assert out == "fpu_rounding_test: PASS", f"Unexpected output from {inc}: {out}"
print("PASS: runtime FRND/MXRND verified against both macos-runtime and recompiler rt.h")

emit_mod = load_mod("recomp_emit", REPO / "vendor/recompiler/recomp/emit.py")
emit_slow_mod = load_mod("recomp_emit_slow", REPO / "vendor/recompiler/recomp/emit_slow.py")

x87_fn = {
    "entry": 0x401000,
    "name": "test_x87",
    "insns": [
        {"a": 0x401000, "len": 2, "m": "FRNDINT",
         "ops": [["ROUND", ["register", 4352, 10], [["register", 4352, 10]]]]},
        {"a": 0x401002, "len": 1, "m": "RET", "ops": [["RETURN", None, []]]},
    ],
}
sse_fn = {
    "entry": 0x401100,
    "name": "test_sse",
    "insns": [
        {"a": 0x401100, "len": 4, "m": "CVTSD2SI EAX,XMM0",
         "ops": [["ROUND", ["unique", 0x100, 8], [["register", 4608, 8]]],
                 ["TRUNC", ["register", 0, 4], [["unique", 0x100, 8]]]]},
        {"a": 0x401104, "len": 1, "m": "RET", "ops": [["RETURN", None, []]]},
    ],
}

_, code_x87 = emit_mod.FnEmitter(x87_fn).emit()
_, code_sse = emit_mod.FnEmitter(sse_fn).emit()
assert "FRND(R," in code_x87 and "nearbyint(" not in code_x87, code_x87
assert "MXRND(R," in code_sse and "nearbyint(" not in code_sse, code_sse

_, slow_x87 = emit_slow_mod.FnEmitter(x87_fn).emit()
_, slow_sse = emit_slow_mod.FnEmitter(sse_fn).emit()
assert "FRND(R," in slow_x87 and "nearbyint(" not in slow_x87, slow_x87
assert "MXRND(R," in slow_sse and "nearbyint(" not in slow_sse, slow_sse
print("PASS: emit.py and emit_slow.py emit FRND(R,...) for x87 and MXRND(R,...) for SSE ROUND")
