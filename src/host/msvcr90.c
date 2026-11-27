#include <ctype.h>
#include <errno.h>
#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#include "shims.h"

static uint32_t run_initializers(CPU *cpu, bool stop_on_error) {
    uint32_t begin = ARG(cpu, 0);
    uint32_t end = ARG(cpu, 1);
    uint32_t stack = REG(cpu, R_ESP);

    if (begin > end || ((begin | end) & 3u))
        rt_trap(cpu, TRAP_IMPORT, begin);

    for (uint32_t slot = begin; slot < end; slot += sizeof(uint32_t)) {
        uint32_t initializer = G32(slot);
        if (!initializer)
            continue;

        P32(stack - 4, HOST_EXIT_THUNK);
        SETREG(cpu, R_ESP, stack - 4);
        rt_call(cpu, initializer);
        SETREG(cpu, R_ESP, stack);

        uint32_t result = REG(cpu, R_EAX);
        if (stop_on_error && result)
            return result;
    }
    return 0;
}

SHIM(_initterm) {
    run_initializers(c, false);
    RET(c, 0, 0);
}

SHIM(_initterm_e) {
    uint32_t result = run_initializers(c, true);
    RET(c, result, 0);
}

static uint32_t pointer_cookie;
static pthread_once_t pointer_cookie_once = PTHREAD_ONCE_INIT;

static void create_pointer_cookie(void) {
    pointer_cookie = arc4random();
}

SHIM(_encode_pointer) {
    pthread_once(&pointer_cookie_once, create_pointer_cookie);
    RET(c, ARG(c, 0) ^ pointer_cookie, 0);
}

SHIM(_controlfp_s) {
    const uint32_t precision_mask = 0x30000;
    const unsigned x87_control_offset = 4256;
    uint32_t value = ARG(c, 1);
    uint32_t mask = ARG(c, 2);
    uint16_t control = (uint16_t)LD(c->r + x87_control_offset, 2);

    if (mask & ~precision_mask || (mask && (value & precision_mask) != 0x10000)) {
        RET(c, EINVAL, 0);
        return;
    }
    if (mask) {
        control = (control & ~0x300u) | 0x200u;
        ST(c->r + x87_control_offset, control, 2);
    }
    uint32_t current = ARG(c, 0);
    if (current) {
        uint32_t precision = (control & 0x300u) == 0x200u ? 0x10000u
                           : (control & 0x300u) == 0 ? 0x20000u : 0;
        uint32_t exceptions = ((control & 0x01u) << 4) | ((control & 0x02u) << 18)
                            | ((control & 0x04u) << 1) | ((control & 0x08u) >> 1)
                            | ((control & 0x10u) >> 3) | ((control & 0x20u) >> 5);
        P32(current, precision | exceptions | ((control & 0x0c00u) >> 2)
                    | ((control & 0x1000u) << 6));
    }
    RET(c, 0, 0);
}

typedef struct ExitHandler {
    uint32_t address;
    struct ExitHandler *next;
} ExitHandler;

static pthread_mutex_t exit_lock = PTHREAD_MUTEX_INITIALIZER;
static ExitHandler *exit_handlers;

SHIM(_onexit) {
    uint32_t address = ARG(c, 0);
    ExitHandler *entry = address ? malloc(sizeof(*entry)) : NULL;
    if (!entry) {
        RET(c, 0, 0);
        return;
    }
    entry->address = address;
    pthread_mutex_lock(&exit_lock);
    entry->next = exit_handlers;
    exit_handlers = entry;
    pthread_mutex_unlock(&exit_lock);
    RET(c, address, 0);
}

SHIM(_cexit) {
    uint32_t stack = REG(c, R_ESP);
    for (;;) {
        pthread_mutex_lock(&exit_lock);
        ExitHandler *entry = exit_handlers;
        if (entry)
            exit_handlers = entry->next;
        pthread_mutex_unlock(&exit_lock);
        if (!entry)
            break;

        uint32_t address = entry->address;
        free(entry);
        P32(stack - 4, HOST_EXIT_THUNK);
        SETREG(c, R_ESP, stack - 4);
        rt_call(c, address);
        SETREG(c, R_ESP, stack);
    }
    RET(c, 0, 0);
}

static uint32_t file_mode;
static uint32_t commit_mode;
static _Thread_local uint32_t thread_locale_mode = 2;

static uint32_t guest_int(uint32_t *slot) {
    if (!*slot) {
        *slot = gmalloc(sizeof(uint32_t));
        P32(*slot, 0);
    }
    return *slot;
}

SHIM(__set_app_type) {
    // The macOS host manages standard streams independently of the Windows subsystem.
    RET(c, 0, 0);
}

SHIM(__p__fmode) {
    RET(c, guest_int(&file_mode), 0);
}

SHIM(__p__commode) {
    RET(c, guest_int(&commit_mode), 0);
}

SHIM(_configthreadlocale) {
    uint32_t mode = ARG(c, 0);
    uint32_t previous = thread_locale_mode;
    if (mode == 1 || mode == 2)
        thread_locale_mode = mode;
    RET(c, previous, 0);
}

SHIM(malloc) {
    uint32_t size = ARG(c, 0);
    RET(c, gmalloc(size ? size : 1), 0);
}

SHIM(calloc) {
    uint64_t size = (uint64_t)ARG(c, 0) * ARG(c, 1);
    if (size > UINT32_MAX) {
        RET(c, 0, 0);
        return;
    }
    uint32_t address = gmalloc(size ? (uint32_t)size : 1);
    if (address)
        memset(MEM + address, 0, size);
    RET(c, address, 0);
}

SHIM(realloc) {
    uint32_t address = ARG(c, 0);
    uint32_t size = ARG(c, 1);
    if (address && !size) {
        gfree(address);
        RET(c, 0, 0);
        return;
    }
    RET(c, grealloc(address, size ? size : 1), 0);
}

SHIM(_msize) {
    uint32_t address = ARG(c, 0);
    RET(c, address ? gsize(address) : UINT32_MAX, 0);
}

SHIM(free) {
    uint32_t address = ARG(c, 0);
    if (address)
        gfree(address);
    RET(c, 0, 0);
}

static void check_guest_range(CPU *cpu, uint32_t address, uint32_t size) {
    if (size && (!address || (uint64_t)address + size > (1ull << 32)))
        rt_trap(cpu, TRAP_IMPORT, address);
}

SHIM(memset) {
    uint32_t target = ARG(c, 0);
    uint32_t size = ARG(c, 2);
    check_guest_range(c, target, size);
    memset(MEM + target, (unsigned char)ARG(c, 1), size);
    RET(c, target, 0);
}

SHIM(memmove) {
    uint32_t target = ARG(c, 0);
    uint32_t source = ARG(c, 1);
    uint32_t size = ARG(c, 2);
    check_guest_range(c, target, size);
    check_guest_range(c, source, size);
    memmove(MEM + target, MEM + source, size);
    RET(c, target, 0);
}

SHIM(memcmp) {
    uint32_t left = ARG(c, 0);
    uint32_t right = ARG(c, 1);
    uint32_t size = ARG(c, 2);
    check_guest_range(c, left, size);
    check_guest_range(c, right, size);
    RET(c, (uint32_t)memcmp(MEM + left, MEM + right, size), 0);
}

