#include <errno.h>
#include <stdbool.h>
#include <pthread.h>
#include <stdlib.h>
#include <strings.h>
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

ShimFn smr_find_msvcr90_fast_shim(const char *name) {
    if (!strcmp(name, "memset"))
        return memset_;
    if (!strcmp(name, "memcpy") || !strcmp(name, "memmove"))
        return memmove_;
    if (!strcmp(name, "memcmp"))
        return memcmp_;
    if (!strcmp(name, "strcmp"))
        return strcmp_;
    if (!strcmp(name, "strncmp"))
        return strncmp_;
    if (!strcmp(name, "_stricmp"))
        return _stricmp_;
    if (!strcmp(name, "_strnicmp"))
        return _strnicmp_;
    return NULL;
}

ShimFn smr_find_msvcr90_shim(const char *name) {
    ShimFn fast = smr_find_msvcr90_fast_shim(name);
    if (fast)
        return fast;
    if (!strcmp(name, "_initterm"))
        return _initterm_;
    if (!strcmp(name, "_initterm_e"))
        return _initterm_e_;
    if (!strcmp(name, "_encode_pointer") || !strcmp(name, "_decode_pointer"))
        return _encode_pointer_;
    if (!strcmp(name, "_controlfp_s"))
        return _controlfp_s_;
    if (!strcmp(name, "malloc"))
        return malloc_;
    if (!strcmp(name, "calloc"))
        return calloc_;
    if (!strcmp(name, "realloc"))
        return realloc_;
    if (!strcmp(name, "_msize"))
        return _msize_;
    if (!strcmp(name, "free"))
        return free_;
    if (!strcmp(name, "getenv"))
        return getenv_;
    if (!strcmp(name, "__wgetmainargs"))
        return __wgetmainargs_;
    if (!strcmp(name, "_onexit"))
        return _onexit_;
    if (!strcmp(name, "_cexit"))
        return _cexit_;
    if (!strcmp(name, "__set_app_type"))
        return __set_app_type_;
    if (!strcmp(name, "__p__fmode"))
        return __p__fmode_;
    if (!strcmp(name, "__p__commode"))
        return __p__commode_;
    if (!strcmp(name, "_configthreadlocale"))
        return _configthreadlocale_;
    return NULL;
}
