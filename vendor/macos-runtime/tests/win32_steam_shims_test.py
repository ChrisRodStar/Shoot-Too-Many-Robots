"""KERNEL32/USER32/steam_api shims added for ShootManyRobots.exe."""
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

uint8_t *MEM;
_Thread_local uint32_t host_last_error;
HostImport host_imports[MAX_IMPORTS];
int host_import_count;

extern const ShimTable text_shims;
extern const ShimTable win_shims;
extern const ShimTable steam_shims;
void host_set_window_focused(int focused);

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
void rt_calltrace_dump(void) {}
const char *host_game_dir(void) { return "ShootManyRobots"; }
const char *host_exe_name(void) { return "ShootManyRobots.exe"; }
void host_path(const char *win, char *out, size_t n) { (void)win; if (n) out[0] = 0; }
void host_pump_events(void) {}
uint32_t dshow_create_filtergraph(uint32_t iid) { (void)iid; return 0; }
uint32_t host_thunk(const char *name, ShimFn fn) { (void)name; (void)fn; return 0; }

uint32_t wlen(uint32_t w) {
    uint32_t n = 0; uint16_t ch;
    do { memcpy(&ch, MEM + w + 2 * n, 2); n++; } while (ch);
    return n - 1;
}
void w2a(uint32_t w, char *out, size_t n) {
    size_t i = 0;
    for (; i + 1 < n; i++) {
        uint16_t ch; memcpy(&ch, MEM + w + 2 * i, 2);
        if (!ch) break;
        out[i] = ch < 256 ? (char)ch : '?';
    }
    out[i] = 0;
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
        fprintf(stderr, "Wrong stack cleanup: %#x count=%u\n", REG(&c, R_ESP), count);
        abort();
    }
    return REG(&c, R_EAX);
}

static ShimFn shim(const ShimTable *table, const char *name) {
    for (int i = 0; i < table->count; i++)
        if (strcmp(table->list[i].name, name) == 0) return table->list[i].fn;
    fprintf(stderr, "Missing shim %s\n", name);
    abort();
}

#define CALLT(table, name, ...) invoke(shim(table, name), (uint32_t[]){__VA_ARGS__}, \
    sizeof((uint32_t[]){__VA_ARGS__}) / sizeof(uint32_t))
#define CALL0T(table, name) invoke(shim(table, name), NULL, 0)
#define CALL(name, ...) CALLT(&text_shims, name, __VA_ARGS__)
#define CALL0(name) CALL0T(&text_shims, name)
#define UCALL(name, ...) CALLT(&win_shims, name, __VA_ARGS__)
#define UCALL0(name) CALL0T(&win_shims, name)

static void put_w(uint32_t addr, const char *s) {
    for (size_t i = 0;; i++) {
        uint16_t ch = (uint8_t)s[i];
        memcpy(MEM + addr + 2 * i, &ch, 2);
        if (!ch) break;
    }
}

