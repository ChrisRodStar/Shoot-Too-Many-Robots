#include <strings.h>
#include "shims.h"

ShimFn smr_find_msvcr90_fast_shim(const char *name);
ShimFn smr_find_msvcp90_fast_shim(const char *name);
ShimFn smr_find_fmodex_fast_shim(const char *name);
ShimFn smr_find_fmod_event_fast_shim(const char *name);

ShimFn smr_find_fast_shim(const char *dll, const char *name) {
    if (!dll || !name)
        return NULL;
    if (!strcasecmp(dll, "msvcr90.dll"))
        return smr_find_msvcr90_fast_shim(name);
    if (!strcasecmp(dll, "msvcp90.dll"))
        return smr_find_msvcp90_fast_shim(name);
    if (!strcasecmp(dll, "fmodex.dll"))
        return smr_find_fmodex_fast_shim(name);
    if (!strcasecmp(dll, "fmod_event.dll"))
        return smr_find_fmod_event_fast_shim(name);
    return NULL;
}
