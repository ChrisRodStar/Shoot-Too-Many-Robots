// Headless (M2) user32 / gdi32 / advapi32 / shell32 / ole32 / winmm / steam_api shims.
// The window exists only as a handle and an empty message queue until the Metal layer (M3).
#include <stdio.h>
#include <stdbool.h>
#include <errno.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <time.h>
#include "shims.h"
#include "FNVDisplay.h"
#include "input.h"

#define FAKE_HWND 0x00010010u
#define DESKTOP_HWND 0x00010000u
#define WINDOW_STATION 0x00010020u
static uint32_t wndproc;

// ---- a small Win32 message queue; DispatchMessage / SendMessage run the game's own WndProc ----------
#include <pthread.h>
typedef struct { uint32_t msg, wp, lp; } QMsg;
static QMsg mq[512]; static int mq_h, mq_t;
static pthread_mutex_t mq_lk = PTHREAD_MUTEX_INITIALIZER;
void host_post_message(uint32_t msg, uint32_t wp, uint32_t lp) {
    pthread_mutex_lock(&mq_lk);
    int n = (mq_t + 1) % 512;
    if (n != mq_h) { mq[mq_t] = (QMsg){msg, wp, lp}; mq_t = n; }
    pthread_mutex_unlock(&mq_lk);
}
static uint32_t call_wndproc(CPU *c, uint32_t hwnd, uint32_t msg, uint32_t wp, uint32_t lp) {
    if (!wndproc) return 0;
    uint32_t esp = REG(c, R_ESP), saved_eax = REG(c, R_EAX);
    uint32_t sp = esp - 64;                       // below the shim's own frame
    P32(sp, HOST_EXIT_THUNK); P32(sp + 4, hwnd); P32(sp + 8, msg); P32(sp + 12, wp); P32(sp + 16, lp);
    SETREG(c, R_ESP, sp);
    rt_call(c, wndproc);                          // stdcall: callee pops the 4 args + return address
    uint32_t r = REG(c, R_EAX);
    SETREG(c, R_ESP, esp); (void)saved_eax;
    return r;
}

// ---- user32 ------------------------------------------------------------------------------------
SHIM(RegisterClassA) { wndproc = G32(ARG(c, 0) + 4); fprintf(stderr, "[host] RegisterClassA wndproc %#x\n", wndproc); RET(c, 0xC001, 1); }
static uint32_t window_style, window_ex_style, window_user_data;

SHIM(CreateWindowExA) {
    window_style = ARG(c, 3);
    window_ex_style = ARG(c, 0);
    window_user_data = 0;
    // the window starts active: tell the game the way Windows would
    host_post_message(0x001C /* WM_ACTIVATEAPP */, 1, 0);
    host_post_message(0x0006 /* WM_ACTIVATE */, 1 /* WA_ACTIVE */, 0);
    host_post_message(0x0007 /* WM_SETFOCUS */, 0, 0);
    fprintf(stderr, "[host] CreateWindowExA(\"%s\", %ux%u) -> headless window\n", GSTR(ARG(c, 2)) ? GSTR(ARG(c, 2)) : "", ARG(c, 6), ARG(c, 7));
    RET(c, FAKE_HWND, 12);
}
SHIM(DestroyWindow) { RET(c, 1, 1); }
SHIM(ShowWindow) { RET(c, 1, 2); }
SHIM(UpdateWindow) { RET(c, 1, 1); }
SHIM(SetWindowPos) { RET(c, 1, 7); }
SHIM(SetWindowTextA) { RET(c, 1, 2); }
SHIM(GetWindowTextA) { if (ARG(c, 2)) MEM[ARG(c, 1)] = 0; RET(c, 0, 3); }
SHIM(GetClassNameA) { if (ARG(c, 2)) MEM[ARG(c, 1)] = 0; RET(c, 0, 3); }
SHIM(GetWindow) { RET(c, 0, 2); }
static uint32_t *window_long_field(uint32_t window, int32_t index) {
    if (window != FAKE_HWND) {
        SETERR(1400); // ERROR_INVALID_WINDOW_HANDLE
        return NULL;
    }
    switch (index) {
    case -4: return &wndproc;
    case -16: return &window_style;
    case -20: return &window_ex_style;
    case -21: return &window_user_data;
    default:
        SETERR(87);
        return NULL;
    }
}