int main(void) {
    MEM = calloc(1, 4u << 20);

    // ---- KERNEL32 (text_shims) ------------------------------------------------------------------
    const uint32_t src = 0x4000, dst = 0x4100;
    strcpy((char *)MEM + src, "C:\\Games\\SMR");
    uint32_t need = (uint32_t)strlen((char *)MEM + src) + 1;
    memset(MEM + dst, 0xAA, 32);
    check("ExpandEnvironmentStringsA copies and returns length",
          CALL("ExpandEnvironmentStringsA", src, dst, 32) == need &&
          strcmp((char *)MEM + dst, "C:\\Games\\SMR") == 0);
    check("ExpandEnvironmentStringsA reports size for null destination",
          CALL("ExpandEnvironmentStringsA", src, 0, 0) == need);
    memset(MEM + dst, 0xAA, 32);
    check("ExpandEnvironmentStringsA leaves a short buffer untouched",
          CALL("ExpandEnvironmentStringsA", src, dst, 4) == need && MEM[dst] == 0xAA);

    const uint32_t wsrc = 0x4200, wdst = 0x4300;
    put_w(wsrc, "Hello");
    memset(MEM + wdst, 0xAA, 16);
    check("lstrcpyW copies UTF-16 including NUL",
          CALL("lstrcpyW", wdst, wsrc) == wdst &&
          memcmp(MEM + wdst, MEM + wsrc, 12) == 0 && MEM[wdst + 12] == 0xAA);

    check("FlushConsoleInputBuffer returns TRUE", CALL("FlushConsoleInputBuffer", 0) == 1);
    check("SetConsoleTextAttribute returns TRUE",
          CALL("SetConsoleTextAttribute", 7, 0x0F) == 1);
    check("SetErrorMode stores and returns the previous mode",
          CALL("SetErrorMode", 0x8001) == 0 && CALL("SetErrorMode", 0x4000) == 0x8001);

    // ---- USER32 (win_shims) ---------------------------------------------------------------------
    const uint32_t kl = 0x4400;
    memset(MEM + kl, 0xAA, 16);
    check("GetKeyboardLayoutNameA writes the US layout",
          UCALL("GetKeyboardLayoutNameA", kl) == 1 &&
          strcmp((char *)MEM + kl, "00000409") == 0);
    check("GetKeyboardLayoutNameA tolerates a null buffer",
          UCALL("GetKeyboardLayoutNameA", 0) == 1);

    check("SetTimer returns the requested id",
          UCALL("SetTimer", 0x10010u, 7, 100, 0) == 7);
    check("SetTimer falls back to id 1 when none is given",
          UCALL("SetTimer", 0x10010u, 0, 100, 0) == 1);
    check("KillTimer returns TRUE", UCALL("KillTimer", 0x10010u, 7) == 1);
    check("InvalidateRect returns TRUE", UCALL("InvalidateRect", 0x10010u, 0, 1) == 1);

    const uint32_t wtext = 0x4600, wcaption = 0x4700;
    put_w(wtext, "Continue?");
    put_w(wcaption, "Shoot Too Many Robots");
    check("MessageBoxW returns IDOK",
          UCALL("MessageBoxW", 0, wtext, wcaption, 0) == 1);

    const uint32_t ps = 0x4800;
    memset(MEM + ps, 0xFF, 64);
    check("BeginPaint zeroes PAINTSTRUCT and returns the fake HDC",
          UCALL("BeginPaint", 0x10010u, ps) == 0xDC01u && G32(ps) == 0xDC01u);
    int paint_zeroed = 1;
    for (uint32_t i = 4; i < 64; i++) paint_zeroed &= MEM[ps + i] == 0;
    check("BeginPaint zeroes the rest of PAINTSTRUCT", paint_zeroed);
    check("BeginPaint tolerates a null PAINTSTRUCT",
          UCALL("BeginPaint", 0x10010u, 0) == 0xDC01u);
    check("EndPaint returns TRUE", UCALL("EndPaint", 0x10010u, ps) == 1);

    const uint32_t msg = 0x4900;
    check("PostQuitMessage returns zero", UCALL("PostQuitMessage", 0x2A) == 0);
    memset(MEM + msg, 0xFF, 28);
    check("PeekMessageA delivers WM_QUIT with the posted code",
          UCALL("PeekMessageA", msg, 0, 0, 0, 1) == 1 &&
          G32(msg) == 0x10010u && G32(msg + 4) == 0x0012u &&
          G32(msg + 8) == 0x2A && G32(msg + 12) == 0);
    check("PeekMessageA consumes WM_QUIT with PM_REMOVE",
          UCALL("PeekMessageA", msg, 0, 0, 0, 1) == 0);

    UCALL("PostQuitMessage", 7);
    check("PeekMessageA honors PM_NOREMOVE for WM_QUIT",
          UCALL("PeekMessageA", msg, 0, 0, 0, 0) == 1 &&
          G32(msg + 4) == 0x0012u && G32(msg + 8) == 7 &&
          UCALL("PeekMessageA", msg, 0, 0, 0, 0) == 1 && G32(msg + 8) == 7);
    check("PeekMessageA removes WM_QUIT after PM_NOREMOVE",
          UCALL("PeekMessageA", msg, 0, 0, 0, 1) == 1 && G32(msg + 8) == 7 &&
          UCALL("PeekMessageA", msg, 0, 0, 0, 1) == 0);

    host_set_window_focused(0);
    check("focus lost clears GetActiveWindow", UCALL0("GetActiveWindow") == 0);
    check("focus lost clears GetForegroundWindow", UCALL0("GetForegroundWindow") == 0);
    check("focus lost clears GetFocus", UCALL0("GetFocus") == 0);
    host_set_window_focused(1);
    check("focus gained restores GetActiveWindow", UCALL0("GetActiveWindow") == 0x10010u);
    check("focus gained restores GetForegroundWindow", UCALL0("GetForegroundWindow") == 0x10010u);
    check("focus gained restores GetFocus", UCALL0("GetFocus") == 0x10010u);

    // ---- steam_api.dll --------------------------------------------------------------------------
    static const char *const offline_steam[] = {
        "SteamMatchmaking", "SteamNetworking", "SteamGameServer", "SteamGameServer_Init",
        "SteamGameServer_Shutdown", "SteamAPI_RegisterCallResult", "SteamAPI_UnregisterCallResult",
        "SteamAPI_WriteMiniDump",
    };
    for (size_t i = 0; i < sizeof(offline_steam) / sizeof(offline_steam[0]); i++) {
        char name[128];
        snprintf(name, sizeof(name), "%s returns zero without popping", offline_steam[i]);
        check(name, CALL0T(&steam_shims, offline_steam[i]) == 0);
    }

    free(MEM);
    return failed ? 1 : 0;
}
'''


def main() -> int:
    with tempfile.TemporaryDirectory() as temp:
        work = Path(temp)
        source = work / 'win32_steam_shims_test.c'
        source.write_text(SOURCE)
        binary = work / 'win32-steam-shims-test'
        subprocess.run([
            *COMPILER, *PLATFORM_FLAGS, '-O1', '-Wall', '-Wextra',
            '-I', str(ROOT / 'macos'),
            '-I', str(ROOT / 'upstream/recomp/host'),
            '-I', str(ROOT / 'upstream/recomp'),
            str(source),
            str(ROOT / 'upstream/recomp/host/shims_text.c'),
            str(ROOT / 'upstream/recomp/host/shims_win.c'),
            str(ROOT / 'upstream/recomp/host/shims_steam.c'),
            str(ROOT / 'upstream/recomp/host/input.c'),
            str(ROOT / 'macos/FNVDisplay.c'),
            *LIBRARIES, '-o', str(binary),
        ], check=True)
        result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=20)
        print(result.stdout, end='')
        print(result.stderr, end='')
        return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
