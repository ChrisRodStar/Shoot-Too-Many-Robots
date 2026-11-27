#pragma once
#include <stdint.h>

typedef struct {
    uint32_t packet;
    uint16_t buttons;
    uint8_t left_trigger, right_trigger;
    int16_t lx, ly, rx, ry;
} FNVPadState;

void fnv_pad_physical_state(const FNVPadState *state, int connected);
int fnv_pad_connected(void);
int fnv_analog_enabled(void);
void fnv_pad_snapshot(FNVPadState *state);
void fnv_pad_reset(void);

// GameController-backed polling and rumble. Both have weak no-op fallbacks in FNVPad.c so
// headless/unit-test links that omit the Objective-C host still resolve; the strong
// implementations live in src/host/gamepad.m inside the windowed game host.
void fnv_pad_poll(void);
void fnv_pad_set_rumble(uint16_t left_motor, uint16_t right_motor);
