"""Unit tests for the host-backed MSVCR90 stdio stream shims in src/host/msvcr90.c."""
from pathlib import Path
import subprocess
import tempfile
from native_test_toolchain import COMPILER, PLATFORM_FLAGS, LIBRARIES

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]

HARNESS = r"""
#include <assert.h>
#include <errno.h>
#include <setjmp.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>

#include "rt.h"
#include "host.h"
#include "shims.h"

uint8_t *MEM = NULL;
int64_t rt_budget = 0;

ShimFn smr_find_msvcr90_fast_shim(const char *name);

static uint32_t g_heap_ptr = 0x01000000u;
static sigjmp_buf g_trap_jmp;

uint32_t gmalloc(uint32_t n) {
    uint32_t p = (g_heap_ptr + 15u) & ~15u;
    g_heap_ptr = p + n + 16u;
    memset(MEM + p, 0, n);
    return p;
}
void gfree(uint32_t p) { (void)p; }
uint32_t grealloc(uint32_t p, uint32_t n) { (void)p; return gmalloc(n); }
uint32_t gsize(uint32_t p) { (void)p; return 0; }
void host_path(const char *win, char *out, size_t n) {
    size_t len = strlen(win);
    if (len >= n) len = n - 1;
    memcpy(out, win, len);
    out[len] = 0;
}
void w2a(uint32_t w, char *out, size_t n) {
    size_t i = 0;
    if (!n) return;
    while (i + 1 < n) {
        uint16_t unit;
        memcpy(&unit, MEM + w + 2 * i, 2);
        out[i] = (char)unit;
        if (!unit) return;
        i++;
    }
    out[i] = 0;
}
uint32_t wlen(uint32_t w) {
    uint32_t len = 0;
    for (;;) {
        uint16_t unit;
        memcpy(&unit, MEM + w + 2 * len, 2);
        if (!unit) return len;
        len++;
    }
}
const char *host_exe_name(void) { return "msvcr90_stdio_test.exe"; }
ShimFn host_find_shim(const char *dll, const char *name) { (void)dll; (void)name; return NULL; }
void rt_call(CPU *c, uint32_t a) { (void)c; (void)a; abort(); }
void rt_trap(CPU *c, int code, uint32_t addr) {
    (void)c; (void)code; (void)addr;
    siglongjmp(g_trap_jmp, 1);
}

static void w32(uint32_t addr, uint32_t val) { memcpy(MEM + addr, &val, 4); }
static uint32_t r32(uint32_t addr) { uint32_t val; memcpy(&val, MEM + addr, 4); return val; }

static uint32_t bump_alloc(uint32_t size) {
    uint32_t p = (g_heap_ptr + 15u) & ~15u;
    g_heap_ptr = p + ((size + 15u) & ~15u);
    memset(MEM + p, 0, size);
    return p;
}

static void put_str(uint32_t addr, const char *s) {
    memcpy(MEM + addr, s, strlen(s) + 1);
}

static void put_wstr(uint32_t addr, const char *s) {
    for (size_t i = 0;; i++) {
        uint16_t unit = (unsigned char)s[i];
        memcpy(MEM + addr + 2 * i, &unit, 2);
        if (!unit) break;
    }
}

static void get_wstr(uint32_t addr, char *out, size_t cap) {
    size_t i = 0;
    if (!cap) return;
    while (i + 1 < cap) {
        uint16_t unit;
        memcpy(&unit, MEM + addr + 2 * i, 2);
        out[i] = (char)unit;
        if (!unit) return;
        i++;
    }
    out[i] = 0;
}

static void setup_cpu(CPU *c, uint32_t sp, int nargs, const uint32_t *args) {
    memset(c, 0, sizeof *c);
    SETREG(c, R_ESP, sp);
    w32(sp, 0x0040deadu);
    for (int i = 0; i < nargs; i++) w32(sp + 4 + 4 * (uint32_t)i, args[i]);
}

static uint32_t call_shim(ShimFn fn, int nargs, const uint32_t *args) {
    CPU c;
    uint32_t sp = 0x00800000u;
    setup_cpu(&c, sp, nargs, args);
    fn(&c);
    assert(REG(&c, R_ESP) == sp + 4);
    return REG(&c, R_EAX);
}

static uint64_t call_shim64(ShimFn fn, int nargs, const uint32_t *args) {
    CPU c;
    uint32_t sp = 0x00800000u;
    setup_cpu(&c, sp, nargs, args);
    fn(&c);
    assert(REG(&c, R_ESP) == sp + 4);
    return ((uint64_t)REG(&c, R_EDX) << 32) | REG(&c, R_EAX);
}

static uint32_t open_wfile(ShimFn wfopen_s, const char *path, const char *mode) {
    uint32_t wpath = bump_alloc((uint32_t)(2 * (strlen(path) + 1)));
    uint32_t wmode = bump_alloc((uint32_t)(2 * (strlen(mode) + 1)));
    uint32_t pfile = bump_alloc(4);
    put_wstr(wpath, path);
    put_wstr(wmode, mode);
    uint32_t args[3] = { pfile, wpath, wmode };
    assert(call_shim(wfopen_s, 3, args) == 0);
    uint32_t stream = r32(pfile);
    assert(stream != 0);
    return stream;
}

int main(int argc, char **argv) {
    assert(argc == 2);
    MEM = mmap(NULL, 64u << 20, PROT_READ | PROT_WRITE, MAP_ANON | MAP_PRIVATE, -1, 0);
    assert(MEM != MAP_FAILED);

    if (sigsetjmp(g_trap_jmp, 1) != 0) {
        fprintf(stderr, "msvcr90_stdio_test: unexpected guest trap\n");
        return 1;
    }

    ShimFn wfopen_s = smr_find_msvcr90_fast_shim("_wfopen_s");
    ShimFn fwrite_fn = smr_find_msvcr90_fast_shim("fwrite");
    ShimFn fread_fn = smr_find_msvcr90_fast_shim("fread");
    ShimFn fflush_fn = smr_find_msvcr90_fast_shim("fflush");
    ShimFn ftell_fn = smr_find_msvcr90_fast_shim("ftell");
    ShimFn ftelli64_fn = smr_find_msvcr90_fast_shim("_ftelli64");
    ShimFn fseek_fn = smr_find_msvcr90_fast_shim("fseek");
    ShimFn fseeki64_fn = smr_find_msvcr90_fast_shim("_fseeki64");
    ShimFn rewind_fn = smr_find_msvcr90_fast_shim("rewind");
    ShimFn feof_fn = smr_find_msvcr90_fast_shim("feof");
    ShimFn ferror_fn = smr_find_msvcr90_fast_shim("ferror");
    ShimFn clearerr_fn = smr_find_msvcr90_fast_shim("clearerr");
    ShimFn fputc_fn = smr_find_msvcr90_fast_shim("fputc");
    ShimFn putc_fn = smr_find_msvcr90_fast_shim("putc");
    ShimFn fputs_fn = smr_find_msvcr90_fast_shim("fputs");
    ShimFn fgets_fn = smr_find_msvcr90_fast_shim("fgets");
    ShimFn ungetc_fn = smr_find_msvcr90_fast_shim("ungetc");
    ShimFn getc_fn = smr_find_msvcr90_fast_shim("getc");
    ShimFn fprintf_fn = smr_find_msvcr90_fast_shim("fprintf");
    ShimFn fclose_fn = smr_find_msvcr90_fast_shim("fclose");
    ShimFn strtoul_fn = smr_find_msvcr90_fast_shim("strtoul");
    ShimFn sprintf_fn = smr_find_msvcr90_fast_shim("sprintf");
    ShimFn vsnwprintf_fn = smr_find_msvcr90_fast_shim("_vsnwprintf_s");
    assert(wfopen_s && fwrite_fn && fread_fn && fflush_fn && ftell_fn && ftelli64_fn);
    assert(fseek_fn && fseeki64_fn && rewind_fn && feof_fn && ferror_fn && clearerr_fn);
    assert(fputc_fn && putc_fn && fputs_fn && fgets_fn && ungetc_fn && getc_fn);
    assert(fprintf_fn && fclose_fn && strtoul_fn && sprintf_fn && vsnwprintf_fn);

    const char DATA[] = "line1\nline2\n";
    assert(sizeof DATA - 1 == 12);

    // 1. Guest stream round trip through the host-backed FILE* table.
    uint32_t stream = open_wfile(wfopen_s, argv[1], "w+b");
    assert(r32(stream + 0x10) == 0xFFFFFFFFu); // open streams set _file = -1, not stdin

    uint32_t data = bump_alloc(16);
    put_str(data, DATA);
    uint32_t one[1] = { stream };
    assert(call_shim(fwrite_fn, 4, (uint32_t[]){ data, 1, 12, stream }) == 12);
    assert(call_shim(fflush_fn, 1, one) == 0);
    assert(call_shim(ftell_fn, 1, one) == 12);
    assert(call_shim64(ftelli64_fn, 1, one) == 12);

    assert(call_shim(fseek_fn, 3, (uint32_t[]){ stream, 0, SEEK_END }) == 0);
    assert(call_shim(ftell_fn, 1, one) == 12);
    assert(call_shim64(fseeki64_fn, 4, (uint32_t[]){ stream, 7, 0, SEEK_SET }) == 0);
    assert(call_shim(ftell_fn, 1, one) == 7);

    // 2. fgets / ungetc / getc / feof / ferror / clearerr at EOF.
    uint32_t line = bump_alloc(32);
    assert(call_shim(fgets_fn, 3, (uint32_t[]){ line, 16, stream }) == line);
    assert(strcmp((char *)(MEM + line), "ine2\n") == 0);
    assert(call_shim(feof_fn, 1, one) == 0);
    assert(call_shim(ferror_fn, 1, one) == 0);
    assert(call_shim(ungetc_fn, 2, (uint32_t[]){ 'Q', stream }) == (uint32_t)'Q');
    assert(call_shim(getc_fn, 1, one) == (uint32_t)'Q');
    assert(call_shim(getc_fn, 1, one) == 0xFFFFFFFFu);
    assert(call_shim(feof_fn, 1, one) != 0);
    assert(call_shim(ferror_fn, 1, one) == 0);
    assert(call_shim(clearerr_fn, 1, one) == 0);
    assert(call_shim(feof_fn, 1, one) == 0);

    // 3. rewind + fread returns the exact bytes written.
    assert(call_shim(rewind_fn, 1, one) == 0);
    assert(call_shim(ftell_fn, 1, one) == 0);
    uint32_t readback = bump_alloc(32);
    assert(call_shim(fread_fn, 4, (uint32_t[]){ readback, 1, 12, stream }) == 12);
    assert(memcmp(MEM + readback, DATA, 12) == 0);

    // 4. fputc / putc / fputs / fprintf write through the same stream.
    assert(call_shim(fseek_fn, 3, (uint32_t[]){ stream, 0, SEEK_SET }) == 0);
    assert(call_shim(fputc_fn, 2, (uint32_t[]){ 'A', stream }) == (uint32_t)'A');
    assert(call_shim(putc_fn, 2, (uint32_t[]){ 'B', stream }) == (uint32_t)'B');
    assert(call_shim(fflush_fn, 1, one) == 0);
    assert(call_shim(ftell_fn, 1, one) == 2);
    assert(call_shim(rewind_fn, 1, one) == 0);
    assert(call_shim(fread_fn, 4, (uint32_t[]){ readback, 1, 2, stream }) == 2);
    assert(memcmp(MEM + readback, "AB", 2) == 0);

    assert(call_shim(fseek_fn, 3, (uint32_t[]){ stream, 0, SEEK_SET }) == 0);
    uint32_t hello = bump_alloc(8);
    put_str(hello, "hello");
    assert((int32_t)call_shim(fputs_fn, 2, (uint32_t[]){ hello, stream }) >= 0);
    assert(call_shim(fflush_fn, 1, one) == 0);
    assert(call_shim(ftell_fn, 1, one) == 5);
    assert(call_shim(rewind_fn, 1, one) == 0);
    assert(call_shim(fread_fn, 4, (uint32_t[]){ readback, 1, 5, stream }) == 5);
    assert(memcmp(MEM + readback, "hello", 5) == 0);

    assert(call_shim(fseek_fn, 3, (uint32_t[]){ stream, 0, SEEK_SET }) == 0);
    uint32_t fmt = bump_alloc(8);
    uint32_t fmt_arg = bump_alloc(4);
    put_str(fmt, "%s=%d");
    put_str(fmt_arg, "n");
    assert(call_shim(fprintf_fn, 4, (uint32_t[]){ stream, fmt, fmt_arg, 7 }) == 3);
    assert(call_shim(fflush_fn, 1, one) == 0);
    assert(call_shim(rewind_fn, 1, one) == 0);
    assert(call_shim(fread_fn, 4, (uint32_t[]){ readback, 1, 3, stream }) == 3);
    assert(memcmp(MEM + readback, "n=7", 3) == 0);

    assert(call_shim(fclose_fn, 1, one) == 0);

    // 5. fflush(NULL) flushes every open guest stream.
    uint32_t pending = open_wfile(wfopen_s, argv[1], "w+b");
    uint32_t flush_data = bump_alloc(16);
    put_str(flush_data, "flushall");
    assert(call_shim(fwrite_fn, 4, (uint32_t[]){ flush_data, 1, 8, pending }) == 8);
    assert(call_shim(fflush_fn, 1, (uint32_t[]){ 0 }) == 0);
    uint32_t flushed = open_wfile(wfopen_s, argv[1], "rb");
    uint32_t flush_read = bump_alloc(16);
    assert(call_shim(fread_fn, 4, (uint32_t[]){ flush_read, 1, 8, flushed }) == 8);
    assert(memcmp(MEM + flush_read, "flushall", 8) == 0);
    assert(call_shim(fclose_fn, 1, (uint32_t[]){ flushed }) == 0);
    assert(call_shim(fclose_fn, 1, (uint32_t[]){ pending }) == 0);

    // 6. Real lifted _iob[1]/_iob[2] pass-through: _file = 1/2, no trap.
    for (uint32_t file = 1; file <= 2; file++) {
        uint32_t iob = bump_alloc(32);
        w32(iob + 0x10, file);
        uint32_t iob_one[1] = { iob };
        assert(call_shim(fflush_fn, 1, iob_one) == 0);
        assert(call_shim(feof_fn, 1, iob_one) == 0);
        assert(call_shim(ferror_fn, 1, iob_one) == 0);
        assert(call_shim(clearerr_fn, 1, iob_one) == 0);
        (void)call_shim(ftell_fn, 1, iob_one);
        (void)call_shim64(ftelli64_fn, 1, iob_one);
        (void)call_shim(fseek_fn, 3, (uint32_t[]){ iob, 0, SEEK_SET });
        assert(call_shim(rewind_fn, 1, iob_one) == 0);
    }
    uint32_t empty = bump_alloc(1);
    MEM[empty] = 0;
    uint32_t iob_out = bump_alloc(32);
    w32(iob_out + 0x10, 1);
    uint32_t iob_err = bump_alloc(32);
    w32(iob_err + 0x10, 2);
    assert(call_shim(fprintf_fn, 2, (uint32_t[]){ iob_out, empty }) == 0);
    assert(call_shim(fprintf_fn, 2, (uint32_t[]){ iob_err, empty }) == 0);

    // 7. 64-bit host strtoul saturates at 32-bit ULONG_MAX instead of wrapping.
    uint32_t number = bump_alloc(32);
    uint32_t endptr = bump_alloc(4);
    put_str(number, "4294967296");
    assert(call_shim(strtoul_fn, 3, (uint32_t[]){ number, endptr, 10 }) == 0xFFFFFFFFu);
    assert(r32(endptr) == number + 10);
    put_str(number, "123");
    assert(call_shim(strtoul_fn, 3, (uint32_t[]){ number, endptr, 10 }) == 123);
    put_str(number, "999999999999999999999");
    assert(call_shim(strtoul_fn, 3, (uint32_t[]){ number, endptr, 10 }) == 0xFFFFFFFFu);

    // 8. Wide format %S means narrow; %s stays wide. Narrow %S means wide.
    uint32_t wfmt = bump_alloc(32);
    put_wstr(wfmt, "[%S] %s");
    uint32_t narrow = bump_alloc(16);
    uint32_t wide = bump_alloc(16);
    put_str(narrow, "narrow");
    put_wstr(wide, "wide");
    uint32_t va = bump_alloc(8);
    w32(va, narrow);
    w32(va + 4, wide);
    uint32_t wbuf = bump_alloc(128);
    assert(call_shim(vsnwprintf_fn, 5,
                     (uint32_t[]){ wbuf, 64, 0xFFFFFFFFu, wfmt, va }) == 13);
    char wide_result[64];
    get_wstr(wbuf, wide_result, sizeof wide_result);
    assert(strcmp(wide_result, "[narrow] wide") == 0);

    uint32_t narrow_fmt = bump_alloc(8);
    uint32_t narrow_out = bump_alloc(32);
    put_str(narrow_fmt, "%S");
    assert(call_shim(sprintf_fn, 3, (uint32_t[]){ narrow_out, narrow_fmt, wide }) == 4);
    assert(strcmp((char *)(MEM + narrow_out), "wide") == 0);
    put_str(narrow_fmt, "%s");
    assert(call_shim(sprintf_fn, 3, (uint32_t[]){ narrow_out, narrow_fmt, narrow }) == 6);
    assert(strcmp((char *)(MEM + narrow_out), "narrow") == 0);

    puts("msvcr90_stdio_test: PASS");
    return 0;
}
"""

with tempfile.TemporaryDirectory(prefix='smr-msvcr90-stdio-') as temp:
    src = Path(temp) / 'test.c'
    binary = Path(temp) / 'msvcr90-stdio-test'
    guest_file = Path(temp) / 'guest.bin'
    src.write_text(HARNESS)
    ldflags = ['-Wl,-dead_strip'] if COMPILER[0] == 'xcrun' else []
    subprocess.run([
        *COMPILER, *PLATFORM_FLAGS, '-O2',
        '-I', str(REPO / 'src/host'),
        '-I', str(ROOT / 'upstream/recomp/host'),
        '-I', str(ROOT / 'upstream/recomp'),
        str(src),
        str(REPO / 'src/host/msvcr90.c'),
        *LIBRARIES, *ldflags, '-o', str(binary),
    ], check=True)
    subprocess.run([str(binary), str(guest_file)], check=True, timeout=20)
