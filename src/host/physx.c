#include <stdint.h>
#include "shims.h"

// PhysXCore.dll is statically lifted (work/physxcore-generated) at its runtime
// base, so its NpActor/Body/Shape/Scene methods dispatch natively.  Keep the
// address-shim hook for rt_dispatch.c, but install no manual offset shims.
ShimFn smr_find_addr_shim(uint32_t addr) {
    (void)addr;
    return NULL;
}
