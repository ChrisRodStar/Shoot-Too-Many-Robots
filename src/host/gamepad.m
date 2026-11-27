// GameController.framework + CoreHaptics backend for the XInput shim.
//
// Windowed hosts link this file alongside FNVPad.c. Headless/unit-test links omit it and use the
// weak no-op fallbacks in FNVPad.c. Polling is driven lazily from XInputGetState, so no window or
// surface code needs to know the pad exists.
#import <CoreHaptics/CoreHaptics.h>
#import <Foundation/Foundation.h>
#import <GameController/GameController.h>

#include <math.h>
#include <pthread.h>
#include <stdint.h>

#include "FNVPad.h"

static dispatch_once_t once;
static id connect_observer;
static id disconnect_observer;

static pthread_mutex_t pad_lock = PTHREAD_MUTEX_INITIALIZER;
static GCController *current_controller;

typedef struct {
    CHHapticEngine *engine;
    id<CHHapticPatternPlayer> player;
    float intensity;
} RumbleChannel;

static RumbleChannel left_channel;
static RumbleChannel right_channel;
static RumbleChannel combined_channel;
static uint16_t rumble_left;
static uint16_t rumble_right;

static void stop_channel(RumbleChannel *channel) {
    if (channel->player) {
        [channel->player stopAtTime:0 error:nil];
        channel->player = nil;
    }
    if (channel->engine) {
        [channel->engine stopWithCompletionHandler:nil];
        channel->engine = nil;
    }
    channel->intensity = 0.0f;
}

static void stop_all_rumble(void) {
    stop_channel(&left_channel);
    stop_channel(&right_channel);
    stop_channel(&combined_channel);
}

static CHHapticEngine *create_engine(GCController *controller, GCHapticsLocality locality) {
    GCDeviceHaptics *haptics = controller.haptics;
    if (!haptics) return nil;
    if (locality && ![haptics.supportedLocalities containsObject:locality]) {
        locality = GCHapticsLocalityDefault;
    }
    CHHapticEngine *engine = [haptics createEngineWithLocality:locality];
    if (!engine && locality != GCHapticsLocalityDefault) {
        engine = [haptics createEngineWithLocality:GCHapticsLocalityDefault];
    }
    if (!engine) return nil;
    NSError *error = nil;
    if (![engine startAndReturnError:&error]) {
        return nil;
    }
    __weak CHHapticEngine *weak_engine = engine;
    engine.resetHandler = ^{
        [weak_engine startAndReturnError:nil];
    };
    return engine;
}

// Keep one continuous haptic event alive per actuator. Updating a running player's intensity
// avoids restarting the engine for every XInputSetState call.
static void set_channel(RumbleChannel *channel, GCController *controller,
                        GCHapticsLocality locality, float intensity) {
    if (intensity <= 0.001f) {
        stop_channel(channel);
        return;
    }
    if (!channel->engine) {
        channel->engine = create_engine(controller, locality);
        if (!channel->engine) return;
    }
    NSError *error = nil;
    if (channel->player) {
        CHHapticDynamicParameter *parameter =
            [[CHHapticDynamicParameter alloc] initWithParameterID:CHHapticDynamicParameterIDHapticIntensityControl
                                                            value:intensity
                                                     relativeTime:0];
        [channel->player sendParameters:@[parameter] atTime:0 error:&error];
        channel->intensity = intensity;
        return;
    }
    CHHapticEventParameter *intensity_parameter =
        [[CHHapticEventParameter alloc] initWithParameterID:CHHapticEventParameterIDHapticIntensity
                                                      value:intensity];
    CHHapticEventParameter *sharpness_parameter =
        [[CHHapticEventParameter alloc] initWithParameterID:CHHapticEventParameterIDHapticSharpness
                                                      value:0.35];
    CHHapticEvent *event =
        [[CHHapticEvent alloc] initWithEventType:CHHapticEventTypeHapticContinuous
                                      parameters:@[intensity_parameter, sharpness_parameter]
                                    relativeTime:0
                                        duration:GCHapticDurationInfinite];
    CHHapticPattern *pattern = [[CHHapticPattern alloc] initWithEvents:@[event]
                                                              parameters:@[]
                                                                   error:&error];
    if (!pattern) return;
    channel->player = [channel->engine createPlayerWithPattern:pattern error:&error];
    if (!channel->player) return;
    [channel->player startAtTime:0 error:&error];
    channel->intensity = intensity;
}