SHIM(GetWindowLongA) {
    uint32_t *field = window_long_field(ARG(c, 0), (int32_t)ARG(c, 1));
    RET(c, field ? *field : 0, 2);
}

SHIM(SetWindowLongA) {
    uint32_t *field = window_long_field(ARG(c, 0), (int32_t)ARG(c, 1));
    uint32_t previous = field ? *field : 0;
    if (field)
        *field = ARG(c, 2);
    RET(c, previous, 3);
}
SHIM(GetClassLongA) { RET(c, 0, 2); }
SHIM(EnumChildWindows) { RET(c, 1, 3); }
SHIM(FindWindowA) { RET(c, 0, 2); }
SHIM(GetDesktopWindow) { RET(c, DESKTOP_HWND, 0); }
SHIM(GetProcessWindowStation) { RET(c, WINDOW_STATION, 0); }

SHIM(GetUserObjectInformationW) {
    static const uint16_t name[] = {'W', 'i', 'n', 'S', 't', 'a', '0', 0};
    uint32_t handle = ARG(c, 0), index = ARG(c, 1);
    uint32_t output = ARG(c, 2), capacity = ARG(c, 3), needed = ARG(c, 4);
    if (handle != WINDOW_STATION || index != 2) {
        SETERR(handle != WINDOW_STATION ? 6 : 87);
        RET(c, 0, 5);
        return;
    }
    if (needed)
        P32(needed, sizeof(name));
    if (!output || capacity < sizeof(name)) {
        SETERR(122);
        RET(c, 0, 5);
        return;
    }
    memcpy(MEM + output, name, sizeof(name));
    RET(c, 1, 5);
}

SHIM(GetActiveWindow) { RET(c, FAKE_HWND, 0); }
SHIM(GetForegroundWindow) { RET(c, FAKE_HWND, 0); }
SHIM(GetFocus) { RET(c, FAKE_HWND, 0); }
SHIM(SetForegroundWindow) { RET(c, 1, 1); }
// The guest has one window whose client area starts at its virtual desktop origin.
SHIM(ScreenToClient) {
    if (ARG(c, 0) != FAKE_HWND || !ARG(c, 1)) {
        SETERR(87);
        RET(c, 0, 2);
        return;
    }
    RET(c, 1, 2);
}

SHIM(ClientToScreen) { ScreenToClient_(c); }

SHIM(GetClientRect) { uint32_t r = ARG(c, 1); P32(r, 0); P32(r + 4, 0); P32(r + 8, fnv_client_width()); P32(r + 12, fnv_client_height()); RET(c, 1, 2); }
SHIM(GetWindowRect) {
    uint32_t r = ARG(c, 1);
    if (!r) { RET(c, 0, 2); return; }
    P32(r, 0); P32(r + 4, 0); P32(r + 8, fnv_client_width()); P32(r + 12, fnv_client_height());
    RET(c, 1, 2);
}
SHIM(AdjustWindowRect) { RET(c, 1, 3); }
SHIM(AdjustWindowRectEx) { RET(c, 1, 4); }
SHIM(GetSystemMetrics) { uint32_t i = ARG(c, 0); RET(c, i == 0 ? fnv_display_width() : i == 1 ? fnv_display_height() : 0, 1); }
SHIM(EnumDisplayDevicesA) { RET(c, 0, 4); }
SHIM(LoadImageA) {
    uint32_t type = ARG(c, 2);
    uint32_t handle = type == 1 ? 0x00020001u : type == 2 ? 0x00020002u : 0;
    RET(c, handle, 6);
}
SHIM(LoadIconA) { RET(c, 0x00020001, 2); }
static uint32_t window_cursor;

SHIM(SetCursor) {
    uint32_t previous = window_cursor;
    window_cursor = ARG(c, 0);
    RET(c, previous, 1);
}

