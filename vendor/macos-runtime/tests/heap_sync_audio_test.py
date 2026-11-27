"""Standalone regressions for heap overflow guards, handle-table locking and CPU feature reporting.

The C source is generated here because the test only needs three host modules: gheap.c,
shims_sync.c and shims_kernel32.c. The rest of the host runtime is stubbed below.
"""
from native_test_toolchain import COMPILER, PLATFORM_FLAGS
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / 'upstream/recomp/host'
SOURCE = r'''
// Standalone regression test: heap overflow guards, handle-table locking and CPU feature reporting.
#include <pthread.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include "shims.h"

uint8_t *MEM;
HostImport host_imports[MAX_IMPORTS];
int host_import_count;
uint32_t host_image_base;
uint8_t *host_tls_template;
uint32_t host_tls_template_size, host_tls_block_size;

// The rest of the host runtime is not linked here: only the three modules under test are.
const ShimTable file_shims = { NULL, 0 };
const ShimTable text_shims = { NULL, 0 };
const ShimTable win_shims = { NULL, 0 };
const ShimTable steam_shims = { NULL, 0 };
const ShimTable xlive_shims = { NULL, 0 };
const ShimTable wsock_shims = { NULL, 0 };
const ShimTable dinput_shims = { NULL, 0 };
const ShimTable dsound_shims = { NULL, 0 };
const ShimTable d3d9_shims = { NULL, 0 };
const ShimTable d3dx_shims = { NULL, 0 };
const ShimTable xinput_shims = { NULL, 0 };
const ShimTable media_shims = { NULL, 0 };
const ShimTable mmio_shims = { NULL, 0 };
void rt_calltrace_dump(void) {}
void rt_call(CPU *c, uint32_t a) { (void)c; (void)a; }
int host_run_guest(CPU *c, uint32_t entry) { (void)c; (void)entry; return 0; }
uint32_t smr_module_by_name(const char *name) { (void)name; return 0; }
uint32_t smr_module_export_by_handle(uint32_t handle, const char *name) { (void)handle; (void)name; return 0; }
bool smr_mapped_module_handle(uint32_t handle) { (void)handle; return false; }
ShimFn smr_find_fast_shim(const char *dll, const char *name) { (void)dll; (void)name; return NULL; }
ShimFn smr_find_msvcr90_shim(const char *name) { (void)name; return NULL; }

extern const ShimTable sync_shims;
static int failed;
static void check(const char *name, int ok) { printf("%s: %s\n", ok ? "PASS" : "FAIL", name); fflush(stdout); failed += !ok; }
static ShimFn find_sync(const char *name) {
    for (int i = 0; i < sync_shims.count; i++) if (!strcmp(sync_shims.list[i].name, name)) return sync_shims.list[i].fn;
    fprintf(stderr, "missing shim %s\n", name); abort();
}
static uint32_t invoke(ShimFn fn, const uint32_t *args, unsigned count) {
    CPU c = {0};
    uint32_t sp = 0x7000;
    SETREG(&c, R_ESP, sp); P32(sp, 0xabc);
    for (unsigned i = 0; i < count; i++) P32(sp + 4 + 4 * i, args[i]);
    fn(&c);
    return REG(&c, R_EAX);
}
#define CALL(name, ...) invoke(find_sync(name), (uint32_t[]){__VA_ARGS__}, sizeof((uint32_t[]){__VA_ARGS__}) / 4)

#define HANDLE_WORKERS 8
#define HANDLE_ROUNDS 2000
static void *handle_worker(void *p) {
    int id = (int)(intptr_t)p;
    void *mine = (void *)(uintptr_t)(id + 1);
    for (int i = 0; i < HANDLE_ROUNDS; i++) {
        uint32_t h = handle_new(H_EVENT, mine);
        if (!h || handle_get(h, H_EVENT) != mine || handle_type(h) != H_EVENT) {
            fprintf(stderr, "worker %d lost handle %#x\n", id, h);
            abort();
        }
        if (handle_get(h, H_SEMA) || handle_type(0xFFFFFFF0u)) abort();
    }
    return NULL;
}

int main(void) {
    MEM = mmap(NULL, (size_t)1 << 32, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0);
    if (MEM == MAP_FAILED) { perror("guest memory"); return 2; }

    // gmalloc/grealloc must refuse requests whose size rounding would wrap 32 bits.
    uint32_t live = gmalloc(64);
    memset(MEM + live, 0x5a, 64);
    check("gmalloc rejects overflowing huge size", gmalloc(0xFFFFFFF0u) == 0);
    check("grealloc rejects overflowing size", grealloc(live, 0xFFFFFFF0u) == 0);
    check("rejected realloc keeps the live block", gsize(live) == 64 && MEM[live] == 0x5a && MEM[live + 63] == 0x5a);
    gfree(live);

    // In-place growth must publish zeroes for the new tail, not stale bytes or guard fill.
    uint32_t q = gmalloc(40);
    memset(MEM + q, 0x5a, 40);
    uint32_t grown = grealloc(q, 44);
    int kept = grown == q && gsize(grown) == 44;
    for (unsigned i = 0; i < 40; i++) kept = kept && MEM[grown + i] == 0x5a;
    for (unsigned i = 40; i < 44; i++) kept = kept && MEM[grown + i] == 0;
    check("in-place growth preserves the old bytes and zeroes the tail", kept);
    gfree(grown);

    // IsProcessorFeaturePresent: PF_3DNOW (7) must be false; SSE2 (10) true.
    ShimFn feature = host_find_shim("kernel32.dll", "IsProcessorFeaturePresent");
    check("kernel32 feature shim resolves", feature != NULL);
    if (feature) {
        check("PF_3DNOW reports unsupported", invoke(feature, (uint32_t[]){7}, 1) == 0);
        check("PF_SSE2 reports supported", invoke(feature, (uint32_t[]){10}, 1) == 1);
    }

    // ReleaseSemaphore must honour lMaximumCount and reject non-positive releases.
    uint32_t sem = CALL("CreateSemaphoreA", 0, 1, 2, 0);
    host_last_error = 0;
    check("ReleaseSemaphore rejects zero release", CALL("ReleaseSemaphore", sem, 0, 0) == 0 && host_last_error == 87);
    host_last_error = 0;
    check("ReleaseSemaphore rejects negative release", CALL("ReleaseSemaphore", sem, (uint32_t)-1, 0) == 0 && host_last_error == 87);
    host_last_error = 0;
    check("ReleaseSemaphore rejects count above maximum", CALL("ReleaseSemaphore", sem, 2, 0) == 0 && host_last_error == 298);
    check("rejected release leaves the count untouched", CALL("WaitForSingleObject", sem, 0) == 0 && CALL("WaitForSingleObject", sem, 0) == 0x102);
    check("release up to the maximum succeeds", CALL("ReleaseSemaphore", sem, 1, 0x2004) == 1 && G32(0x2004) == 0);
    check("release one more succeeds at capacity", CALL("ReleaseSemaphore", sem, 1, 0x2004) == 1 && G32(0x2004) == 1);
    host_last_error = 0;
    check("release past capacity fails again", CALL("ReleaseSemaphore", sem, 1, 0) == 0 && host_last_error == 298);

    // Concurrent handle_new/handle_get/handle_type on the shared table.
    pthread_t workers[HANDLE_WORKERS];
    for (int i = 0; i < HANDLE_WORKERS; i++) pthread_create(&workers[i], NULL, handle_worker, (void *)(intptr_t)i);
    for (int i = 0; i < HANDLE_WORKERS; i++) pthread_join(workers[i], NULL);
    check("concurrent handle table use stays consistent", 1);

    return failed ? 1 : 0;
}
'''

