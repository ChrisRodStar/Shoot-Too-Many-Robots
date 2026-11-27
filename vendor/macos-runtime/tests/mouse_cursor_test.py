"""Cursor position, window rect, wheel, and mouse virtual-key shims."""
from native_test_toolchain import COMPILER, PLATFORM_FLAGS, LIBRARIES
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]

SOURCE = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "shims.h"
#include "input.h"
#include "FNVDisplay.h"

void input_mouse_pos(int32_t x, int32_t y);

uint8_t *MEM;
_Thread_local uint32_t host_last_error;
HostImport host_imports[MAX_IMPORTS];
int host_import_count;

extern const ShimTable win_shims;

static uint32_t heap = 0x80000;
uint32_t gmalloc(uint32_t n) {
    uint32_t p = heap + 16;
    P32(p - 4, n);
    heap = (p + n + 15) & ~15u;
    if (heap >= 4u << 20) abort();
    return p;
}
void gfree(uint32_t p) { if (p) memset(MEM + p, 0xdd, G32(p - 4)); }
void gheap_report(void) {}
void rt_call(CPU *c, uint32_t addr) { (void)c; (void)addr; }
void rt_trap(CPU *c, int code, uint32_t address) { (void)c; (void)code; (void)address; abort(); }
const char *host_game_dir(void) { return "ShootManyRobots"; }
void host_path(const char *win, char *out, size_t n) { (void)win; if (n) out[0] = 0; }
void host_pump_events(void) {}
uint32_t dshow_create_filtergraph(uint32_t iid) { (void)iid; return 0; }

static int failed;
static void check(const char *name, int ok) {
    printf("%s: %s\n", ok ? "PASS" : "FAIL", name);
    failed += !ok;
}

static uint32_t invoke(ShimFn fn, const uint32_t *args, unsigned count) {
    CPU c = {0};
    SETREG(&c, R_ESP, 0x1000);
    P32(0x1000, 0xabc);
    for (unsigned i = 0; i < count; i++) P32(0x1004 + 4 * i, args[i]);
    fn(&c);
    if (REG(&c, R_ESP) != 0x1004 + 4 * count) {
        fprintf(stderr, "Wrong stack cleanup: %#x count=%u\n", REG(&c, R_ESP), count);
        abort();
    }
    return REG(&c, R_EAX);
}

static ShimFn shim(const char *name) {
    for (int i = 0; i < win_shims.count; i++)
        if (strcmp(win_shims.list[i].name, name) == 0) return win_shims.list[i].fn;
    fprintf(stderr, "Missing shim %s\n", name);
    abort();
}

#define CALL(name, ...) invoke(shim(name), (uint32_t[]){__VA_ARGS__}, \
    sizeof((uint32_t[]){__VA_ARGS__}) / sizeof(uint32_t))

int main(void) {
    MEM = calloc(1, 4u << 20);
    fnv_display_client(1024, 768);

    const uint32_t pt = 0x4000;
    const uint32_t rc = 0x4100;
    const uint32_t clip = 0x4200;

    check("GetCursorPos default center",
          CALL("GetCursorPos", pt) == 1 && (int32_t)G32(pt) == 512 && (int32_t)G32(pt + 4) == 384);

    input_mouse_pos(123, 456);
    check("GetCursorPos reflects input_mouse_pos",
          CALL("GetCursorPos", pt) == 1 && (int32_t)G32(pt) == 123 && (int32_t)G32(pt + 4) == 456);

    P32(clip, 100); P32(clip + 4, 100); P32(clip + 8, 300); P32(clip + 12, 300);
    CALL("ClipCursor", clip);
    input_mouse_pos(500, 500);
    check("ClipCursor clamps GetCursorPos",
          CALL("GetCursorPos", pt) == 1 && (int32_t)G32(pt) == 299 && (int32_t)G32(pt + 4) == 299);
    CALL("ClipCursor", 0);

    CALL("SetCursorPos", 700, 200);
    check("SetCursorPos updates GetCursorPos",
          CALL("GetCursorPos", pt) == 1 && (int32_t)G32(pt) == 700 && (int32_t)G32(pt + 4) == 200);

    check("GetWindowRect writes client dimensions",
          CALL("GetWindowRect", 0x10010u, rc) == 1 &&
          G32(rc) == 0 && G32(rc + 4) == 0 && G32(rc + 8) == 1024 && G32(rc + 12) == 768);
    check("GetWindowRect rejects null rect", CALL("GetWindowRect", 0x10010u, 0) == 0);

    input_mouse_button(0, 1);
    input_mouse_button(1, 1);
    input_mouse_button(2, 1);
    check("GetAsyncKeyState VK_LBUTTON down", CALL("GetAsyncKeyState", 0x01) == 0x8000u);
    check("GetKeyState VK_RBUTTON down", CALL("GetKeyState", 0x02) == 0xFF80u);
    check("GetAsyncKeyState VK_MBUTTON down", CALL("GetAsyncKeyState", 0x04) == 0x8000u);
    input_mouse_button(0, 0);
    input_mouse_button(1, 0);
    input_mouse_button(2, 0);
    check("GetAsyncKeyState VK_LBUTTON up", CALL("GetAsyncKeyState", 0x01) == 0u);
    check("GetKeyState VK_RBUTTON up", CALL("GetKeyState", 0x02) == 0u);

    input_mouse_wheel(120);
    int32_t dx = 0, dy = 0, dz = 0; uint8_t b[8] = {0};
    input_mouse_state(&dx, &dy, &dz, b);
    check("mouse wheel reported in input_mouse_state", dz == 120);

    free(MEM);
    return failed ? 1 : 0;
}
'''


def main() -> int:
    with tempfile.TemporaryDirectory() as temp:
        work = Path(temp)
        source = work / 'mouse_cursor_test.c'
        source.write_text(SOURCE)
        binary = work / 'mouse-cursor-test'
        subprocess.run([
            *COMPILER, *PLATFORM_FLAGS, '-O1', '-Wall', '-Wextra',
            '-I', str(ROOT / 'macos'),
            '-I', str(ROOT / 'upstream/recomp/host'),
            '-I', str(ROOT / 'upstream/recomp'),
            str(source),
            str(ROOT / 'upstream/recomp/host/input.c'),
            str(ROOT / 'upstream/recomp/host/shims_win.c'),
            str(ROOT / 'macos/FNVDisplay.c'),
            *LIBRARIES, '-o', str(binary),
        ], check=True)
        result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=20)
        print(result.stdout, end='')
        print(result.stderr, end='')
        return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