SHIM(LoadCursorA) { RET(c, 0x00020002, 2); }
SHIM(ShowCursor) {
    static int32_t display_count = 0;
    int32_t v = ARG(c, 0) ? __atomic_add_fetch(&display_count, 1, __ATOMIC_RELAXED)
                          : __atomic_sub_fetch(&display_count, 1, __ATOMIC_RELAXED);
    RET(c, (uint32_t)v, 1);
}
SHIM(GetDoubleClickTime) { RET(c, 500, 0); }
SHIM(SwapMouseButton) { RET(c, 0, 1); }
SHIM(GetAsyncKeyState) { RET(c, input_vk_down((int)ARG(c, 0)) ? 0x8000u : 0u, 1); }
SHIM(GetKeyState) { RET(c, input_vk_down((int)ARG(c, 0)) ? 0xFF80u : 0u, 1); }
SHIM(GetKeyboardLayout) { RET(c, 0x04090409u, 1); }
SHIM(MapVirtualKeyA) { RET(c, input_map_vk(ARG(c, 0), ARG(c, 1)), 2); }
SHIM(ToUnicode) {
    uint32_t vk = ARG(c, 0), ks = ARG(c, 2), out = ARG(c, 3); int cap = (int)ARG(c, 4);
    int shift = ks ? (MEM[ks + 0x10] & 0x80) != 0 : input_vk_down(0x10);
    int ch = input_vk_to_char((int)vk, shift);
    if (!ch || cap <= 0) { RET(c, 0, 6); return; }
    uint16_t w = (uint16_t)ch; memcpy(MEM + out, &w, 2);
    RET(c, 1, 6);
}
void input_mouse_pos(int32_t x, int32_t y);
int input_get_mouse_pos(int32_t *x, int32_t *y);
static bool cursor_set, cursor_clipped;
static int32_t cursor_x, cursor_y, cursor_clip[4];

SHIM(ClipCursor) {
    uint32_t rect = ARG(c, 0);
    cursor_clipped = rect != 0;
    if (rect)
        memcpy(cursor_clip, MEM + rect, sizeof(cursor_clip));
    RET(c, 1, 1);
}

SHIM(SetCursorPos) {
    cursor_x = (int32_t)ARG(c, 0);
    cursor_y = (int32_t)ARG(c, 1);
    cursor_set = true;
    input_mouse_pos(cursor_x, cursor_y);
    RET(c, 1, 2);
}

SHIM(GetCursorPos) {
    uint32_t output = ARG(c, 0);
    if (output) {
        int32_t x = (int32_t)fnv_client_width() / 2;
        int32_t y = (int32_t)fnv_client_height() / 2;
        if (!input_get_mouse_pos(&x, &y) && cursor_set) {
            x = cursor_x;
            y = cursor_y;
        }
        if (cursor_clipped && cursor_clip[0] < cursor_clip[2] && cursor_clip[1] < cursor_clip[3]) {
            if (x < cursor_clip[0]) x = cursor_clip[0];
            if (y < cursor_clip[1]) y = cursor_clip[1];
            if (x >= cursor_clip[2]) x = cursor_clip[2] - 1;
            if (y >= cursor_clip[3]) y = cursor_clip[3] - 1;
        }
        P32(output, (uint32_t)x);
        P32(output + 4, (uint32_t)y);
    }
    RET(c, output != 0, 1);
}
SHIM(GetDlgItem) { RET(c, 0, 2); }
SHIM(GetWindowInfo) {
    uint32_t p = ARG(c, 1);
    if (!p) { RET(c, 0, 2); return; }
    memset(MEM + p, 0, 60); P32(p, 60);
    P32(p + 12, fnv_client_width()); P32(p + 16, fnv_client_height());
    P32(p + 28, fnv_client_width()); P32(p + 32, fnv_client_height());
    P32(p + 36, 0x10000000u /* WS_VISIBLE */); P32(p + 44, 1 /* WS_ACTIVECAPTION */);
    RET(c, 1, 2);
}
SHIM(SendInput) { RET(c, ARG(c, 0), 3); }
SHIM(SetWindowsHookExA) { RET(c, 0x00030001, 4); }
SHIM(UnhookWindowsHookEx) { RET(c, 1, 1); }
SHIM(CallNextHookEx) { RET(c, 0, 4); }
void host_pump_events(void);
SHIM(PeekMessageA) {
    host_pump_events();
    uint32_t m = ARG(c, 0), remove = ARG(c, 4) & 1;
    pthread_mutex_lock(&mq_lk);
    if (mq_h == mq_t) { pthread_mutex_unlock(&mq_lk); RET(c, 0, 5); return; }
    QMsg q = mq[mq_h];
    if (remove) mq_h = (mq_h + 1) % 512;
    pthread_mutex_unlock(&mq_lk);
    P32(m, FAKE_HWND); P32(m + 4, q.msg); P32(m + 8, q.wp); P32(m + 12, q.lp);
    P32(m + 16, (uint32_t)(clock_gettime_nsec_np(CLOCK_UPTIME_RAW) / 1000000)); P32(m + 20, 0); P32(m + 24, 0);
    RET(c, 1, 5);
}
SHIM(TranslateMessage) { RET(c, 0, 1); }
SHIM(DispatchMessageA) {
    uint32_t m = ARG(c, 0);
    uint32_t r = call_wndproc(c, G32(m), G32(m + 4), G32(m + 8), G32(m + 12));
    RET(c, r, 1);
}
SHIM(SendMessageA) { uint32_t r = call_wndproc(c, ARG(c, 0), ARG(c, 1), ARG(c, 2), ARG(c, 3)); RET(c, r, 4); }
SHIM(DefWindowProcA) { RET(c, 0, 4); }
SHIM(MessageBoxA) {
    fprintf(stderr, "[host] MessageBoxA: \"%s\" — %s\n", GSTR(ARG(c, 2)) ? GSTR(ARG(c, 2)) : "", GSTR(ARG(c, 1)) ? GSTR(ARG(c, 1)) : "");
    RET(c, 1, 4);    // IDOK
}
// ---- gdi32 / comctl32 ----------------------------------------------------------------------------
SHIM(GetStockObject) { RET(c, 0x00040001, 1); }
SHIM(GetDC) { RET(c, 0, 1); }
SHIM(CreateDCA) { RET(c, 0, 4); }
SHIM(ExtEscape) { RET(c, 0, 6); }
SHIM(DeleteDC) { RET(c, 1, 1); }
SHIM(InitCommonControlsEx) { RET(c, 1, 1); }
SHIM(ImageList_LoadImageA) { RET(c, 0x00050001, 7); }
SHIM(ImageList_Destroy) { RET(c, 1, 1); }