SHIM(strcmp) {
    uint32_t left = ARG(c, 0);
    uint32_t right = ARG(c, 1);
    if (!left || !right)
        rt_trap(c, TRAP_IMPORT, left ? right : left);
    RET(c, (uint32_t)strcmp((const char *)(MEM + left), (const char *)(MEM + right)), 0);
}

SHIM(strncmp) {
    uint32_t left = ARG(c, 0);
    uint32_t right = ARG(c, 1);
    uint32_t size = ARG(c, 2);
    if (size && (!left || !right))
        rt_trap(c, TRAP_IMPORT, left ? right : left);
    RET(c, (uint32_t)strncmp((const char *)(MEM + left), (const char *)(MEM + right), size), 0);
}

SHIM(_stricmp) {
    uint32_t left = ARG(c, 0);
    uint32_t right = ARG(c, 1);
    if (!left || !right)
        rt_trap(c, TRAP_IMPORT, left ? right : left);
    RET(c, (uint32_t)strcasecmp((const char *)(MEM + left), (const char *)(MEM + right)), 0);
}

SHIM(_strnicmp) {
    uint32_t left = ARG(c, 0);
    uint32_t right = ARG(c, 1);
    uint32_t size = ARG(c, 2);
    if (size && (!left || !right))
        rt_trap(c, TRAP_IMPORT, left ? right : left);
    RET(c, (uint32_t)strncasecmp((const char *)(MEM + left), (const char *)(MEM + right), size), 0);
}

// Hot single-byte classification/conversion exports. MSVC uses the C locale by default;
// returning a normalized boolean (rather than the host table's bit value) is sufficient for
// the game's boolean tests and avoids leaking glibc's ctype table values into guest code.
#define CTYPE_SHIM(name) SHIM(name) { RET(c, (uint32_t)!!name((unsigned char)ARG(c, 0)), 0); }
CTYPE_SHIM(isspace)
CTYPE_SHIM(isalnum)
CTYPE_SHIM(isalpha)
CTYPE_SHIM(isdigit)
CTYPE_SHIM(isxdigit)
#undef CTYPE_SHIM

SHIM(tolower) { RET(c, (uint32_t)tolower((unsigned char)ARG(c, 0)), 0); }
SHIM(toupper) { RET(c, (uint32_t)toupper((unsigned char)ARG(c, 0)), 0); }

SHIM(strchr) {
    uint32_t string = ARG(c, 0);
    if (!string) { RET(c, 0, 0); return; }
    uint8_t *found = (uint8_t *)strchr((const char *)(MEM + string), (int)(unsigned char)ARG(c, 1));
    RET(c, found ? (uint32_t)(found - MEM) : 0, 0);
}

SHIM(strspn) {
    uint32_t string = ARG(c, 0), accept = ARG(c, 1);
    if (!string || !accept) { RET(c, 0, 0); return; }
    RET(c, (uint32_t)strspn((const char *)(MEM + string), (const char *)(MEM + accept)), 0);
}

SHIM(strstr) {
    uint32_t haystack = ARG(c, 0), needle = ARG(c, 1);
    if (!haystack || !needle) { RET(c, 0, 0); return; }
    uint8_t *found = (uint8_t *)strstr((const char *)(MEM + haystack), (const char *)(MEM + needle));
    RET(c, found ? (uint32_t)(found - MEM) : 0, 0);
}

SHIM(memchr) {
    uint32_t string = ARG(c, 0), size = ARG(c, 2);
    if (!string || !size) { RET(c, 0, 0); return; }
    uint8_t *found = (uint8_t *)memchr(MEM + string, (int)(unsigned char)ARG(c, 1), size);
    RET(c, found ? (uint32_t)(found - MEM) : 0, 0);
}

SHIM(atoi) {
    uint32_t string = ARG(c, 0);
    RET(c, string ? (uint32_t)atoi((const char *)(MEM + string)) : 0, 0);
}

// MSVC's rand/srand use a 32-bit LCG, not the host libc sequence. Keep the original
// algorithm so replacing the fallback does not change determinism.
static uint32_t msvc_rand_state = 1;
static pthread_mutex_t msvc_rand_lock = PTHREAD_MUTEX_INITIALIZER;

SHIM(srand) {
    pthread_mutex_lock(&msvc_rand_lock);
    msvc_rand_state = ARG(c, 0);
    pthread_mutex_unlock(&msvc_rand_lock);
    RET(c, 0, 0);
}

SHIM(rand) {
    pthread_mutex_lock(&msvc_rand_lock);
    msvc_rand_state = msvc_rand_state * 214013u + 2531011u;
    uint32_t value = (msvc_rand_state >> 16) & 0x7fff;
    pthread_mutex_unlock(&msvc_rand_lock);
    RET(c, value, 0);
}

// MSVC cdecl double arguments live at [ESP+4..]; the return value is ST0, matching the
// native generated-code convention (no TOP change at a call boundary).
static double guest_double_arg(CPU *c, int index) {
    double value;
    memcpy(&value, MEM + REG(c, R_ESP) + 4 + 8 * index, sizeof value);
    return value;
}

static void return_double(CPU *c, double value) {
    memcpy(c->r + 4352, &value, sizeof value);
}

static double guest_st0(CPU *c) {
    double value;
    memcpy(&value, c->r + 4352, sizeof value);
    return value;
}

SHIM(floor) { double x = guest_double_arg(c, 0); return_double(c, floor(x)); RET(c, 0, 0); }
SHIM(ceil) { double x = guest_double_arg(c, 0); return_double(c, ceil(x)); RET(c, 0, 0); }
SHIM(atof) {
    uint32_t string = ARG(c, 0);
    return_double(c, string ? atof((const char *)(MEM + string)) : 0.0);
    RET(c, 0, 0);
}

// The single-argument _CI* CRT intrinsics take their argument in ST0 and return in ST0.
// Multi-argument variants (atan2/fmod/pow) are left on the interpreter path for now.
SHIM(_CIsqrt) { return_double(c, sqrt(guest_st0(c))); RET(c, 0, 0); }
SHIM(_CIsin) { return_double(c, sin(guest_st0(c))); RET(c, 0, 0); }
SHIM(_CIcos) { return_double(c, cos(guest_st0(c))); RET(c, 0, 0); }
SHIM(_CItan) { return_double(c, tan(guest_st0(c))); RET(c, 0, 0); }
SHIM(_CIasin) { return_double(c, asin(guest_st0(c))); RET(c, 0, 0); }
SHIM(_CIacos) { return_double(c, acos(guest_st0(c))); RET(c, 0, 0); }
SHIM(_CIlog) { return_double(c, log(guest_st0(c))); RET(c, 0, 0); }

SHIM(_CIatan2) {
    double y, x;
    memcpy(&y, c->r + 4368, sizeof y);
    memcpy(&x, c->r + 4352, sizeof x);
    double r = atan2(y, x);
    memcpy(c->r + 4352, &r, sizeof r);
    memmove(c->r + 4368, c->r + 4384, 6 * 16);
    TOPADJ(c->r, 1);
    SYNC_FPUSW(c->r);
    RET(c, 0, 0);
}

