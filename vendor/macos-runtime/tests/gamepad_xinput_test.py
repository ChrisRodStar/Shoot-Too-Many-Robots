"""XInput 1.3 ABI over the GameController pad bridge, without a device or game assets.

Compiles dinput.c together with FNVPad.c, then feeds synthetic controller snapshots through
fnv_pad_physical_state just like src/host/gamepad.m does from GameController.framework. The test
provides the strong fnv_pad_poll/fnv_pad_set_rumble hooks so FNVPad.c's weak fallbacks are
overridden, exactly as the windowed host links them.
"""
from native_test_toolchain import COMPILER, PLATFORM_FLAGS, LIBRARIES
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]

SOURCE = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "com.h"
#include "shims.h"
#include "FNVPad.h"

uint8_t *MEM;
HostImport host_imports[MAX_IMPORTS];
int host_import_count;

extern const ShimTable xinput_shims;

static uint32_t heap = 0x80000;
uint32_t gmalloc(uint32_t n) {
    uint32_t p = heap + 16;
    P32(p - 4, n);
    heap = (p + n + 15) & ~15u;
    if (heap >= 4u << 20) abort();
    return p;
}
void gfree(uint32_t p) { if (p) memset(MEM + p, 0xdd, G32(p - 4)); }
void rt_trap(CPU *c, int code, uint32_t address) {
    (void)c;
    fprintf(stderr, "unexpected trap %d at %#x\n", code, address);
    abort();
}

/* dinput.c links the DirectInput keyboard/mouse shims; the XInput paths do not use them. */
void input_key(int dik, int down) { (void)dik; (void)down; }
void input_mouse_move(int dx, int dy) { (void)dx; (void)dy; }
void input_mouse_wheel(int dz) { (void)dz; }
void input_mouse_button(int b, int down) { (void)b; (void)down; }
void input_keyboard_state(uint8_t out[256]) { memset(out, 0, 256); }
void input_mouse_state(int32_t *dx, int32_t *dy, int32_t *dz, uint8_t buttons[8]) {
    *dx = *dy = *dz = 0;
    memset(buttons, 0, 8);
}
int input_pop_event(int device, uint32_t *ofs, uint32_t *data, int peek_index) {
    (void)device; (void)ofs; (void)data; (void)peek_index;
    return 0;
}
int input_pending(int device) { (void)device; return 0; }

/* Strong hooks override FNVPad.c's weak fallbacks. */
static int polls;
void fnv_pad_poll(void) { polls++; }
static uint16_t rumble_left, rumble_right;
static int rumble_calls;
void fnv_pad_set_rumble(uint16_t left_motor, uint16_t right_motor) {
    rumble_left = left_motor;
    rumble_right = right_motor;
    rumble_calls++;
}

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
        fprintf(stderr, "Wrong XInput stack cleanup: %#x count=%u\n", REG(&c, R_ESP), count);
        abort();
    }
    return REG(&c, R_EAX);
}

static ShimFn shim(const char *name) {
    for (int i = 0; i < xinput_shims.count; i++)
        if (strcmp(xinput_shims.list[i].name, name) == 0) return xinput_shims.list[i].fn;
    fprintf(stderr, "Missing XInput shim %s\n", name);
    abort();
}

#define CALL(name, ...) invoke(shim(name), (uint32_t[]){__VA_ARGS__}, \
    sizeof((uint32_t[]){__VA_ARGS__}) / sizeof(uint32_t))