// ---- advapi32: an empty registry (the game falls back to defaults / its INIs) -------------------
SHIM(RegOpenKeyA) {
    if (ARG(c, 2))
        P32(ARG(c, 2), 0);
    RET(c, 2, 3); // ERROR_FILE_NOT_FOUND in the probe's empty registry.
}
SHIM(RegOpenKeyExA) { RET(c, 2, 5); }                // ERROR_FILE_NOT_FOUND
SHIM(RegCreateKeyExA) { if (ARG(c, 7)) P32(ARG(c, 7), 0x00060001); RET(c, 0, 9); }
SHIM(RegQueryValueExA) { RET(c, 2, 6); }
SHIM(RegSetValueExA) { RET(c, 0, 6); }
SHIM(RegCloseKey) { RET(c, 0, 1); }
SHIM(GetUserNameA) { const char *u = "Player"; strcpy((char *)MEM + ARG(c, 0), u); P32(ARG(c, 1), 7); RET(c, 1, 2); }

SHIM(GetUserNameW) {
    static const uint16_t player[] = {'P', 'l', 'a', 'y', 'e', 'r', 0};
    uint32_t output = ARG(c, 0);
    uint32_t size = ARG(c, 1);
    uint32_t capacity = G32(size);
    P32(size, sizeof(player) / sizeof(player[0]));
    if (!output || capacity < sizeof(player) / sizeof(player[0])) {
        SETERR(122); // ERROR_INSUFFICIENT_BUFFER
        RET(c, 0, 2);
        return;
    }
    memcpy(MEM + output, player, sizeof(player));
    RET(c, 1, 2);
}

const char *host_game_dir(void);

// ---- shell32: special folders live under SKYRIM_USER_DIR / FNV_USER_DIR (or UserDocuments) ------
SHIM(SHGetFolderPathW) {
    uint32_t folder = ARG(c, 1) & 0xffu;
    uint32_t output = ARG(c, 4);
    const char *app_data = "C:\\Games\\ShootManyRobots\\UserDocuments\\LocalAppData";
    if (!output || (folder != 0x1c && folder != 0x1a)) {
        RET(c, 0x80070057u, 5); // E_INVALIDARG
        return;
    }

    char path[1024];
    host_path(app_data, path, sizeof(path));
    if (mkdir(path, 0755) != 0 && errno != EEXIST) {
        RET(c, 0x80004005u, 5); // E_FAIL
        return;
    }
    for (size_t index = 0; index <= strlen(app_data); index++) {
        uint16_t code_unit = (unsigned char)app_data[index];
        memcpy(MEM + output + 2 * index, &code_unit, sizeof(code_unit));
    }
    RET(c, 0, 5);
}