SHIM(_CIfmod) {
    double x, y;
    memcpy(&x, c->r + 4368, sizeof x);
    memcpy(&y, c->r + 4352, sizeof y);
    double r = fmod(x, y);
    memcpy(c->r + 4352, &r, sizeof r);
    memmove(c->r + 4368, c->r + 4384, 6 * 16);
    TOPADJ(c->r, 1);
    SYNC_FPUSW(c->r);
    RET(c, 0, 0);
}

SHIM(_CIpow) {
    double base, expv;
    memcpy(&base, c->r + 4368, sizeof base);
    memcpy(&expv, c->r + 4352, sizeof expv);
    double r = pow(base, expv);
    memcpy(c->r + 4352, &r, sizeof r);
    memmove(c->r + 4368, c->r + 4384, 6 * 16);
    TOPADJ(c->r, 1);
    SYNC_FPUSW(c->r);
    RET(c, 0, 0);
}

SHIM(_isnan) { RET(c, (uint32_t)isnan(guest_double_arg(c, 0)), 0); }
SHIM(_finite) { RET(c, (uint32_t)isfinite(guest_double_arg(c, 0)), 0); }

SHIM(_fpclass) {
    double x = guest_double_arg(c, 0);
    uint64_t bits;
    memcpy(&bits, &x, sizeof bits);
    uint32_t sign = (uint32_t)(bits >> 63);
    uint32_t exp = (uint32_t)((bits >> 52) & 0x7ffu);
    uint64_t frac = bits & ((1ull << 52) - 1ull);
    uint32_t cls;
    if (exp == 0x7ffu) {
        if (frac == 0) cls = sign ? 0x0004u : 0x0200u;
        else cls = (frac & (1ull << 51)) ? 0x0002u : 0x0001u;
    } else if (exp == 0) {
        if (frac == 0) cls = sign ? 0x0020u : 0x0040u;
        else cls = sign ? 0x0010u : 0x0080u;
    } else {
        cls = sign ? 0x0008u : 0x0100u;
    }
    RET(c, cls, 0);
}

SHIM(strncpy) {
    uint32_t dst = ARG(c, 0), src = ARG(c, 1), n = ARG(c, 2);
    check_guest_range(c, dst, n);
    if (n && !src) rt_trap(c, TRAP_IMPORT, src);
    strncpy((char *)(MEM + dst), (const char *)(MEM + src), n);
    RET(c, dst, 0);
}

SHIM(strncpy_s) {
    uint32_t dst = ARG(c, 0), dst_cap = ARG(c, 1), src = ARG(c, 2), count = ARG(c, 3);
    if (!dst || !dst_cap) { RET(c, EINVAL, 0); return; }
    if (!src) { MEM[dst] = 0; RET(c, EINVAL, 0); return; }
    const char *s = (const char *)(MEM + src);
    char *d = (char *)(MEM + dst);
    bool truncate = (count == 0xffffffffu);
    size_t max_copy = truncate ? (dst_cap - 1) : (count < dst_cap - 1 ? count : dst_cap - 1);
    size_t i = 0;
    while (i < max_copy && s[i]) { d[i] = s[i]; i++; }
    d[i] = 0;
    if (!truncate && s[i] && i == dst_cap - 1 && count >= dst_cap) {
        d[0] = 0;
        RET(c, ERANGE, 0);
        return;
    }
    RET(c, (truncate && s[i]) ? 80u /* STRUNCATE */ : 0u, 0);
}

SHIM(strcspn) {
    uint32_t s = ARG(c, 0), reject = ARG(c, 1);
    if (!s || !reject) { RET(c, 0, 0); return; }
    RET(c, (uint32_t)strcspn((const char *)(MEM + s), (const char *)(MEM + reject)), 0);
}

SHIM(strtoul) {
    uint32_t nptr = ARG(c, 0), endptr = ARG(c, 1);
    int base = (int)ARG(c, 2);
    const char *s = nptr ? (const char *)(MEM + nptr) : "";
    char *end = NULL;
    unsigned long v = strtoul(s, &end, base);
    if (endptr) P32(endptr, end ? nptr + (uint32_t)(end - s) : nptr);
    RET(c, (uint32_t)v, 0);
}

SHIM(wcsrchr) {
    uint32_t ws = ARG(c, 0);
    uint16_t wc = (uint16_t)ARG(c, 1);
    if (!ws) { RET(c, 0, 0); return; }
    uint32_t last = 0;
    for (uint32_t p = ws;; p += 2) {
        uint16_t ch;
        memcpy(&ch, MEM + p, 2);
        if (ch == wc) last = p;
        if (!ch) break;
    }
    RET(c, last, 0);
}

SHIM(_time64) {
    uint32_t timer = ARG(c, 0);
    int64_t t = (int64_t)time(NULL);
    if (timer) memcpy(MEM + timer, &t, 8);
    SETREG(c, R_EDX, (uint32_t)((uint64_t)t >> 32));
    RET(c, (uint32_t)t, 0);
}

SHIM(_waccess_s) {
    uint32_t wpath = ARG(c, 0);
    int mode = (int)ARG(c, 1);
    if (!wpath) { RET(c, EINVAL, 0); return; }
    char win[1024], hp[1024];
    w2a(wpath, win, sizeof win);
    host_path(win, hp, sizeof hp);
    int amode = F_OK;
    if (mode == 2) amode = W_OK;
    else if (mode == 4) amode = R_OK;
    else if (mode == 6) amode = R_OK | W_OK;
    RET(c, access(hp, amode) == 0 ? 0u : (uint32_t)errno, 0);
}

SHIM(_wstat64) {
    uint32_t wpath = ARG(c, 0), st_out = ARG(c, 1);
    if (!wpath || !st_out) { RET(c, 0xffffffffu, 0); return; }
    char win[1024], hp[1024];
    w2a(wpath, win, sizeof win);
    host_path(win, hp, sizeof hp);
    struct stat st;
    if (stat(hp, &st) != 0) { RET(c, 0xffffffffu, 0); return; }
    uint8_t buf[56];
    memset(buf, 0, sizeof buf);
    uint32_t dev = (uint32_t)st.st_dev;
    uint16_t mode = 0;
    if (S_ISDIR(st.st_mode)) mode |= 0x4000u;
    else if (S_ISREG(st.st_mode)) mode |= 0x8000u;
    if (st.st_mode & S_IRUSR) mode |= 0x0100u;
    if (st.st_mode & S_IWUSR) mode |= 0x0080u;
    if (st.st_mode & S_IXUSR) mode |= 0x0040u;
    int16_t nlink = (int16_t)st.st_nlink;
    int64_t sz = (int64_t)st.st_size;
    int64_t at = (int64_t)st.st_atime;
    int64_t mt = (int64_t)st.st_mtime;
    int64_t ct = (int64_t)st.st_ctime;
    memcpy(buf + 0x00, &dev, 4);
    memcpy(buf + 0x06, &mode, 2);
    memcpy(buf + 0x08, &nlink, 2);
    memcpy(buf + 0x10, &dev, 4);
    memcpy(buf + 0x18, &sz, 8);
    memcpy(buf + 0x20, &at, 8);
    memcpy(buf + 0x28, &mt, 8);
    memcpy(buf + 0x30, &ct, 8);
    memcpy(MEM + st_out, buf, sizeof buf);
    RET(c, 0, 0);
}

