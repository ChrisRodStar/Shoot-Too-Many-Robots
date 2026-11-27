// Fallback time accounting shared by the Unicorn fallback and the [perf] reporter.
// Lives in the local host dir so both fnv-startup and fnv-discovery link it.
//
// Counters are thread-local on purpose: the [perf] line is emitted by the presenting
// thread, and only that thread's interpreter time counts against the frame budget.
// A global total is kept for the optional SMR_FALLBACK_PERF exit summary.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

static _Thread_local uint64_t tl_emu_ns, tl_calls;
static uint64_t total_emu_ns, total_calls, start_ns;

static uint64_t now_ns(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint64_t)t.tv_sec * 1000000000ull + (uint64_t)t.tv_nsec;
}

void smr_fallback_perf_add(uint64_t ns) {
    tl_emu_ns += ns;
    __atomic_fetch_add(&total_emu_ns, ns, __ATOMIC_RELAXED);
}
void smr_fallback_perf_call(void) {
    tl_calls++;
    __atomic_fetch_add(&total_calls, 1, __ATOMIC_RELAXED);
}

// Returns the calling thread's time since the previous call and resets its counters.
void smr_fallback_perf(uint64_t *emu_ns, uint64_t *native_ns, uint64_t *calls) {
    *emu_ns = tl_emu_ns;
    *calls = tl_calls;
    tl_emu_ns = 0;
    tl_calls = 0;
    *native_ns = 0;
}

__attribute__((constructor)) static void fallback_perf_init(void) { start_ns = now_ns(); }

__attribute__((destructor)) static void fallback_perf_dump(void) {
    if (!getenv("SMR_FALLBACK_PERF")) return;
    double elapsed = (now_ns() - start_ns) / 1e9;
    double emu = (double)total_emu_ns / 1e9;
    fprintf(stderr, "[fallback-perf] interpreter=%.2fs of %.2fs wall (%.1f%%) calls=%llu\n",
            emu, elapsed, elapsed > 0 ? 100.0 * emu / elapsed : 0.0,
            (unsigned long long)total_calls);
}
