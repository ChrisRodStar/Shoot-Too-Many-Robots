#include "FNVPad.h"
#include <pthread.h>
#include <string.h>

static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static FNVPadState physical;
static int connected;

void fnv_pad_physical_state(const FNVPadState *state, int is_connected) {
    pthread_mutex_lock(&lock);
    connected = !!is_connected;
    if (connected && state) {
        if (memcmp((const char *)state + 4, (const char *)&physical + 4, sizeof(FNVPadState) - 4) != 0) {
            uint32_t next_pkt = physical.packet + 1;
            physical = *state;
            physical.packet = next_pkt;
        }
    } else {
        uint32_t next_pkt = physical.packet + 1;
        memset(&physical, 0, sizeof physical);
        physical.packet = next_pkt;
    }
    pthread_mutex_unlock(&lock);
}

int fnv_pad_connected(void) {
    pthread_mutex_lock(&lock);
    int c = connected;
    pthread_mutex_unlock(&lock);
    return c;
}

int fnv_analog_enabled(void) {
    return fnv_pad_connected();
}

void fnv_pad_snapshot(FNVPadState *state) {
    pthread_mutex_lock(&lock);
    *state = physical;
    pthread_mutex_unlock(&lock);
}

void fnv_pad_reset(void) {
    pthread_mutex_lock(&lock);
    uint32_t next_pkt = physical.packet + 1;
    memset(&physical, 0, sizeof physical);
    physical.packet = next_pkt;
    pthread_mutex_unlock(&lock);
}

// Weak fallbacks: a headless host (unit tests, the startup diagnostic) links FNVPad.c without
// the Objective-C gamepad host. The windowed host links src/host/gamepad.m which provides the
// strong definitions and overrides these at link time.
__attribute__((weak)) void fnv_pad_poll(void) {}

__attribute__((weak)) void fnv_pad_set_rumble(uint16_t left_motor, uint16_t right_motor) {
    (void)left_motor;
    (void)right_motor;
}