with tempfile.TemporaryDirectory(prefix='fnv-heap-sync-audio-') as temp:
    work = Path(temp)
    source = work / 'heap_sync_audio_test.c'
    source.write_text(SOURCE)
    common = [*COMPILER, *PLATFORM_FLAGS, '-O1', '-Wall', '-Wextra', '-Werror',
              '-I', str(ROOT / 'macos'), '-I', str(HOST), '-I', str(ROOT / 'upstream/recomp'), '-I', str(ROOT / 'tests'),
              str(source), str(HOST / 'gheap.c'), str(HOST / 'shims_sync.c'), str(HOST / 'shims_kernel32.c'),
              '-pthread']
    binary = work / 'heap-sync-audio'
    subprocess.run([*common, '-o', str(binary)], check=True)
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=60)
    print(result.stdout, end='')
    assert result.returncode == 0, result.stdout + result.stderr

    # The handle stress must also be data-race free, not merely non-crashing.
    tsan = work / 'heap-sync-audio-tsan'
    subprocess.run([*common, '-fsanitize=thread', '-o', str(tsan)], check=True)
    raced = subprocess.run([str(tsan)], capture_output=True, text=True, timeout=120)
    assert raced.returncode == 0, raced.stdout + raced.stderr
    assert 'WARNING: ThreadSanitizer' not in raced.stderr, raced.stderr
    print('PASS: concurrent handle table access is data-race free')