enum { FMT_NONE = 0, FMT_HH, FMT_H, FMT_L, FMT_LL };

static void fmt_emit(char *out, size_t cap, size_t *total, const char *s, size_t n) {
    if (out && cap > 0 && *total < cap - 1) {
        size_t avail = (cap - 1) - *total;
        size_t copy = n < avail ? n : avail;
        memcpy(out + *total, s, copy);
    }
    *total += n;
}

static int guest_vsnprintf(char *out, size_t cap, const char *fmt, uint32_t va, bool wide_default) {
    size_t total = 0;
    const char *p = fmt;
    while (*p) {
        if (*p != '%') {
            const char *next = strchr(p, '%');
            size_t n = next ? (size_t)(next - p) : strlen(p);
            fmt_emit(out, cap, &total, p, n);
            p += n;
            continue;
        }
        p++;
        if (*p == '%') {
            fmt_emit(out, cap, &total, "%", 1);
            p++;
            continue;
        }

        char spec[64];
        size_t si = 0;
        spec[si++] = '%';
        while (*p && strchr("-+ #0", *p)) {
            if (si < sizeof(spec) - 16) spec[si++] = *p;
            p++;
        }
        if (*p == '*') {
            int w = (int)G32(va); va += 4;
            si += (size_t)snprintf(spec + si, sizeof(spec) - si, "%d", w);
            p++;
        } else {
            while (*p >= '0' && *p <= '9') {
                if (si < sizeof(spec) - 16) spec[si++] = *p;
                p++;
            }
        }
        if (*p == '.') {
            if (si < sizeof(spec) - 16) spec[si++] = *p;
            p++;
            if (*p == '*') {
                int pr = (int)G32(va); va += 4;
                if (pr >= 0) si += (size_t)snprintf(spec + si, sizeof(spec) - si, "%d", pr);
                else if (si > 0 && spec[si - 1] == '.') si--;
                p++;
            } else {
                while (*p >= '0' && *p <= '9') {
                    if (si < sizeof(spec) - 16) spec[si++] = *p;
                    p++;
                }
            }
        }

        int len = FMT_NONE;
        if (p[0] == 'I' && p[1] == '6' && p[2] == '4') { len = FMT_LL; p += 3; }
        else if (p[0] == 'I' && p[1] == '3' && p[2] == '2') { len = FMT_NONE; p += 3; }
        else if (p[0] == 'I') { len = FMT_NONE; p += 1; }
        else if (p[0] == 'l' && p[1] == 'l') { len = FMT_LL; p += 2; }
        else if (p[0] == 'l') { len = FMT_L; p += 1; }
        else if (p[0] == 'h' && p[1] == 'h') { len = FMT_HH; p += 2; }
        else if (p[0] == 'h') { len = FMT_H; p += 1; }
        else if (p[0] == 'w') { len = FMT_L; p += 1; }
        else if (p[0] == 'z' || p[0] == 't') { len = FMT_NONE; p += 1; }

        char conv = *p ? *p++ : '\0';
        if (!conv) break;

        char buf[4096];
        char *dyn = NULL;
        const char *res = buf;
        int n = 0;

        if (conv == 's' || conv == 'S') {
            uint32_t addr = G32(va); va += 4;
            bool is_wide = (conv == 'S') || (conv == 's' && (len == FMT_L || (wide_default && len != FMT_H)));
            char *wbuf = NULL;
            const char *sarg = "(null)";
            if (addr) {
                if (is_wide) {
                    uint32_t wl = wlen(addr);
                    wbuf = malloc(wl + 1);
                    if (wbuf) { w2a(addr, wbuf, wl + 1); sarg = wbuf; }
                } else {
                    sarg = (const char *)(MEM + addr);
                }
            }
            spec[si++] = 's'; spec[si] = '\0';
            n = snprintf(buf, sizeof(buf), spec, sarg);
            if (n >= (int)sizeof(buf)) {
                dyn = malloc((size_t)n + 1);
                if (dyn) { snprintf(dyn, (size_t)n + 1, spec, sarg); res = dyn; }
            }
            free(wbuf);
        } else if (conv == 'c' || conv == 'C') {
            int ch = (int)(unsigned char)G32(va); va += 4;
            spec[si++] = 'c'; spec[si] = '\0';
            n = snprintf(buf, sizeof(buf), spec, ch);
        } else if (conv == 'd' || conv == 'i') {
            if (len == FMT_LL) {
                int64_t v; memcpy(&v, MEM + va, 8); va += 8;
                spec[si++] = 'l'; spec[si++] = 'l'; spec[si++] = conv; spec[si] = '\0';
                n = snprintf(buf, sizeof(buf), spec, v);
            } else {
                int32_t v = (int32_t)G32(va); va += 4;
                if (len == FMT_HH) { spec[si++] = 'h'; spec[si++] = 'h'; }
                else if (len == FMT_H) { spec[si++] = 'h'; }
                spec[si++] = conv; spec[si] = '\0';
                n = snprintf(buf, sizeof(buf), spec, v);
            }
        } else if (conv == 'u' || conv == 'o' || conv == 'x' || conv == 'X') {
            if (len == FMT_LL) {
                uint64_t v; memcpy(&v, MEM + va, 8); va += 8;
                spec[si++] = 'l'; spec[si++] = 'l'; spec[si++] = conv; spec[si] = '\0';
                n = snprintf(buf, sizeof(buf), spec, v);
            } else {
                uint32_t v = G32(va); va += 4;
                if (len == FMT_HH) { spec[si++] = 'h'; spec[si++] = 'h'; }
                else if (len == FMT_H) { spec[si++] = 'h'; }
                spec[si++] = conv; spec[si] = '\0';
                n = snprintf(buf, sizeof(buf), spec, v);
            }
        } else if (conv == 'p') {
            uint32_t v = G32(va); va += 4;
            n = snprintf(buf, sizeof(buf), "%08X", v);
        } else if (strchr("fFeEgGaA", conv)) {
            double v; memcpy(&v, MEM + va, 8); va += 8;
            spec[si++] = conv; spec[si] = '\0';
            n = snprintf(buf, sizeof(buf), spec, v);
            if (n >= (int)sizeof(buf)) {
                dyn = malloc((size_t)n + 1);
                if (dyn) { snprintf(dyn, (size_t)n + 1, spec, v); res = dyn; }
            }
        } else if (conv == 'n') {
            uint32_t ptr = G32(va); va += 4;
            if (ptr) {
                if (len == FMT_HH) MEM[ptr] = (uint8_t)total;
                else if (len == FMT_H) { uint16_t v = (uint16_t)total; memcpy(MEM + ptr, &v, 2); }
                else if (len == FMT_LL) { int64_t v = (int64_t)total; memcpy(MEM + ptr, &v, 8); }
                else P32(ptr, (uint32_t)total);
            }
            n = 0;
        } else {
            buf[0] = conv; buf[1] = '\0'; n = 1;
        }

        if (n > 0) fmt_emit(out, cap, &total, res, (size_t)n);
        free(dyn);
    }
    if (out && cap > 0) {
        size_t nul = total < cap ? total : cap - 1;
        out[nul] = '\0';
    }
    return (int)total;
}

