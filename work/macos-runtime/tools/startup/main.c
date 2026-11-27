// Build-machine startup diagnostic using the same guest dispatcher and host shims.
// The null renderer cannot validate iPhone graphics or gameplay.
#include <stdio.h>
#include <stdlib.h>
#include "rt.h"
extern int fnv_run_game(int, char **);
#ifdef SMR_METAL_HOST
extern int smr_run_windowed(int, char **);
#endif
#ifdef FNV_STARTUP_HOST_CHECK
const uint32_t rt_fn_addr[] = {0};
const GuestFn rt_fn_ptr[] = {0};
const int rt_fn_count = 0;
#endif
int main(int argc, char **argv) {
    setvbuf(stderr, NULL, _IONBF, 0);
#ifdef FNV_STARTUP_HOST_CHECK
    (void)argc; (void)argv;
    puts("PASS: native diagnostic host linked; no game code executed");
    return 0;
#else
#ifdef SMR_METAL_HOST
    if (getenv("SMR_WINDOW"))
        return smr_run_windowed(argc, argv);
#endif
    return fnv_run_game(argc, argv);
#endif
}
