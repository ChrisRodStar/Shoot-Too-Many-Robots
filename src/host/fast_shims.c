#include <strings.h>
#include "shims.h"

ShimFn smr_find_msvcr90_fast_shim(const char *name);
ShimFn smr_find_msvcp90_fast_shim(const char *name);

// fmodex.dll and fmod_event.dll are not intercepted here: both are statically recompiled and
// the guest binds their real lifted exports instead of native no-op stubs.
ShimFn smr_find_fast_shim(const char *dll, const char *name) {
    if (!dll || !name)
        return NULL;
    if (!strcasecmp(dll, "msvcr90.dll"))
        return smr_find_msvcr90_fast_shim(name);
    if (!strcasecmp(dll, "msvcp90.dll"))
        return smr_find_msvcp90_fast_shim(name);
    return NULL;
}
