#include <stdint.h>
#include <string.h>
#include "shims.h"

// MSVC9 std::basic_string<wchar_t> (Release, 28 bytes):
//   +0x00: allocator/iter proxy (unused by ctor)
//   +0x04: _Bx (_Buf[8] when _Myres < 8, else _Ptr)
//   +0x14: _Mysize
//   +0x18: _Myres
SHIM(msvcp90_wstring_ctor_wptr) {
    uint32_t self = REG(c, R_ECX);
    uint32_t src = ARG(c, 0);
    if (!self || !src)
        rt_trap(c, TRAP_IMPORT, self ? src : self);

    uint32_t len = wlen(src);
    uint32_t cap = 7;
    uint32_t dst = self + 4;
    if (len > 7) {
        cap = len | 7u;
        dst = gmalloc((cap + 1u) * 2u);
        if (!dst)
            rt_trap(c, TRAP_IMPORT, self);
        P32(self + 4, dst);
    }
    memcpy(MEM + dst, MEM + src, (size_t)(len + 1u) * 2u);
    P32(self + 0x14, len);
    P32(self + 0x18, cap);
    RET(c, self, 1);
}

ShimFn smr_find_msvcp90_fast_shim(const char *name) {
    if (!name)
        return NULL;
    if (!strcmp(name, "??0?$basic_string@_WU?$char_traits@_W@std@@V?$allocator@_W@2@@std@@QAE@PB_W@Z"))
        return msvcp90_wstring_ctor_wptr_;
    return NULL;
}