SHIM(_vscprintf) {
    uint32_t fmt = ARG(c, 0), va = ARG(c, 1);
    if (!fmt) { RET(c, 0xffffffffu, 0); return; }
    RET(c, (uint32_t)guest_vsnprintf(NULL, 0, (const char *)(MEM + fmt), va, false), 0);
}

SHIM(_vsnprintf_s) {
    uint32_t buf = ARG(c, 0), cap = ARG(c, 1), count = ARG(c, 2), fmt = ARG(c, 3), va = ARG(c, 4);
    if (!buf || !cap || !fmt) { RET(c, 0xffffffffu, 0); return; }
    bool truncate = (count == 0xffffffffu);
    size_t limit = truncate ? cap : (count + 1 < cap ? count + 1 : cap);
    int n = guest_vsnprintf((char *)(MEM + buf), limit, (const char *)(MEM + fmt), va, false);
    if (n < 0 || (size_t)n >= limit) {
        if (!truncate && (size_t)n >= cap) MEM[buf] = '\0';
        RET(c, 0xffffffffu, 0);
        return;
    }
    RET(c, (uint32_t)n, 0);
}

SHIM(sprintf) {
    uint32_t buf = ARG(c, 0), fmt = ARG(c, 1);
    if (!buf || !fmt) { RET(c, 0xffffffffu, 0); return; }
    uint32_t va = REG(c, R_ESP) + 4 + 2 * 4;
    int n = guest_vsnprintf((char *)(MEM + buf), 0x10000000u, (const char *)(MEM + fmt), va, false);
    RET(c, (uint32_t)n, 0);
}

SHIM(sprintf_s) {
    uint32_t buf = ARG(c, 0), cap = ARG(c, 1), fmt = ARG(c, 2);
    if (!buf || !cap || !fmt) { RET(c, 0xffffffffu, 0); return; }
    uint32_t va = REG(c, R_ESP) + 4 + 3 * 4;
    int n = guest_vsnprintf((char *)(MEM + buf), cap, (const char *)(MEM + fmt), va, false);
    if (n < 0 || (size_t)n >= cap) {
        MEM[buf] = '\0';
        RET(c, 0xffffffffu, 0);
        return;
    }
    RET(c, (uint32_t)n, 0);
}

SHIM(_vscwprintf) {
    uint32_t wfmt = ARG(c, 0), va = ARG(c, 1);
    if (!wfmt) { RET(c, 0xffffffffu, 0); return; }
    uint32_t fl = wlen(wfmt);
    char *fmt = malloc(fl + 1);
    if (!fmt) { RET(c, 0xffffffffu, 0); return; }
    w2a(wfmt, fmt, fl + 1);
    int n = guest_vsnprintf(NULL, 0, fmt, va, true);
    free(fmt);
    RET(c, (uint32_t)n, 0);
}

SHIM(_vsnwprintf_s) {
    uint32_t wbuf = ARG(c, 0), cap = ARG(c, 1), count = ARG(c, 2), wfmt = ARG(c, 3), va = ARG(c, 4);
    if (!wbuf || !cap || !wfmt) { RET(c, 0xffffffffu, 0); return; }
    uint32_t fl = wlen(wfmt);
    char *fmt = malloc(fl + 1);
    bool truncate = (count == 0xffffffffu);
    size_t limit = truncate ? cap : (count + 1 < cap ? count + 1 : cap);
    char *tmp = malloc(limit + 1);
    if (!fmt || !tmp) { free(fmt); free(tmp); RET(c, 0xffffffffu, 0); return; }
    w2a(wfmt, fmt, fl + 1);
    int n = guest_vsnprintf(tmp, limit, fmt, va, true);
    free(fmt);
    for (size_t i = 0; i < limit; i++) {
        uint16_t ch = (unsigned char)tmp[i];
        memcpy(MEM + wbuf + 2 * i, &ch, 2);
        if (!ch) break;
    }
    free(tmp);
    if (n < 0 || (size_t)n >= limit) {
        if (!truncate && (size_t)n >= cap) { uint16_t z = 0; memcpy(MEM + wbuf, &z, 2); }
        RET(c, 0xffffffffu, 0);
        return;
    }
    RET(c, (uint32_t)n, 0);
}

