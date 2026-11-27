"""Unit tests for MSVC9 __RTDynamicCast SI/MI/VI semantics in src/host/msvcr90.c."""
from pathlib import Path
import subprocess
import tempfile
from native_test_toolchain import COMPILER, PLATFORM_FLAGS, LIBRARIES

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]

HARNESS = r"""
#include <assert.h>
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
static volatile int g_trap_caught = 0;

uint32_t gmalloc(uint32_t n) {
    uint32_t p = (g_heap_ptr + 15u) & ~15u;
    g_heap_ptr = p + n + 16u;
    memset(MEM + p, 0, n);
    return p;
}
void gfree(uint32_t p) { (void)p; }
uint32_t grealloc(uint32_t p, uint32_t n) { (void)p; return gmalloc(n); }
uint32_t gsize(uint32_t p) { (void)p; return 0; }
void host_path(const char *win, char *out, size_t n) { (void)win; if (n) out[0] = 0; }
void w2a(uint32_t w, char *out, size_t n) { (void)w; if (n) out[0] = 0; }
uint32_t wlen(uint32_t w) { (void)w; return 0; }
const char *host_exe_name(void) { return "rtti_test.exe"; }
ShimFn host_find_shim(const char *dll, const char *name) { (void)dll; (void)name; return NULL; }
void rt_call(CPU *c, uint32_t a) { (void)c; (void)a; abort(); }
void rt_trap(CPU *c, int code, uint32_t addr) {
    (void)c; (void)code; (void)addr;
    g_trap_caught = 1;
    siglongjmp(g_trap_jmp, 1);
}

static void w32(uint32_t addr, uint32_t val) { memcpy(MEM + addr, &val, 4); }
static uint32_t bump_alloc(uint32_t size) {
    uint32_t p = (g_heap_ptr + 15u) & ~15u;
    g_heap_ptr = p + ((size + 15u) & ~15u);
    memset(MEM + p, 0, size);
    return p;
}

static uint32_t make_td(const char *name) {
    size_t len = strlen(name) + 1;
    uint32_t td = bump_alloc(8u + (uint32_t)len);
    w32(td + 0, 0x12345678u);
    w32(td + 4, 0u);
    memcpy(MEM + td + 8, name, len);
    return td;
}

static uint32_t make_bcd(uint32_t td, uint32_t nsub, int32_t mdisp, int32_t pdisp, int32_t vdisp,
                         uint32_t attrs, uint32_t sub_chd) {
    uint32_t bcd = bump_alloc(28);
    w32(bcd + 0, td);
    w32(bcd + 4, nsub);
    w32(bcd + 8, (uint32_t)mdisp);
    w32(bcd + 12, (uint32_t)pdisp);
    w32(bcd + 16, (uint32_t)vdisp);
    w32(bcd + 20, attrs);
    w32(bcd + 24, sub_chd);
    return bcd;
}

static uint32_t make_chd(uint32_t attrs, uint32_t count, const uint32_t *bcds) {
    uint32_t bca = bump_alloc(4 * count);
    for (uint32_t i = 0; i < count; i++) w32(bca + 4 * i, bcds[i]);
    uint32_t chd = bump_alloc(16);
    w32(chd + 0, 0);
    w32(chd + 4, attrs);
    w32(chd + 8, count);
    w32(chd + 12, bca);
    return chd;
}

static uint32_t make_vftable(uint32_t offset, uint32_t cd_off, uint32_t td, uint32_t chd) {
    uint32_t col = bump_alloc(20);
    w32(col + 0, 0);
    w32(col + 4, offset);
    w32(col + 8, cd_off);
    w32(col + 12, td);
    w32(col + 16, chd);
    uint32_t block = bump_alloc(16);
    uint32_t vftable = block + 4;
    w32(vftable - 4, col);
    w32(vftable, 0x00401000u);
    return vftable;
}

static uint32_t call_dyn_cast(ShimFn fn, uint32_t inptr, int32_t vfdelta,
                              uint32_t src_td, uint32_t target_td, uint32_t is_ref) {
    CPU c;
    memset(&c, 0, sizeof(c));
    uint32_t sp = 0x00800000u;
    SETREG(&c, R_ESP, sp);
    w32(sp + 0, 0x0040dead);
    w32(sp + 4, inptr);
    w32(sp + 8, (uint32_t)vfdelta);
    w32(sp + 12, src_td);
    w32(sp + 16, target_td);
    w32(sp + 20, is_ref);
    fn(&c);
    assert(REG(&c, R_ESP) == sp + 4);
    return REG(&c, R_EAX);
}

int main(void) {
    MEM = mmap(NULL, 64u << 20, PROT_READ | PROT_WRITE, MAP_ANON | MAP_PRIVATE, -1, 0);
    assert(MEM != MAP_FAILED);

    ShimFn dyn_cast = smr_find_msvcr90_fast_shim("__RTDynamicCast");
    assert(dyn_cast != NULL);

    // 1. NULL inptr returns 0 even if is_ref=1
    assert(call_dyn_cast(dyn_cast, 0, 0, 0x1000, 0x2000, 1) == 0);

    // 2. Single Inheritance: Derived : public Base, PrivSub : private Base
    uint32_t td_base = make_td(".?AVBase@@");
    uint32_t td_base_dll = make_td(".?AVBase@@"); // distinct address, same name
    uint32_t td_derived = make_td(".?AVDerived@@");
    uint32_t td_derived_dll = make_td(".?AVDerived@@");
    uint32_t td_other = make_td(".?AVOther@@");
    uint32_t td_priv = make_td(".?AVPrivSub@@");

    uint32_t si_bcds[2] = {
        make_bcd(td_derived, 1, 0, -1, 0, 0, 0),
        make_bcd(td_base, 0, 0, -1, 0, 0, 0),
    };
    uint32_t chd_si = make_chd(0, 2, si_bcds);
    uint32_t vft_si = make_vftable(0, 0, td_derived, chd_si);
    uint32_t obj_si = bump_alloc(32);
    w32(obj_si, vft_si);

    assert(call_dyn_cast(dyn_cast, obj_si, 0, td_base, td_derived, 0) == obj_si);
    assert(call_dyn_cast(dyn_cast, obj_si, 0, td_base_dll, td_derived_dll, 0) == obj_si);
    assert(call_dyn_cast(dyn_cast, obj_si, 0, td_base, td_other, 0) == 0);

    // bad_cast trap on is_ref=1
    g_trap_caught = 0;
    if (sigsetjmp(g_trap_jmp, 1) == 0) {
        call_dyn_cast(dyn_cast, obj_si, 0, td_base, td_other, 1);
        assert(0 && "expected bad_cast trap");
    }
    assert(g_trap_caught == 1);

    // Private SI base rejected (BCD_PRIVORPROTBASE = 4)
    uint32_t si_priv_bcds[2] = {
        make_bcd(td_priv, 1, 0, -1, 0, 0, 0),
        make_bcd(td_base, 0, 0, -1, 0, 4u, 0),
    };
    uint32_t chd_si_priv = make_chd(0, 2, si_priv_bcds);
    uint32_t vft_si_priv = make_vftable(0, 0, td_priv, chd_si_priv);
    uint32_t obj_si_priv = bump_alloc(32);
    w32(obj_si_priv, vft_si_priv);
    assert(call_dyn_cast(dyn_cast, obj_si_priv, 0, td_base, td_priv, 0) == 0);

    // 3. Multiple Inheritance: TouchTriggerComponent : TriggerComponentBase(0), TouchTriggerInterface(0x80)
    //    TriggerComponentBase : Component(0)
    uint32_t td_ttc = make_td(".?AVTouchTriggerComponent@@");
    uint32_t td_tcb = make_td(".?AVTriggerComponentBase@@");
    uint32_t td_comp = make_td(".?AVComponent@@");
    uint32_t td_tti = make_td(".?AVTouchTriggerInterface@@");

    uint32_t mi_bcds[4] = {
        make_bcd(td_ttc, 3, 0, -1, 0, 0, 0),
        make_bcd(td_tcb, 1, 0, -1, 0, 0, 0),
        make_bcd(td_comp, 0, 0, -1, 0, 0, 0),
        make_bcd(td_tti, 0, 0x80, -1, 0, 0, 0),
    };
    uint32_t chd_mi = make_chd(1u, 4, mi_bcds); // attrs=1 -> MI
    uint32_t vft_mi_primary = make_vftable(0, 0, td_ttc, chd_mi);
    uint32_t vft_mi_tti = make_vftable(0x80u, 0, td_ttc, chd_mi);
    uint32_t obj_mi = bump_alloc(0x100);
    w32(obj_mi + 0x00, vft_mi_primary);
    w32(obj_mi + 0x80, vft_mi_tti);

    // Exact SMR crash/stall cast: Component* (+0) -> TouchTriggerInterface* (+0x80)
    assert(call_dyn_cast(dyn_cast, obj_mi + 0x00, 0, td_comp, td_tti, 0) == obj_mi + 0x80);
    // Reverse cross-cast: TouchTriggerInterface* (+0x80) -> Component* (+0)
    assert(call_dyn_cast(dyn_cast, obj_mi + 0x80, 0, td_tti, td_comp, 0) == obj_mi + 0x00);
    // Cross-cast with vfdelta adjusting subobject pointer (+0x84 with vfdelta=4 -> +0x80)
    uint32_t obj_mi_delta_vft = make_vftable(0x84u, 0, td_ttc, chd_mi);
    w32(obj_mi + 0x84, obj_mi_delta_vft);
    assert(call_dyn_cast(dyn_cast, obj_mi + 0x84, 4, td_tti, td_comp, 0) == obj_mi + 0x00);
    // MI downcasts & upcast
    assert(call_dyn_cast(dyn_cast, obj_mi + 0x00, 0, td_comp, td_ttc, 0) == obj_mi + 0x00);
    assert(call_dyn_cast(dyn_cast, obj_mi + 0x80, 0, td_tti, td_ttc, 0) == obj_mi + 0x00);
    assert(call_dyn_cast(dyn_cast, obj_mi + 0x00, 0, td_ttc, td_tti, 0) == obj_mi + 0x80);

    // 4. MI visibility & ambiguity + sub-CHD private downcast checks
    // Layout: MidPriv : private HiddenBase(0), Full : public MidPriv(0), private SecretIfc(0x20), AmbigIfc(0x40), AmbigIfc(0x60)
    uint32_t td_full = make_td(".?AVFull@@");
    uint32_t td_midpriv = make_td(".?AVMidPriv@@");
    uint32_t td_hidden = make_td(".?AVHiddenBase@@");
    uint32_t td_secifc = make_td(".?AVSecretIfc@@");
    uint32_t td_ambig = make_td(".?AVAmbigIfc@@");

    // MidPriv's own CHD marks HiddenBase with BCD_NOTVISIBLE (1)
    uint32_t midpriv_bcds[2] = {
        make_bcd(td_midpriv, 1, 0, -1, 0, 0, 0),
        make_bcd(td_hidden, 0, 0, -1, 0, 1u, 0),
    };
    uint32_t chd_midpriv = make_chd(0, 2, midpriv_bcds);

    uint32_t full_bcds[6] = {
        make_bcd(td_full, 5, 0, -1, 0, 0, 0),
        make_bcd(td_midpriv, 1, 0, -1, 0, 0x40u, chd_midpriv),
        make_bcd(td_hidden, 0, 0, -1, 0, 1u, 0),
        make_bcd(td_secifc, 0, 0x20, -1, 0, 1u, 0),
        make_bcd(td_ambig, 0, 0x40, -1, 0, 2u, 0),
        make_bcd(td_ambig, 0, 0x60, -1, 0, 2u, 0),
    };
    uint32_t chd_full = make_chd(1u, 6, full_bcds);
    uint32_t vft_full_0 = make_vftable(0, 0, td_full, chd_full);
    uint32_t vft_full_20 = make_vftable(0x20u, 0, td_full, chd_full);
    uint32_t vft_full_40 = make_vftable(0x40u, 0, td_full, chd_full);
    uint32_t obj_full = bump_alloc(0x80);
    w32(obj_full + 0x00, vft_full_0);
    w32(obj_full + 0x20, vft_full_20);
    w32(obj_full + 0x40, vft_full_40);

    // Private base HiddenBase -> MidPriv via BCD_HASPCHD must fail
    assert(call_dyn_cast(dyn_cast, obj_full + 0x00, 0, td_hidden, td_midpriv, 0) == 0);
    // Private cross-cast MidPriv -> SecretIfc (target attr&1) must fail
    assert(call_dyn_cast(dyn_cast, obj_full + 0x00, 0, td_midpriv, td_secifc, 0) == 0);
    // Cross-cast FROM private base SecretIfc -> MidPriv (src attr&1) must fail
    assert(call_dyn_cast(dyn_cast, obj_full + 0x20, 0, td_secifc, td_midpriv, 0) == 0);
    // Cross-cast TO ambiguous target AmbigIfc (target attr&2) must fail
    assert(call_dyn_cast(dyn_cast, obj_full + 0x00, 0, td_midpriv, td_ambig, 0) == 0);
    // Cross-cast FROM specific ambiguous subobject AmbigIfc (+0x40) -> MidPriv MUST succeed!
    assert(call_dyn_cast(dyn_cast, obj_full + 0x40, 0, td_ambig, td_midpriv, 0) == obj_full + 0x00);

    // 5. Virtual Inheritance (attrs = 3): Diamond : Left(0), Right(0x10), virtual VBase(via vbtable -> +0x24)
    uint32_t td_diamond = make_td(".?AVDiamond@@");
    uint32_t td_left = make_td(".?AVLeft@@");
    uint32_t td_right = make_td(".?AVRight@@");
    uint32_t td_vbase = make_td(".?AVVBase@@");

    uint32_t vi_bcds5[5] = {
        make_bcd(td_diamond, 4, 0, -1, 0, 0, 0),
        make_bcd(td_left, 1, 0, -1, 0, 0, 0),
        make_bcd(td_vbase, 0, 0, 4, 4, 0x10u, 0), // BCD_VBOFCONTOBJ, offset = 4 + 0x20 = 0x24
        make_bcd(td_right, 1, 0x10, -1, 0, 0, 0),
        make_bcd(td_vbase, 0, 0, 4, 4, 0x10u, 0),
    };
    uint32_t chd_vi = make_chd(3u, 5, vi_bcds5); // attrs=3 -> VI + MI
    uint32_t vbtable = bump_alloc(16);
    w32(vbtable + 0, 0);
    w32(vbtable + 4, 0x20u); // complete_off = pdisp(4) + 0x20 = 0x24

    uint32_t vft_dia_left = make_vftable(0, 0, td_diamond, chd_vi);
    uint32_t vft_dia_right = make_vftable(0x10u, 0, td_diamond, chd_vi);
    uint32_t vft_dia_vbase = make_vftable(0x24u, 0, td_diamond, chd_vi);

    uint32_t obj_vi = bump_alloc(0x40);
    w32(obj_vi + 0x00, vft_dia_left);
    w32(obj_vi + 0x04, vbtable);
    w32(obj_vi + 0x10, vft_dia_right);
    w32(obj_vi + 0x24, vft_dia_vbase);

    // Downcast VBase* (+0x24) -> Diamond* (+0)
    assert(call_dyn_cast(dyn_cast, obj_vi + 0x24, 0, td_vbase, td_diamond, 0) == obj_vi + 0x00);
    // Downcast VBase* (+0x24) -> Left* (+0) and -> Right* (+0x10)
    assert(call_dyn_cast(dyn_cast, obj_vi + 0x24, 0, td_vbase, td_left, 0) == obj_vi + 0x00);
    assert(call_dyn_cast(dyn_cast, obj_vi + 0x24, 0, td_vbase, td_right, 0) == obj_vi + 0x10);
    // Cross-casts Left* (+0) <-> Right* (+0x10)
    assert(call_dyn_cast(dyn_cast, obj_vi + 0x00, 0, td_left, td_right, 0) == obj_vi + 0x10);
    assert(call_dyn_cast(dyn_cast, obj_vi + 0x10, 0, td_right, td_left, 0) == obj_vi + 0x00);
    // Upcast Left* (+0) -> VBase* (+0x24) via VI
    assert(call_dyn_cast(dyn_cast, obj_vi + 0x00, 0, td_left, td_vbase, 0) == obj_vi + 0x24);

    // VI ambiguous downcast VBase* -> Shared* where Shared appears in two subobjects at +0x00 and +0x10
    uint32_t td_shared = make_td(".?AVShared@@");
    uint32_t vi_amb_bcds[7] = {
        make_bcd(td_diamond, 6, 0, -1, 0, 0, 0),
        make_bcd(td_shared, 2, 0, -1, 0, 2u, 0),
        make_bcd(td_left, 1, 0, -1, 0, 0, 0),
        make_bcd(td_vbase, 0, 0, 4, 4, 0x10u, 0),
        make_bcd(td_shared, 2, 0x10, -1, 0, 2u, 0),
        make_bcd(td_right, 1, 0x10, -1, 0, 0, 0),
        make_bcd(td_vbase, 0, 0, 4, 4, 0x10u, 0),
    };
    uint32_t chd_vi_amb = make_chd(3u, 7, vi_amb_bcds);
    uint32_t vft_vi_amb_vbase = make_vftable(0x24u, 0, td_diamond, chd_vi_amb);
    uint32_t obj_vi_amb = bump_alloc(0x40);
    w32(obj_vi_amb + 0x04, vbtable);
    w32(obj_vi_amb + 0x24, vft_vi_amb_vbase);
    assert(call_dyn_cast(dyn_cast, obj_vi_amb + 0x24, 0, td_vbase, td_shared, 0) == 0);

    puts("rtti_dynamic_cast_test: PASS");
    return 0;
}
"""

with tempfile.TemporaryDirectory(prefix='smr-rtti-') as temp:
    src = Path(temp) / 'test.c'
    binary = Path(temp) / 'rtti-dynamic-cast-test'
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
    subprocess.run([str(binary)], check=True, timeout=15)