SHIM(SHGetFolderPathA) {
    uint32_t csidl = ARG(c, 1) & 0xFFu;
    const char *gd = host_game_dir();
    const char *ud = getenv("SKYRIM_USER_DIR");
    if (!ud || !ud[0]) ud = getenv("FNV_USER_DIR");
    const char *base = (ud && ud[0]) ? ud : "UserDocuments";
    mkdir(base, 0755);
    if ((csidl == 0x1c || csidl == 0x1a) &&
        (strcmp(gd, "Fallout3") == 0 || strcmp(gd, "Skyrim") == 0)) {
        char local_dir[1024], win_path[256];
        snprintf(local_dir, sizeof local_dir, "%s/LocalAppData", base);
        mkdir(local_dir, 0755);
        snprintf(win_path, sizeof win_path, "C:\\Games\\%s\\UserDocuments\\LocalAppData", gd);
        strcpy((char *)MEM + ARG(c, 4), win_path);
    } else {
        char p[256];
        snprintf(p, sizeof p, "C:\\Games\\%s\\UserDocuments", gd);
        strcpy((char *)MEM + ARG(c, 4), p);
    }
    RET(c, 0, 5);
}
// Nothing external is launched (e.g. FalloutNVLauncher.exe / SkyrimLauncher.exe). The game tests
// the result for != 0, not the documented > 32, so failure has to be 0 for it to carry on cleanly.
SHIM(ShellExecuteA) {
    fprintf(stderr, "[host] ShellExecuteA(%s) -> not launched\n", GSTR(ARG(c, 2)) ? GSTR(ARG(c, 2)) : "");
    RET(c, 0, 6);
}
SHIM(CommandLineToArgvW) { if (ARG(c, 1)) P32(ARG(c, 1), 0); RET(c, gmalloc(8), 2); }

// ---- ole32 -------------------------------------------------------------------------------------
SHIM(CoInitialize) { RET(c, 0, 1); }
SHIM(CoInitializeEx) { RET(c, 0, 2); }
SHIM(CoUninitialize) { RET(c, 0, 0); }
SHIM(CoFreeUnusedLibraries) { RET(c, 0, 0); }
SHIM(CoTaskMemAlloc) { RET(c, gmalloc(ARG(c, 0)), 1); }
SHIM(CoTaskMemFree) { gfree(ARG(c, 0)); RET(c, 0, 1); }
uint32_t dshow_create_filtergraph(uint32_t iid);
#ifdef FNV_GAME_SKYRIM
uint32_t xaudio2_create(uint32_t iid);
uint32_t xaudio2_create_reverb(uint32_t iid);
#endif
SHIM(CoCreateInstance) {
    static const uint8_t filter_graph[16] = {
        0xb3,0xeb,0x36,0xe4,0x4f,0x52,0xce,0x11,0x9f,0x53,0x00,0x20,0xaf,0x0b,0xa7,0x70
    };
#ifdef FNV_GAME_SKYRIM
    static const uint8_t xaudio2_clsid[16] = {
        0x49,0x9b,0xda,0x3e,0x85,0x20,0x8b,0x49,0x9b,0xb2,0x39,0xa6,0x77,0x84,0x93,0xde
    };
    static const uint8_t xaudio2_debug_clsid[16] = {
        0x94,0x98,0x19,0x47,0xc2,0x7c,0x4d,0x44,0x98,0x73,0xce,0xd2,0x56,0x2c,0xc6,0x0e
    };
    static const uint8_t audioreverb_clsid[16] = {
        0x5a,0xc9,0xce,0xce,0x94,0xd8,0x1a,0x49,0xbe,0xe3,0x5e,0x10,0x6f,0xb5,0x9f,0x2d
    };
#endif
    static const struct {
        const uint8_t *clsid;
        uint32_t (*create)(uint32_t iid);
    } classes[] = {
        { filter_graph,        dshow_create_filtergraph },
#ifdef FNV_GAME_SKYRIM
        { xaudio2_clsid,       xaudio2_create },
        { xaudio2_debug_clsid, xaudio2_create },
        { audioreverb_clsid,   xaudio2_create_reverb },
#endif
    };
    uint32_t clsid=ARG(c,0),out=ARG(c,4);
    if(!out){RET(c,0x80004003u,5);return;}
    P32(out,0);
    if(!clsid||!ARG(c,3)){RET(c,0x80004003u,5);return;}
    for (size_t i = 0; i < sizeof classes / sizeof classes[0]; i++) {
        if (!memcmp(MEM + clsid, classes[i].clsid, 16)) {
            if (ARG(c, 1)) { RET(c, 0x80040110u, 5); return; }
            uint32_t object = classes[i].create(ARG(c, 3));
            P32(out, object);
            RET(c, object ? 0 : 0x80004002u, 5);
            return;
        }
    }
    uint32_t g = ARG(c, 0), ig = ARG(c, 3);
    fprintf(stderr, "[host] CoCreateInstance clsid {%08x-%04x-%04x-...} iid {%08x-...} -> REGDB_E_CLASSNOTREG\n",
            G32(g), G32(g + 4) & 0xFFFF, G32(g + 4) >> 16, G32(ig));
    P32(ARG(c, 4), 0); RET(c, 0x80040154u, 5);
}