SHIM(sscanf_s) {
    uint32_t buf = ARG(c, 0), fmt_addr = ARG(c, 1);
    if (!buf || !fmt_addr) { RET(c, 0xffffffffu, 0); return; }
    const char *input_start = (const char *)(MEM + buf);
    const char *input = input_start;
    const char *p = (const char *)(MEM + fmt_addr);
    uint32_t va = REG(c, R_ESP) + 4 + 2 * 4;
    int assigned = 0;
    bool eof_hit = false;

    while (*p) {
        if (isspace((unsigned char)*p)) {
            while (isspace((unsigned char)*input)) input++;
            while (isspace((unsigned char)*p)) p++;
            continue;
        }
        if (*p != '%') {
            if (*input != *p) { if (!*input) eof_hit = true; break; }
            input++; p++;
            continue;
        }
        p++;
        if (*p == '%') {
            if (*input != '%') { if (!*input) eof_hit = true; break; }
            input++; p++;
            continue;
        }

        bool suppress = false;
        if (*p == '*') { suppress = true; p++; }

        unsigned width = 0;
        bool has_width = false;
        while (*p >= '0' && *p <= '9') {
            has_width = true;
            width = width * 10u + (unsigned)(*p - '0');
            p++;
        }

        int len = FMT_NONE;
        if (p[0] == 'I' && p[1] == '6' && p[2] == '4') { len = FMT_LL; p += 3; }
        else if (p[0] == 'I' && p[1] == '3' && p[2] == '2') { len = FMT_NONE; p += 3; }
        else if (p[0] == 'l' && p[1] == 'l') { len = FMT_LL; p += 2; }
        else if (p[0] == 'l') { len = FMT_L; p += 1; }
        else if (p[0] == 'h' && p[1] == 'h') { len = FMT_HH; p += 2; }
        else if (p[0] == 'h') { len = FMT_H; p += 1; }

        char conv = *p ? *p++ : '\0';
        if (!conv) break;

        if (conv == 'n') {
            if (!suppress) {
                uint32_t dst = G32(va); va += 4;
                if (dst) P32(dst, (uint32_t)(input - input_start));
            }
            continue;
        }

        if (!*input && conv != '[') { eof_hit = true; break; }

        char spec[256];
        size_t si = 0;
        spec[si++] = '%';
        if (suppress) spec[si++] = '*';

        if (conv == 's' || conv == 'c' || conv == '[') {
            uint32_t dst = 0, cap = 0;
            if (!suppress) {
                dst = G32(va); va += 4;
                cap = G32(va); va += 4;
                if (!dst || !cap) break;
            }
            unsigned maxw = has_width ? width : (conv == 'c' ? 1u : (cap ? cap - 1u : 0u));
            if (!suppress && conv != 'c' && maxw >= cap) maxw = cap - 1u;
            if (!suppress && conv == 'c' && maxw > cap) break;
            if (has_width || !suppress) si += (size_t)snprintf(spec + si, sizeof(spec) - si, "%u", maxw);
            if (conv == '[') {
                spec[si++] = '[';
                if (*p == '^') { spec[si++] = *p++; }
                if (*p == ']') { spec[si++] = *p++; }
                while (*p && *p != ']' && si < sizeof(spec) - 5) spec[si++] = *p++;
                if (*p == ']') p++;
                spec[si++] = ']';
            } else {
                spec[si++] = conv;
            }
            spec[si++] = '%'; spec[si++] = 'n'; spec[si] = '\0';
            int consumed = -1;
            int r = suppress ? sscanf(input, spec, &consumed) : sscanf(input, spec, (char *)(MEM + dst), &consumed);
            if (consumed < 0) break;
            input += consumed;
            if (!suppress && r == 1) assigned++;
        } else if (strchr("diuoxXp", conv)) {
            if (has_width) si += (size_t)snprintf(spec + si, sizeof(spec) - si, "%u", width);
            if (len == FMT_LL) { spec[si++] = 'l'; spec[si++] = 'l'; }
            spec[si++] = (conv == 'p') ? 'x' : conv;
            spec[si++] = '%'; spec[si++] = 'n'; spec[si] = '\0';
            int consumed = -1;
            uint64_t val = 0;
            int r = suppress ? sscanf(input, spec, &consumed) : sscanf(input, spec, &val, &consumed);
            if (consumed < 0 || (!suppress && r != 1)) break;
            input += consumed;
            if (!suppress) {
                uint32_t dst = G32(va); va += 4;
                if (len == FMT_HH) MEM[dst] = (uint8_t)val;
                else if (len == FMT_H) { uint16_t v16 = (uint16_t)val; memcpy(MEM + dst, &v16, 2); }
                else if (len == FMT_LL) { memcpy(MEM + dst, &val, 8); }
                else { uint32_t v32 = (uint32_t)val; memcpy(MEM + dst, &v32, 4); }
                assigned++;
            }
        } else if (strchr("fFeEgGaA", conv)) {
            if (has_width) si += (size_t)snprintf(spec + si, sizeof(spec) - si, "%u", width);
            if (len == FMT_L) spec[si++] = 'l';
            spec[si++] = conv;
            spec[si++] = '%'; spec[si++] = 'n'; spec[si] = '\0';
            int consumed = -1;
            if (suppress) {
                int r = sscanf(input, spec, &consumed);
                (void)r;
                if (consumed < 0) break;
            } else if (len == FMT_L) {
                double v = 0;
                int r = sscanf(input, spec, &v, &consumed);
                if (r != 1 || consumed < 0) break;
                uint32_t dst = G32(va); va += 4;
                memcpy(MEM + dst, &v, 8);
                assigned++;
            } else {
                float v = 0;
                int r = sscanf(input, spec, &v, &consumed);
                if (r != 1 || consumed < 0) break;
                uint32_t dst = G32(va); va += 4;
                memcpy(MEM + dst, &v, 4);
                assigned++;
            }
            input += consumed;
        } else {
            break;
        }
    }
    RET(c, (assigned == 0 && eof_hit) ? 0xffffffffu : (uint32_t)assigned, 0);
}

// Host-backed FILE* table: each open stream gets a 32-byte guest _iobuf placeholder
// mapped to its host FILE* so fread/_fseeki64/getc/fclose avoid Unicorn re-entry.
typedef struct {
    uint32_t guest;
    FILE *host;
} GuestFile;

#define MAX_GUEST_FILES 256
static GuestFile guest_files[MAX_GUEST_FILES];
static pthread_mutex_t guest_files_lock = PTHREAD_MUTEX_INITIALIZER;

static FILE *lookup_guest_file(CPU *c, uint32_t guest) {
    if (!guest) return NULL;
    pthread_mutex_lock(&guest_files_lock);
    FILE *found = NULL;
    for (int i = 0; i < MAX_GUEST_FILES; i++) {
        if (guest_files[i].guest == guest) { found = guest_files[i].host; break; }
    }
    pthread_mutex_unlock(&guest_files_lock);
    if (!found) {
        fprintf(stderr, "[msvcr90] unknown guest FILE* %#x\n", guest);
        rt_trap(c, TRAP_IMPORT, guest);
    }
    return found;
}

static uint32_t open_guest_file(const char *win_path, const char *raw_mode) {
    if (!win_path || !raw_mode) return 0;
    char hp[1024], mode[32];
    host_path(win_path, hp, sizeof hp);
    size_t mi = 0;
    for (size_t i = 0; raw_mode[i] && mi < sizeof(mode) - 1; i++) {
        if (strchr("rwa+b", raw_mode[i])) mode[mi++] = raw_mode[i];
    }
    mode[mi] = '\0';
    FILE *f = fopen(hp, mode[0] ? mode : "rb");
    if (!f) return 0;
    uint32_t guest = gmalloc(32);
    if (!guest) { fclose(f); return 0; }
    memset(MEM + guest, 0, 32);
    pthread_mutex_lock(&guest_files_lock);
    int slot = -1;
    for (int i = 0; i < MAX_GUEST_FILES; i++) {
        if (!guest_files[i].guest) { guest_files[i].guest = guest; guest_files[i].host = f; slot = i; break; }
    }
    pthread_mutex_unlock(&guest_files_lock);
    if (slot < 0) { fclose(f); gfree(guest); return 0; }
    return guest;
}

SHIM(_wfsopen) {
    uint32_t wpath = ARG(c, 0), wmode = ARG(c, 1);
    if (!wpath || !wmode) { RET(c, 0, 0); return; }
    char win[1024], raw_mode[32];
    w2a(wpath, win, sizeof win);
    w2a(wmode, raw_mode, sizeof raw_mode);
    RET(c, open_guest_file(win, raw_mode), 0);
}

SHIM(fopen) {
    uint32_t path = ARG(c, 0), mode = ARG(c, 1);
    if (!path || !mode) { RET(c, 0, 0); return; }
    RET(c, open_guest_file((const char *)(MEM + path), (const char *)(MEM + mode)), 0);
}

SHIM(fopen_s) {
    uint32_t pfile = ARG(c, 0), path = ARG(c, 1), mode = ARG(c, 2);
    if (!pfile || !path || !mode) { RET(c, EINVAL, 0); return; }
    uint32_t f = open_guest_file((const char *)(MEM + path), (const char *)(MEM + mode));
    P32(pfile, f);
    RET(c, f ? 0u : (uint32_t)(errno ? errno : ENOENT), 0);
}

SHIM(_wfopen) {
    _wfsopen_(c);
}

SHIM(_wfopen_s) {
    uint32_t pfile = ARG(c, 0), wpath = ARG(c, 1), wmode = ARG(c, 2);
    if (!pfile || !wpath || !wmode) { RET(c, EINVAL, 0); return; }
    char win[1024], raw_mode[32];
    w2a(wpath, win, sizeof win);
    w2a(wmode, raw_mode, sizeof raw_mode);
    uint32_t f = open_guest_file(win, raw_mode);
    P32(pfile, f);
    RET(c, f ? 0u : (uint32_t)(errno ? errno : ENOENT), 0);
}