int main(void) {
    MEM = calloc(1, 4u << 20);
    const uint32_t state_out = 0x4000;
    const uint32_t caps_out = 0x4100;
    const uint32_t vibration = 0x4200;

    check("XInputEnable(TRUE) succeeds", CALL("XInputEnable", 1) == 0);

    int before = polls;
    check("disconnected pad reports ERROR_DEVICE_NOT_CONNECTED",
          CALL("XInputGetState", 0, state_out) == 1167 && polls == before + 1);
    check("null capabilities output is rejected",
          CALL("XInputGetCapabilities", 0, 0, 0) == 1167);

    FNVPadState synthetic = {0};
    synthetic.buttons = 0x1234;
    synthetic.left_trigger = 0x56;
    synthetic.right_trigger = 0x78;
    synthetic.lx = -1234;
    synthetic.ly = 2345;
    synthetic.rx = -3456;
    synthetic.ry = 4567;
    fnv_pad_physical_state(&synthetic, 1);

    before = polls;
    check("connected pad returns XINPUT_STATE", CALL("XInputGetState", 0, state_out) == 0 && polls == before + 1);
    check("dwPacketNumber starts at the first change", G32(state_out) == 1);
    check("wButtons maps at +4", (G32(state_out + 4) & 0xffff) == 0x1234);
    check("triggers map at +6/+7", G32(state_out + 4) >> 16 == 0x7856);
    check("left stick maps at +8/+10", (int16_t)G32(state_out + 8) == -1234);
    check("left stick Y maps at +10", (int16_t)(G32(state_out + 8) >> 16) == 2345);
    check("right stick maps at +12/+14", (int16_t)G32(state_out + 12) == -3456);
    check("right stick Y maps at +14", (int16_t)(G32(state_out + 12) >> 16) == 4567);

    CALL("XInputGetState", 0, state_out);
    check("unchanged snapshot keeps dwPacketNumber stable", G32(state_out) == 1);
    synthetic.ly = 3000;
    fnv_pad_physical_state(&synthetic, 1);
    CALL("XInputGetState", 0, state_out);
    check("changed snapshot increments dwPacketNumber", G32(state_out) == 2);

    check("null state output is rejected", CALL("XInputGetState", 0, 0) == 87);

    check("XInputGetCapabilities returns a gamepad", CALL("XInputGetCapabilities", 0, 0, caps_out) == 0);
    check("capability type/subtype", MEM[caps_out] == 1 && MEM[caps_out + 1] == 1);
    check("capability button mask", MEM[caps_out + 4] == 0xff && MEM[caps_out + 5] == 0xf3);
    check("capability analog triggers", MEM[caps_out + 6] == 255 && MEM[caps_out + 7] == 255);
    check("capability stick ranges", G32(caps_out + 8) == 0x7fff7fff && G32(caps_out + 12) == 0x7fff7fff);
    check("capability rumble motors", G32(caps_out + 20) == 0xffffffffu);

    P32(vibration, 0x33441122u); /* wLeftMotorSpeed=0x1122, wRightMotorSpeed=0x3344 */
    rumble_calls = 0;
    before = polls;
    check("XInputSetState succeeds", CALL("XInputSetState", 0, vibration) == 0 && polls == before + 1);
    check("XInputSetState forwards both motor speeds",
          rumble_calls == 1 && rumble_left == 0x1122 && rumble_right == 0x3344);
    check("null vibration output is rejected", CALL("XInputSetState", 0, 0) == 87);

    check("XInputEnable(FALSE) succeeds", CALL("XInputEnable", 0) == 0);
    check("disabled pad stops reporting state", CALL("XInputGetState", 0, state_out) == 1167);
    check("disabled pad stops reporting capabilities", CALL("XInputGetCapabilities", 0, 0, caps_out) == 1167);
    check("disabled pad rejects rumble", CALL("XInputSetState", 0, vibration) == 1167);
    CALL("XInputEnable", 1);

    before = polls;
    check("controller index 1 stays disconnected",
          CALL("XInputGetState", 1, state_out) == 1167 && polls == before);

    rumble_calls = 0;
    check("disconnect succeeds", CALL("XInputSetState", 0, vibration) == 0 && rumble_calls == 1);
    fnv_pad_physical_state(NULL, 0);
    check("unplugged pad reports ERROR_DEVICE_NOT_CONNECTED", CALL("XInputGetState", 0, state_out) == 1167);
    check("unplugged pad rejects capabilities", CALL("XInputGetCapabilities", 0, 0, caps_out) == 1167);
    check("unplugged pad rejects rumble", CALL("XInputSetState", 0, vibration) == 1167);

    free(MEM);
    return failed ? 1 : 0;
}
'''


def main() -> int:
    with tempfile.TemporaryDirectory() as temp:
        work = Path(temp)
        source = work / 'gamepad_xinput_test.c'
        source.write_text(SOURCE)
        binary = work / 'gamepad-xinput-test'
        subprocess.run([
            *COMPILER, *PLATFORM_FLAGS, '-O1', '-Wall', '-Wextra',
            '-I', str(ROOT / 'macos'),
            '-I', str(ROOT / 'upstream/recomp/host'),
            '-I', str(ROOT / 'upstream/recomp'),
            str(source),
            str(ROOT / 'macos/FNVPad.c'),
            str(ROOT / 'upstream/recomp/host/dinput.c'),
            str(ROOT / 'upstream/recomp/host/com.c'),
            *LIBRARIES, '-o', str(binary),
        ], check=True)
        result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=20)
        print(result.stdout, end='')
        print(result.stderr, end='')
        return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
