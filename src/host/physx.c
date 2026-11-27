#include <math.h>
#include <stdint.h>
#include <string.h>
#include "shims.h"

void rt_fallback(CPU *c, uint32_t a);

// Helper to invoke a guest __thiscall method with 0 stack args and return EAX.
static uint32_t call_this0(CPU *c, uint32_t addr, uint32_t self) {
    uint32_t esp = REG(c, R_ESP);
    P32(esp - 4, HOST_EXIT_THUNK);
    SETREG(c, R_ESP, esp - 4);
    SETREG(c, R_ECX, self);
    rt_call(c, addr);
    SETREG(c, R_ESP, esp);
    return REG(c, R_EAX);
}

// Helper to invoke a guest __stdcall/__thiscall(1 arg) method and return EAX.
static uint32_t call_this1(CPU *c, uint32_t addr, uint32_t self, uint32_t arg0) {
    uint32_t esp = REG(c, R_ESP);
    P32(esp - 4, arg0);
    P32(esp - 8, HOST_EXIT_THUNK);
    SETREG(c, R_ESP, esp - 8);
    SETREG(c, R_ECX, self);
    rt_call(c, addr);
    SETREG(c, R_ESP, esp);
    return REG(c, R_EAX);
}

// 0x11525f70: NpActor::isDynamic()
SHIM(physx_NpActor_isDynamic) {
    RET(c, G32(REG(c, R_ECX) + 0x20) != 0, 0);
}

// 0x11524df0: NpActor::getScene()
SHIM(physx_NpActor_getScene) {
    RET(c, G32(REG(c, R_ECX) + 0x1c), 0);
}

// 0x115260d0: NpActor::getGlobalPosition(NxVec3 &out)
SHIM(physx_NpActor_getGlobalPosition) {
    uint32_t self = REG(c, R_ECX);
    uint32_t out = ARG(c, 0);
    uint32_t body = G32(self + 0x20);
    if (body) {
        call_this1(c, G32(G32(body) + 4), body, out);
        RET(c, out, 1);
        return;
    }
    memcpy(MEM + out, MEM + self + 0x6c, 12);
    RET(c, out, 1);
}

static void mat33_to_quat(const float m[9], float q[4]) {
    float tr = m[0] + m[4] + m[8];
    if (tr >= 0.0f) {
        float s = sqrtf(tr + 1.0f);
        float inv = 0.5f / s;
        q[0] = (m[7] - m[5]) * inv;
        q[1] = (m[2] - m[6]) * inv;
        q[2] = (m[3] - m[1]) * inv;
        q[3] = 0.5f * s;
    } else if (m[0] >= m[4] && m[0] >= m[8]) {
        float s = sqrtf(1.0f + m[0] - m[4] - m[8]);
        float inv = 0.5f / s;
        q[0] = 0.5f * s;
        q[1] = (m[3] + m[1]) * inv;
        q[2] = (m[2] + m[6]) * inv;
        q[3] = (m[7] - m[5]) * inv;
    } else if (m[4] >= m[8]) {
        float s = sqrtf(1.0f + m[4] - m[0] - m[8]);
        float inv = 0.5f / s;
        q[0] = (m[3] + m[1]) * inv;
        q[1] = 0.5f * s;
        q[2] = (m[7] + m[5]) * inv;
        q[3] = (m[2] - m[6]) * inv;
    } else {
        float s = sqrtf(1.0f + m[8] - m[0] - m[4]);
        float inv = 0.5f / s;
        q[0] = (m[2] + m[6]) * inv;
        q[1] = (m[7] + m[5]) * inv;
        q[2] = 0.5f * s;
        q[3] = (m[3] - m[1]) * inv;
    }
}

// 0x1152acb0: NpActor::getGlobalOrientationQuat(NxQuat &out)
SHIM(physx_NpActor_getGlobalOrientationQuat) {
    uint32_t self = REG(c, R_ECX);
    uint32_t out = ARG(c, 0);
    uint32_t body = G32(self + 0x20);
    if (body) {
        call_this1(c, G32(G32(body) + 8), body, out);
        RET(c, out, 1);
        return;
    }
    float m[9], q[4];
    memcpy(m, MEM + self + 0x48, sizeof m);
    mat33_to_quat(m, q);
    memcpy(MEM + out, q, sizeof q);
    RET(c, out, 1);
}

// 0x11526630: NpActor::getLinearVelocity(NxVec3 &out)
SHIM(physx_NpActor_getLinearVelocity) {
    uint32_t self = REG(c, R_ECX);
    uint32_t out = ARG(c, 0);
    uint32_t body = G32(self + 0x20);
    if (body) {
        call_this1(c, G32(G32(body) + 0x18), body, out);
        RET(c, out, 1);
        return;
    }
    rt_fallback(c, 0x11526630u);
}

// 0x11527230: NpActor::readActorFlag(NxActorFlag flag)
SHIM(physx_NpActor_readActorFlag) {
    uint32_t self = REG(c, R_ECX);
    uint32_t flag = ARG(c, 0);
    uint32_t body = G32(self + 0x20);
    if (!body) {
        rt_fallback(c, 0x11527230u);
        return;
    }
    uint32_t flags = call_this0(c, G32(G32(body) + 0x78), body);
    RET(c, (flags & flag) != 0, 1);
}

// 0x115261f0: NpActor::isSleeping()
SHIM(physx_NpActor_isSleeping) {
    uint32_t self = REG(c, R_ECX);
    uint32_t body = G32(self + 0x20);
    if (!body) {
        RET(c, 1, 0);
        return;
    }
    SETREG(c, R_ECX, body);
    rt_call(c, G32(G32(body) + 0x38));
}

