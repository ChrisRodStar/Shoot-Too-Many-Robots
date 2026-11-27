#import <AppKit/AppKit.h>
#import "FNVSurface.h"
#include "FNVKeyMap.h"
#include "input.h"

@interface SMRGameWindow : NSWindow {
    BOOL guest_keys[128];
    BOOL guest_buttons[8];
    double mouse_dx, mouse_dy;
}
@end

@implementation SMRGameWindow
- (BOOL)containsMouseEvent:(NSEvent *)event {
    NSView *view = self.contentView;
    NSPoint point = [view convertPoint:event.locationInWindow fromView:nil];
    return [view mouse:point inRect:view.bounds];
}

- (void)sendEvent:(NSEvent *)event {
    if (event.type == NSEventTypeKeyDown || event.type == NSEventTypeKeyUp) {
        NSUInteger code = event.keyCode;
        BOOL down = event.type == NSEventTypeKeyDown;
        if (code < sizeof(mac2dik) && mac2dik[code] &&
            ((!down && guest_keys[code]) ||
             (down && !(event.modifierFlags & NSEventModifierFlagCommand)))) {
            guest_keys[code] = down;
            input_key(mac2dik[code], down);
            return;
        }
    } else if (event.type == NSEventTypeFlagsChanged) {
        NSEventModifierFlags flags = event.modifierFlags;
        input_key(0x2A, (flags & NSEventModifierFlagShift) != 0);
        input_key(0x1D, (flags & NSEventModifierFlagControl) != 0);
        input_key(0x38, (flags & NSEventModifierFlagOption) != 0);
        input_key(0x3A, (flags & NSEventModifierFlagCapsLock) != 0);
    }
    switch (event.type) {
    case NSEventTypeLeftMouseDown:
    case NSEventTypeRightMouseDown:
    case NSEventTypeOtherMouseDown: {
        NSUInteger button = event.buttonNumber;
        if (button < sizeof(guest_buttons) && [self containsMouseEvent:event]) {
            guest_buttons[button] = YES;
            input_mouse_button((int)button, 1);
        }
        break;
    }
    case NSEventTypeLeftMouseUp:
    case NSEventTypeRightMouseUp:
    case NSEventTypeOtherMouseUp: {
        NSUInteger button = event.buttonNumber;
        if (button < sizeof(guest_buttons) && guest_buttons[button]) {
            guest_buttons[button] = NO;
            input_mouse_button((int)button, 0);
        }
        break;
    }
    case NSEventTypeMouseMoved:
    case NSEventTypeLeftMouseDragged:
    case NSEventTypeRightMouseDragged:
    case NSEventTypeOtherMouseDragged:
        if (self.isKeyWindow && [self containsMouseEvent:event]) {
            mouse_dx += event.deltaX;
            mouse_dy += event.deltaY;
            int dx = (int)mouse_dx, dy = (int)mouse_dy;
            if (dx || dy) {
                input_mouse_move(dx, dy);
                mouse_dx -= dx;
                mouse_dy -= dy;
            }
        }
        break;
    default:
        break;
    }
    [super sendEvent:event];
}

- (void)resignKeyWindow {
    for (NSUInteger code = 0; code < sizeof(mac2dik); code++) {
        if (guest_keys[code]) {
            input_key(mac2dik[code], 0);
            guest_keys[code] = NO;
        }
    }
    input_key(0x2A, 0);
    input_key(0x1D, 0);
    input_key(0x38, 0);
    input_key(0x3A, 0);
    for (NSUInteger button = 0; button < sizeof(guest_buttons); button++) {
        if (guest_buttons[button]) {
            input_mouse_button((int)button, 0);
            guest_buttons[button] = NO;
        }
    }
    mouse_dx = mouse_dy = 0;
    [super resignKeyWindow];
}
@end

static NSWindow *game_window;
static CAMetalLayer *game_layer;

int fnv_run_game(int argc, char **argv);

CAMetalLayer *fnv_surface(id<MTLDevice> device, CGSize size) {
    dispatch_sync(dispatch_get_main_queue(), ^{
        NSRect bounds = NSMakeRect(0, 0, size.width, size.height);
        game_window = [[SMRGameWindow alloc] initWithContentRect:bounds
            styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable |
                      NSWindowStyleMaskMiniaturizable
              backing:NSBackingStoreBuffered defer:NO];
        game_window.title = @"Shoot Too Many Robots";
        game_window.acceptsMouseMovedEvents = YES;
        game_window.releasedWhenClosed = NO;
        NSView *view = game_window.contentView;
        game_layer = [CAMetalLayer layer];
        game_layer.device = device;
        game_layer.pixelFormat = MTLPixelFormatBGRA8Unorm;
        game_layer.frame = view.bounds;
        game_layer.drawableSize = size;
        view.wantsLayer = YES;
        view.layer = game_layer;
        NSScreen *target = nil;
        NSArray<NSScreen *> *screens = [NSScreen screens];
        for (NSScreen *s in screens) {
            if ([s.localizedName rangeOfString:@"DELL" options:NSCaseInsensitiveSearch].location != NSNotFound) {
                target = s;
                break;
            }
        }
        if (!target && screens.count > 1)
            target = screens[1];
        if (target) {
            NSRect vis = target.visibleFrame;
            NSRect wf = game_window.frame;
            [game_window setFrameOrigin:NSMakePoint(
                vis.origin.x + (vis.size.width - wf.size.width) * 0.5,
                vis.origin.y + (vis.size.height - wf.size.height) * 0.5)];
        } else {
            [game_window center];
        }
        [game_window makeKeyAndOrderFront:nil];
        [NSApp activate];
        fprintf(stderr, "[smr-window] opened %.0f x %.0f Metal window\n", size.width, size.height);
    });
    return game_layer;
}

void fnv_resize_surface(CGSize size) {
    dispatch_async(dispatch_get_main_queue(), ^{
        if (!game_window)
            return;
        [game_window setContentSize:size];
        game_layer.frame = game_window.contentView.bounds;
        game_layer.drawableSize = size;
    });
}

void fnv_wait_active(void) {}

@interface SMRAppDelegate : NSObject <NSApplicationDelegate>
@end

@implementation SMRAppDelegate
- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)app {
    (void)app;
    return YES;
}
@end

int smr_run_windowed(int argc, char **argv) {
    @autoreleasepool {
        NSApplication *app = [NSApplication sharedApplication];
        SMRAppDelegate *delegate = [SMRAppDelegate new];
        app.delegate = delegate;
        [app setActivationPolicy:NSApplicationActivationPolicyRegular];
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
            @autoreleasepool {
                int result = fnv_run_game(argc, argv);
                fprintf(stderr, "[smr-window] guest stopped with status %d\n", result);
                exit(result);
            }
        });
        [app run];
    }
    return 0;
}