SHIM(vfprintf_s) {
    uint32_t stream = ARG(c, 0), fmt = ARG(c, 1), va = ARG(c, 2);
    if (!stream || !fmt) { RET(c, 0xffffffffu, 0); return; }
    FILE *f = NULL;
    pthread_mutex_lock(&guest_files_lock);
    for (int i = 0; i < MAX_GUEST_FILES; i++) {
        if (guest_files[i].guest == stream) { f = guest_files[i].host; break; }
    }
    pthread_mutex_unlock(&guest_files_lock);
    char buf[4096];
    int n = guest_vsnprintf(buf, sizeof buf, (const char *)(MEM + fmt), va, false);
    if (n > 0) {
        size_t len = (size_t)n < sizeof(buf) ? (size_t)n : sizeof(buf) - 1;
        fwrite(buf, 1, len, f ? f : stderr);
    }
    RET(c, (uint32_t)n, 0);
}

SHIM(fread) {
    uint32_t dst = ARG(c, 0), size = ARG(c, 1), count = ARG(c, 2), stream = ARG(c, 3);
    FILE *f = lookup_guest_file(c, stream);
    uint64_t total = (uint64_t)size * count;
    if (!f || !total) { RET(c, 0, 0); return; }
    check_guest_range(c, dst, (uint32_t)(total > UINT32_MAX ? UINT32_MAX : total));
    RET(c, (uint32_t)fread(MEM + dst, size, count, f), 0);
}

// Guest fopen() hands out an opaque token, not a real msvcr90 FILE*. Intercept the stream
// writers too, or the guest CRT would dereference that token and dump its payload to a
// random handle (we saw a 5 KiB binary cache blob land on stderr this way).
SHIM(fwrite) {
    uint32_t src = ARG(c, 0), size = ARG(c, 1), count = ARG(c, 2), stream = ARG(c, 3);
    FILE *f = NULL;
    pthread_mutex_lock(&guest_files_lock);
    for (int i = 0; i < MAX_GUEST_FILES; i++) {
        if (guest_files[i].guest == stream) { f = guest_files[i].host; break; }
    }
    pthread_mutex_unlock(&guest_files_lock);
    uint64_t total = (uint64_t)size * count;
    if (!f || !total) { RET(c, 0, 0); return; }
    check_guest_range(c, src, (uint32_t)(total > UINT32_MAX ? UINT32_MAX : total));
    RET(c, (uint32_t)fwrite(MEM + src, size, count, f), 0);
}

SHIM(_fseeki64) {
    uint32_t stream = ARG(c, 0);
    int64_t offset = (int64_t)(((uint64_t)ARG(c, 2) << 32) | ARG(c, 1));
    int origin = (int)ARG(c, 3);
    FILE *f = lookup_guest_file(c, stream);
    RET(c, (f && fseeko(f, (off_t)offset, origin) == 0) ? 0u : 0xffffffffu, 0);
}

SHIM(getc) {
    FILE *f = lookup_guest_file(c, ARG(c, 0));
    int ch = f ? fgetc(f) : EOF;
    RET(c, ch == EOF ? 0xffffffffu : (uint32_t)(unsigned char)ch, 0);
}

SHIM(fclose) {
    uint32_t stream = ARG(c, 0);
    FILE *f = NULL;
    pthread_mutex_lock(&guest_files_lock);
    for (int i = 0; i < MAX_GUEST_FILES; i++) {
        if (guest_files[i].guest == stream) {
            f = guest_files[i].host;
            guest_files[i].guest = 0;
            guest_files[i].host = NULL;
            break;
        }
    }
    pthread_mutex_unlock(&guest_files_lock);
    if (!f) { RET(c, 0xffffffffu, 0); return; }
    int r = fclose(f);
    gfree(stream);
    RET(c, r == 0 ? 0u : 0xffffffffu, 0);
}

SHIM(_beginthreadex) {
    ShimFn ct = host_find_shim("kernel32.dll", "CreateThread");
    if (!ct) rt_trap(c, TRAP_IMPORT, 0);
    ct(c);
    // CreateThread is stdcall (6 args); undo its callee cleanup for cdecl _beginthreadex.
    SETREG(c, R_ESP, REG(c, R_ESP) - 6 * 4);
}

static bool rtti_type_match(uint32_t td1, uint32_t td2) {
    if (td1 == td2) return true;
    if (!td1 || !td2) return false;
    return strcmp((const char *)(MEM + td1 + 8), (const char *)(MEM + td2 + 8)) == 0;
}

static int32_t rtti_pmd_offset(uint32_t complete_obj, uint32_t pmd) {
    int32_t mdisp = (int32_t)G32(pmd + 0);
    int32_t pdisp = (int32_t)G32(pmd + 4);
    if (pdisp >= 0) {
        int32_t vdisp = (int32_t)G32(pmd + 8);
        return mdisp + pdisp + (int32_t)G32(G32(complete_obj + (uint32_t)pdisp) + (uint32_t)vdisp);
    }
    return mdisp;
}

SHIM(__RTDynamicCast) {
    uint32_t inptr = ARG(c, 0);
    int32_t vfdelta = (int32_t)ARG(c, 1);
    uint32_t src_type = ARG(c, 2);
    uint32_t target_type = ARG(c, 3);
    uint32_t is_ref = ARG(c, 4);
    if (!inptr) { RET(c, 0, 0); return; }

    uint32_t vftable = G32(inptr);
    uint32_t col = G32(vftable - 4);
    uint32_t complete = inptr - G32(col + 4);
    uint32_t cd_off = G32(col + 8);
    if (cd_off) complete -= G32(inptr - cd_off);

    int32_t in_delta = (int32_t)(inptr - (uint32_t)vfdelta - complete);
    uint32_t chd = G32(col + 16);
    uint32_t attrs = G32(chd + 4);
    uint32_t nbase = G32(chd + 8);
    uint32_t bca = G32(chd + 12);
    uint32_t found_bcd = 0;

    if (!(attrs & 1u)) {
        // Single inheritance: locate TargetType, ensure no private/protected base, verify SrcType.
        for (uint32_t i = 0; i < nbase; i++) {
            uint32_t bcd = G32(bca + 4 * i);
            if (rtti_type_match(G32(bcd), target_type)) {
                bool ok = false;
                for (uint32_t j = i + 1; j < nbase; j++) {
                    uint32_t sub = G32(bca + 4 * j);
                    if (G32(sub + 20) & 4u) break;
                    if (rtti_type_match(G32(sub), src_type)) { ok = true; break; }
                }
                if (ok) found_bcd = bcd;
                break;
            }
        }
    } else {
        // Multiple / virtual inheritance: search for downcast (Target contains Src at in_delta) or upcast.
        for (uint32_t i = 0; i < nbase && !found_bcd; i++) {
            uint32_t bcd = G32(bca + 4 * i);
            uint32_t sub_count = G32(bcd + 4);
            if (rtti_type_match(G32(bcd), target_type)) {
                for (uint32_t j = 1; j <= sub_count && i + j < nbase; j++) {
                    uint32_t sub = G32(bca + 4 * (i + j));
                    if (G32(sub + 20) & 5u) continue;
                    if (rtti_type_match(G32(sub), src_type) && rtti_pmd_offset(complete, sub + 8) == in_delta) {
                        found_bcd = bcd;
                        break;
                    }
                }
            } else if (rtti_type_match(G32(bcd), src_type) && rtti_pmd_offset(complete, bcd + 8) == in_delta) {
                for (uint32_t j = 1; j <= sub_count && i + j < nbase; j++) {
                    uint32_t sub = G32(bca + 4 * (i + j));
                    if (G32(sub + 20) & 5u) continue;
                    if (rtti_type_match(G32(sub), target_type)) {
                        found_bcd = sub;
                        break;
                    }
                }
            }
        }
    }

    if (found_bcd) {
        uint32_t result = complete + (uint32_t)rtti_pmd_offset(complete, found_bcd + 8);
        RET(c, result, 0);
        return;
    }
    if (is_ref) {
        fprintf(stderr, "[msvcr90] __RTDynamicCast bad_cast inptr=%#x\n", inptr);
        rt_trap(c, TRAP_IMPORT, inptr);
    }
    RET(c, 0, 0);
}

