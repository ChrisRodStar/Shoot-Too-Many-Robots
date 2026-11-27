// Guest page allocator regression: VirtualAlloc(NULL) spans must be reusable after
// VirtualFree(MEM_RELEASE), coalesce with neighbours, preserve zero-on-read semantics for
// MEM_DECOMMIT, and never overlap a fixed reservation.
//
// The allocator sources are included so the test can observe the bump pointer and the
// reservation table directly; it is otherwise a plain host executable (no Unicorn, no Metal).
#include "FNVGuestMemory.h"
#ifndef FNV_GHEAP_SOURCE
#define FNV_GHEAP_SOURCE "../upstream/recomp/host/gheap.c"
#endif
#ifndef FNV_KERNEL_SOURCE
#define FNV_KERNEL_SOURCE "../upstream/recomp/host/shims_kernel32.c"
#endif
#include FNV_GHEAP_SOURCE
#include FNV_KERNEL_SOURCE
#include <assert.h>

uint8_t *MEM;
uint32_t host_image_base = 0x400000;

static uint32_t va(uint32_t at, uint32_t bytes, uint32_t type) {
    CPU c = {0};
    SETREG(&c, R_ESP, 0x1000);
    P32(0x1000, 0x123456);
    P32(0x1004, at);
    P32(0x1008, bytes);
    P32(0x100c, type);
    P32(0x1010, 4);
    VirtualAlloc_(&c);
    assert(REG(&c, R_ESP) == 0x1014);
    return REG(&c, R_EAX);
}

static uint32_t vf(uint32_t at, uint32_t bytes, uint32_t type) {
    CPU c = {0};
    SETREG(&c, R_ESP, 0x1000);
    P32(0x1000, 0x123456);
    P32(0x1004, at);
    P32(0x1008, bytes);
    P32(0x100c, type);
    P32(0x1010, 4);
    VirtualFree_(&c);
    assert(REG(&c, R_ESP) == 0x1010);
    return REG(&c, R_EAX);
}

#define MB 0x100000u
#define GRAN 0x10000u

int main(void) {
    MEM = fnv_reserve_guest();
    assert(MEM != MAP_FAILED);
    // Minimal fake PE header so the first VirtualAlloc can reserve the image range.
    P32(host_image_base + 0x3c, 0x80);
    P32(host_image_base + 0x80 + 24 + 56, 0x1000000);

    // 1. A released span is handed back from the free list without moving the bump pointer,
    //    and reads back as zero once it is reallocated (Windows zero-on-commit).
    uint32_t a = va(0, MB, 0x3000);
    assert(a && (a & (GRAN - 1)) == 0);
    memset(MEM + a, 0x5a, MB);
    uint32_t brk0 = brk_;
    int res0 = nres;
    assert(vf(a, 0, 0x8000));                  // MEM_RELEASE: size must be ignored
    assert(nres == res0 - 1);                  // reservation table entry removed
    uint32_t b = va(0, MB, 0x3000);
    assert(b == a);
    assert(brk_ == brk0);                      // reuse, no bump growth
    assert(MEM[b] == 0);

    // 2. Adjacent free spans coalesce, so a larger request fits the old holes.
    uint32_t x = va(0, 2 * MB, 0x3000);
    uint32_t y = va(0, 2 * MB, 0x3000);
    uint32_t z = va(0, 2 * MB, 0x3000);
    assert(y == x + 2 * MB && z == x + 4 * MB);
    uint32_t brk1 = brk_;
    vf(b, 0, 0x8000);
    vf(x, 0, 0x8000);
    vf(z, 0, 0x8000);
    // Freeing b (the reused 1 MB hole) and x merges them into one 3 MB span, while z stays a
    // separate 2 MB hole: the best-fit 2 MB request must take the exact-sized z, not the larger one.
    uint32_t w = va(0, 2 * MB, 0x3000);
    assert(w == z);
    vf(y, 0, 0x8000);                          // y joins the 3 MB span -> 5 MB
    vf(w, 0, 0x8000);                          // z joins it too -> 7 MB
    uint32_t big = va(0, 6 * MB, 0x3000);      // whole first hole is reusable as one span
    assert(big == b);
    assert(brk_ == brk1);
    vf(big, 0, 0x8000);

    // 3. MEM_DECOMMIT reclaims physical pages but keeps the reservation: reads are zero,
    //    untouched pages survive, and the range is not handed to another allocation.
    uint32_t d = va(0, 2 * MB, 0x3000);
    memset(MEM + d, 0x33, 2 * MB);
    uint32_t brk2 = brk_;
    assert(vf(d, MB, 0x4000));
    for (uint32_t i = 0; i < MB; i++) assert(MEM[d + i] == 0);
    assert(MEM[d + MB] == 0x33);
    uint32_t d2 = va(0, MB, 0x3000);
    assert(d2 != d);                           // still reserved, so never reused elsewhere
    assert(brk_ >= brk2);
    vf(d2, 0, 0x8000);
    vf(d, 0, 0x8000);

    // 4. An address below brk_ can never become a fixed reservation again, whether it is
    //    live or in the page free list.
    uint32_t q = va(0, MB, 0x3000);
    vf(q, 0, 0x8000);
    assert(!gheap_reserve_fixed(q & ~(GRAN - 1), (q & ~(GRAN - 1)) + MB));

    // 5. A live fixed reservation inside the heap is skipped by the page bump allocator.
    const uint32_t rlo = 0x20000000u, rhi = 0x20000000u + 8 * MB;
    assert(gheap_reserve_fixed(rlo, rhi));
    uint32_t p = va(0, 200 * MB, 0x3000);
    assert(p >= rhi || p + 200 * MB <= rlo);
    assert(p >= rhi);                          // the hole is in the path, so it was skipped
    vf(p, 0, 0x8000);

    // 6. The free list still serves after all of the above.
    uint32_t brk3 = brk_;
    uint32_t again = va(0, 200 * MB, 0x3000);
    assert(again == p && brk_ == brk3);

    gheap_report();
    printf("PASS: release/reuse, coalescing, decommit, fixed-reservation isolation\n");
    return 0;
}