static void apply_rumble_locked(void) {
    GCController *controller = current_controller;
    if (!controller) {
        stop_all_rumble();
        return;
    }
    float left = rumble_left / 65535.0f;
    float right = rumble_right / 65535.0f;
    if (left <= 0.001f && right <= 0.001f) {
        stop_all_rumble();
        return;
    }
    GCDeviceHaptics *haptics = controller.haptics;
    NSSet<GCHapticsLocality> *localities = haptics.supportedLocalities;
    BOOL split = localities && [localities containsObject:GCHapticsLocalityLeftHandle] &&
                 [localities containsObject:GCHapticsLocalityRightHandle];
    if (split) {
        stop_channel(&combined_channel);
        set_channel(&left_channel, controller, GCHapticsLocalityLeftHandle, left);
        set_channel(&right_channel, controller, GCHapticsLocalityRightHandle, right);
    } else {
        // The controller only exposes one actuator locality; drive it with the strongest motor.
        stop_channel(&left_channel);
        stop_channel(&right_channel);
        set_channel(&combined_channel, controller, GCHapticsLocalityDefault,
                    left > right ? left : right);
    }
}

static void register_controller_notifications(void) {
    NSNotificationCenter *center = NSNotificationCenter.defaultCenter;
    connect_observer = [center addObserverForName:GCControllerDidConnectNotification
                                           object:nil
                                            queue:NSOperationQueue.mainQueue
                                       usingBlock:^(NSNotification *note) {
                                           (void)note;
                                           fnv_pad_poll();
                                       }];
    disconnect_observer = [center addObserverForName:GCControllerDidDisconnectNotification
                                              object:nil
                                               queue:NSOperationQueue.mainQueue
                                          usingBlock:^(NSNotification *note) {
                                              (void)note;
                                              fnv_pad_poll();
                                          }];
    [GCController startWirelessControllerDiscoveryWithCompletionHandler:nil];
}

static void initialize_pad(void) {
    register_controller_notifications();
}

static GCController *find_controller(void) {
    for (GCController *controller in GCController.controllers) {
        if (controller.extendedGamepad) return controller;
    }
    return nil;
}

static FNVPadState sample_controller(GCExtendedGamepad *pad) {
    FNVPadState state = {0};
    state.lx = (int16_t)lround(pad.leftThumbstick.xAxis.value * 32767.0);
    state.ly = (int16_t)lround(pad.leftThumbstick.yAxis.value * 32767.0);
    state.rx = (int16_t)lround(pad.rightThumbstick.xAxis.value * 32767.0);
    state.ry = (int16_t)lround(pad.rightThumbstick.yAxis.value * 32767.0);
    state.left_trigger = (uint8_t)lround(pad.leftTrigger.value * 255.0);
    state.right_trigger = (uint8_t)lround(pad.rightTrigger.value * 255.0);
    if (pad.dpad.up.isPressed) state.buttons |= 0x0001;
    if (pad.dpad.down.isPressed) state.buttons |= 0x0002;
    if (pad.dpad.left.isPressed) state.buttons |= 0x0004;
    if (pad.dpad.right.isPressed) state.buttons |= 0x0008;
    if (pad.buttonMenu.isPressed) state.buttons |= 0x0010;
    if (pad.buttonOptions.isPressed) state.buttons |= 0x0020;
    if (pad.leftThumbstickButton.isPressed) state.buttons |= 0x0040;
    if (pad.rightThumbstickButton.isPressed) state.buttons |= 0x0080;
    if (pad.leftShoulder.isPressed) state.buttons |= 0x0100;
    if (pad.rightShoulder.isPressed) state.buttons |= 0x0200;
    if (pad.buttonA.isPressed) state.buttons |= 0x1000;
    if (pad.buttonB.isPressed) state.buttons |= 0x2000;
    if (pad.buttonX.isPressed) state.buttons |= 0x4000;
    if (pad.buttonY.isPressed) state.buttons |= 0x8000;
    return state;
}

void fnv_pad_poll(void) {
    dispatch_once(&once, ^{ initialize_pad(); });
    GCController *controller = find_controller();
    GCExtendedGamepad *pad = controller.extendedGamepad;
    FNVPadState state = pad ? sample_controller(pad) : (FNVPadState){0};
    pthread_mutex_lock(&pad_lock);
    if (controller != current_controller) {
        current_controller = controller;
        stop_all_rumble();
    }
    pthread_mutex_unlock(&pad_lock);
    fnv_pad_physical_state(&state, pad != nil);
}

void fnv_pad_set_rumble(uint16_t left_motor, uint16_t right_motor) {
    dispatch_once(&once, ^{ initialize_pad(); });
    pthread_mutex_lock(&pad_lock);
    rumble_left = left_motor;
    rumble_right = right_motor;
    apply_rumble_locked();
    pthread_mutex_unlock(&pad_lock);
}