// ---- winmm -------------------------------------------------------------------------------------
SHIM(timeGetTime) { RET(c, (uint32_t)(clock_gettime_nsec_np(CLOCK_UPTIME_RAW) / 1000000ull), 0); }

SHIM(waveOutGetNumDevs) { RET(c, 0, 0); }
SHIM(waveInGetNumDevs) { RET(c, 0, 0); }

SHIM_TABLE(win_shims,
    E(RegisterClassA) E(CreateWindowExA) E(DestroyWindow) E(ShowWindow) E(UpdateWindow) E(SetWindowPos)
    E(SetWindowTextA) E(GetWindowTextA) E(GetClassNameA) E(GetWindow) E(GetWindowLongA) E(SetWindowLongA) E(GetClassLongA)
    E(EnumChildWindows) E(FindWindowA) E(GetDesktopWindow) E(GetProcessWindowStation) E(GetUserObjectInformationW) E(GetActiveWindow) E(GetForegroundWindow) E(GetFocus) E(SetForegroundWindow) E(ScreenToClient) E(ClientToScreen) E(GetClientRect) E(GetWindowRect)
    E(AdjustWindowRect) E(AdjustWindowRectEx) E(GetSystemMetrics) E(EnumDisplayDevicesA) E(LoadImageA) E(LoadIconA)
    E(LoadCursorA) E(SetCursor) E(ShowCursor) E(GetDoubleClickTime) E(SwapMouseButton) E(GetAsyncKeyState)
    E(GetKeyState) E(GetKeyboardLayout) E(MapVirtualKeyA) E(ToUnicode) E(ClipCursor) E(SetCursorPos) E(GetCursorPos)
    E(GetDlgItem) E(GetWindowInfo) E(SendInput)
    E(SetWindowsHookExA) E(UnhookWindowsHookEx) E(CallNextHookEx) E(PeekMessageA) E(TranslateMessage)
    E(DispatchMessageA) E(SendMessageA) E(DefWindowProcA) E(MessageBoxA) E(GetStockObject)
    E(GetDC) E(CreateDCA) E(ExtEscape) E(DeleteDC)
    E(InitCommonControlsEx) E(ImageList_LoadImageA) E(ImageList_Destroy) E(RegOpenKeyA) E(RegOpenKeyExA) E(RegCreateKeyExA)
    E(RegQueryValueExA) E(RegSetValueExA) E(RegCloseKey) E(GetUserNameA) E(GetUserNameW) E(SHGetFolderPathA) E(SHGetFolderPathW) E(ShellExecuteA)
    E(CommandLineToArgvW) E(CoInitialize) E(CoInitializeEx) E(CoUninitialize) E(CoFreeUnusedLibraries)
    E(CoTaskMemAlloc) E(CoTaskMemFree) E(CoCreateInstance) E(timeGetTime) E(waveOutGetNumDevs) E(waveInGetNumDevs))