static uint32_t wide_command_line;

static uint32_t get_wide_command_line(void) {
    if (!wide_command_line) {
        const char *name = host_exe_name();
        size_t length = strlen(name);
        wide_command_line = gmalloc(2 * (length + 1));
        for (size_t index = 0; index <= length; index++) {
            uint16_t unit = (unsigned char)name[index];
            memcpy(MEM + wide_command_line + 2 * index, &unit, sizeof(unit));
        }
    }
    return wide_command_line;
}

SHIM(getenv) {
    // The guest starts with an empty environment, including through direct CRT lookups.
    RET(c, 0, 0);
}

SHIM(__wgetmainargs) {
    // The startup probe supplies the executable name and an empty guest environment.
    static uint32_t argv;
    static uint32_t environment;
    if (!argv) {
        argv = gmalloc(2 * sizeof(uint32_t));
        environment = gmalloc(sizeof(uint32_t));
        P32(argv, get_wide_command_line());
        P32(argv + sizeof(uint32_t), 0);
        P32(environment, 0);
    }
    P32(ARG(c, 0), 1);
    P32(ARG(c, 1), argv);
    P32(ARG(c, 2), environment);
    RET(c, 0, 0);
}

uint32_t smr_find_msvcr90_data(const char *name) {
    static uint32_t adjust_fdiv;
    static uint32_t wcmdln;
    if (!strcmp(name, "_wcmdln")) {
        uint32_t slot = guest_int(&wcmdln);
        P32(slot, get_wide_command_line());
        return slot;
    }
    if (!strcmp(name, "_adjust_fdiv"))
        return guest_int(&adjust_fdiv);
    return 0;
}

typedef struct {
    const char *name;
    ShimFn fn;
} MsvcrShimEntry;

static const MsvcrShimEntry msvcr90_fast_shims[] = {
    {"memset", memset_},
    {"memcpy", memmove_},
    {"memmove", memmove_},
    {"memcmp", memcmp_},
    {"strcmp", strcmp_},
    {"strncmp", strncmp_},
    {"_stricmp", _stricmp_},
    {"_strnicmp", _strnicmp_},
    {"strncpy", strncpy_},
    {"strncpy_s", strncpy_s_},
    {"strcspn", strcspn_},
    {"strtoul", strtoul_},
    {"wcsrchr", wcsrchr_},
    {"isspace", isspace_},
    {"isalnum", isalnum_},
    {"isalpha", isalpha_},
    {"isdigit", isdigit_},
    {"isxdigit", isxdigit_},
    {"tolower", tolower_},
    {"toupper", toupper_},
    {"strchr", strchr_},
    {"strspn", strspn_},
    {"strstr", strstr_},
    {"memchr", memchr_},
    {"atoi", atoi_},
    {"atof", atof_},
    {"rand", rand_},
    {"srand", srand_},
    {"floor", floor_},
    {"ceil", ceil_},
    {"_CIsqrt", _CIsqrt_},
    {"_CIsin", _CIsin_},
    {"_CIcos", _CIcos_},
    {"_CItan", _CItan_},
    {"_CIasin", _CIasin_},
    {"_CIacos", _CIacos_},
    {"_CIlog", _CIlog_},
    {"_CIatan2", _CIatan2_},
    {"_CIfmod", _CIfmod_},
    {"_CIpow", _CIpow_},
    {"_isnan", _isnan_},
    {"_finite", _finite_},
    {"_fpclass", _fpclass_},
    {"_vscprintf", _vscprintf_},
    {"_vsnprintf_s", _vsnprintf_s_},
    {"sprintf", sprintf_},
    {"sprintf_s", sprintf_s_},
    {"_vscwprintf", _vscwprintf_},
    {"_vsnwprintf_s", _vsnwprintf_s_},
    {"sscanf_s", sscanf_s_},
    {"_wfsopen", _wfsopen_},
    {"fopen", fopen_},
    {"_fsopen", fopen_},
    {"fopen_s", fopen_s_},
    {"_wfopen", _wfopen_},
    {"_wfopen_s", _wfopen_s_},
    {"vfprintf_s", vfprintf_s_},
    {"fread", fread_},
    {"fwrite", fwrite_},
    {"_fseeki64", _fseeki64_},
    {"getc", getc_},
    {"fgetc", getc_},
    {"fclose", fclose_},
    {"_waccess_s", _waccess_s_},
    {"_wstat64", _wstat64_},
    {"_time64", _time64_},
    {"_beginthreadex", _beginthreadex_},
    {"__RTDynamicCast", __RTDynamicCast_},
    {"_encode_pointer", _encode_pointer_},
    {"_decode_pointer", _encode_pointer_},
    {"_onexit", _onexit_},
    {"_cexit", _cexit_},
    {"_controlfp_s", _controlfp_s_},
    {"malloc", malloc_},
    {"calloc", calloc_},
    {"realloc", realloc_},
    {"_msize", _msize_},
    {"free", free_},
    {"_initterm", _initterm_},
    {"_initterm_e", _initterm_e_},
    {"getenv", getenv_},
    {"__wgetmainargs", __wgetmainargs_},
    {"__set_app_type", __set_app_type_},
    {"__p__fmode", __p__fmode_},
    {"__p__commode", __p__commode_},
    {"_configthreadlocale", _configthreadlocale_},
};

ShimFn smr_find_msvcr90_fast_shim(const char *name) {
    if (!name) return NULL;
    for (size_t i = 0; i < sizeof(msvcr90_fast_shims) / sizeof(msvcr90_fast_shims[0]); i++) {
        if (!strcmp(name, msvcr90_fast_shims[i].name))
            return msvcr90_fast_shims[i].fn;
    }
    return NULL;
}

ShimFn smr_find_msvcr90_shim(const char *name) {
    return smr_find_msvcr90_fast_shim(name);
}