// 0x11526160: NpActor::getNbShapes() / shape query
SHIM(physx_NpActor_vtable_24_1c) {
    uint32_t self = REG(c, R_ECX);
    uint32_t sub = G32(self + 0x24);
    if (!sub) {
        RET(c, 0, 0);
        return;
    }
    SETREG(c, R_ECX, sub);
    rt_call(c, G32(G32(sub) + 0x1c));
}

// 0x11526180: NpActor::sub24 query
SHIM(physx_NpActor_vtable_24_1e0) {
    uint32_t self = REG(c, R_ECX);
    uint32_t sub = G32(self + 0x24);
    if (!sub) {
        RET(c, 0, 0);
        return;
    }
    if (call_this0(c, G32(G32(sub) + 4), sub) == 9) {
        SETREG(c, R_ECX, sub);
        rt_call(c, G32(G32(sub) + 0x1e0));
        return;
    }
    RET(c, 1, 0);
}

// 0x115aecf0: Body::readActorFlag() -> [ecx + 0x14c]
SHIM(physx_Body_getActorFlags) {
    RET(c, G32(REG(c, R_ECX) + 0x14c), 0);
}

// 0x115af130: Body::getGlobalPosition(NxVec3 &out) -> [ecx + 0x1bc..0x1c7]
SHIM(physx_Body_getGlobalPosition) {
    uint32_t out = ARG(c, 0);
    memcpy(MEM + out, MEM + REG(c, R_ECX) + 0x1bc, 12);
    RET(c, out, 1);
}

// 0x115af100: Body::getGlobalOrientationQuat(NxQuat &out) -> [ecx + 0x1c8..0x1d7]
SHIM(physx_Body_getGlobalOrientationQuat) {
    uint32_t out = ARG(c, 0);
    memcpy(MEM + out, MEM + REG(c, R_ECX) + 0x1c8, 16);
    RET(c, out, 1);
}

// 0x115aed30: Body::isSleeping() -> byte [ecx + 0x1b8]
SHIM(physx_Body_isSleeping) {
    uint32_t eax = (REG(c, R_EAX) & ~0xffu) | MEM[REG(c, R_ECX) + 0x1b8];
    RET(c, eax, 0);
}

// 0x115aeec0: Body::getLinearVelocity(NxVec3 &out) -> [ecx + 0x1a0..0x1ab]
SHIM(physx_Body_getLinearVelocity) {
    uint32_t out = ARG(c, 0);
    memcpy(MEM + out, MEM + REG(c, R_ECX) + 0x1a0, 12);
    RET(c, out, 1);
}

// 0x114f5a40: Scene::get48c() -> [ecx + 0x48c]
SHIM(physx_Scene_get48c) {
    RET(c, G32(REG(c, R_ECX) + 0x48c), 0);
}

// 0x114f0ce0: get1c() -> [ecx + 0x1c]
SHIM(physx_get1c) {
    RET(c, G32(REG(c, R_ECX) + 0x1c), 0);
}

// 0x115261c0: NpActor::readFlag2c(flag) -> ([ecx + 0x2c] & flag) != 0
SHIM(physx_NpActor_readFlag2c) {
    uint32_t v = G32(REG(c, R_ECX) + 0x2c) & ARG(c, 0);
    RET(c, v != 0, 1);
}

// 0x1157e490: Shape::getType() -> 9
SHIM(physx_Shape_ret9) {
    RET(c, 9, 0);
}

// 0x1157e4e0: Shape::get10() -> [ecx + 0x10]
SHIM(physx_Shape_get10) {
    RET(c, G32(REG(c, R_ECX) + 0x10), 0);
}

// 0x1157e520: Shape::get38() -> [ecx + 0x38]
SHIM(physx_Shape_get38) {
    RET(c, G32(REG(c, R_ECX) + 0x38), 0);
}

ShimFn smr_find_addr_shim(uint32_t addr) {
    switch (addr) {
    case 0x11525f70u: return physx_NpActor_isDynamic_;
    case 0x11524df0u: return physx_NpActor_getScene_;
    case 0x115260d0u: return physx_NpActor_getGlobalPosition_;
    case 0x1152acb0u: return physx_NpActor_getGlobalOrientationQuat_;
    case 0x11526630u: return physx_NpActor_getLinearVelocity_;
    case 0x11527230u: return physx_NpActor_readActorFlag_;
    case 0x115261f0u: return physx_NpActor_isSleeping_;
    case 0x11526160u: return physx_NpActor_vtable_24_1c_;
    case 0x11526180u: return physx_NpActor_vtable_24_1e0_;
    case 0x115aecf0u: return physx_Body_getActorFlags_;
    case 0x115af130u: return physx_Body_getGlobalPosition_;
    case 0x115af100u: return physx_Body_getGlobalOrientationQuat_;
    case 0x115aed30u: return physx_Body_isSleeping_;
    case 0x115aeec0u: return physx_Body_getLinearVelocity_;
    case 0x114f5a40u: return physx_Scene_get48c_;
    case 0x114f0ce0u: return physx_get1c_;
    case 0x115261c0u: return physx_NpActor_readFlag2c_;
    case 0x1157e490u: return physx_Shape_ret9_;
    case 0x1157e4e0u: return physx_Shape_get10_;
    case 0x1157e520u: return physx_Shape_get38_;
    default: return NULL;
    }
}
