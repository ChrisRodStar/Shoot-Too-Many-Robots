#import <AppKit/AppKit.h>
#import <math.h>
#import "FNVDisplay.h"
#import "FNVSurface.h"
#include "FNVKeyMap.h"
#include "input.h"

extern void input_mouse_pos(int32_t x, int32_t y);
// Defined by shims_win.c; the window delegate reports AppKit activation changes here. Kept as a
// local declaration because vendor headers are a cached build input.
extern void host_set_window_focused(int focused);

static NSWindow *game_window;
static CAMetalLayer *game_layer;
static int fullscreen_transition;

static void smr_sync_drawable(void);

static int smr_env_on(const char *name) {
    const char *value = getenv(name);
    return value && value[0] && strcmp(value, "0") != 0;
}

static NSScreen *smr_target_screen(void) {
    return game_window.screen ?: NSScreen.mainScreen ?: NSScreen.screens.firstObject;
}

// Pixel size macOS presents this screen at. In full screen the drawable is exactly this size, so
// it is the "native" resolution for 1:1 rendering (on scaled Retina modes it is the backing size,
// not the physical panel).
static CGFloat smr_screen_scale(NSScreen *screen);
static CGSize smr_screen_pixels(NSScreen *screen) {
    CGDirectDisplayID did = CGMainDisplayID();
    if (screen) {
        NSNumber *num = screen.deviceDescription[@"NSScreenNumber"];
        if (num) did = (CGDirectDisplayID)num.unsignedIntValue;
    }
    CGDisplayModeRef mode = CGDisplayCopyDisplayMode(did);
    if (mode) {
        size_t w = CGDisplayModeGetPixelWidth(mode), h = CGDisplayModeGetPixelHeight(mode);
        CGDisplayModeRelease(mode);
        if (w >= 640 && h >= 480) return CGSizeMake((CGFloat)w, (CGFloat)h);
    }
    if (screen) {
        CGFloat scale = smr_screen_scale(screen);
        return CGSizeMake(round(screen.frame.size.width * scale), round(screen.frame.size.height * scale));
    }
    return CGSizeMake(1280, 720);
}

static CGFloat smr_screen_scale(NSScreen *screen) {
    CGFloat scale = screen ? screen.backingScaleFactor : 1.0;
    return scale > 0 ? scale : 1.0;
}

// The D3D9 shim reports fnv_display_width/height as the adapter's desktop mode, and the guest
// creates its device with a 0x0 backbuffer (so that fallback decides the render resolution).
// Publishing the panel size here is what makes the guest render natively instead of 1280x720.
// SMR_RENDER_SCALE=50..100 renders smaller and lets MetalFX/bilinear scale to the panel.
static void smr_configure_display(void) {
    if (!smr_env_on("SMR_NATIVE_RES")) return;
    NSScreen *screen = smr_target_screen();
    CGSize px = smr_screen_pixels(screen);
    int pct = 100;
    if (getenv("SMR_RENDER_SCALE")) {
        pct = atoi(getenv("SMR_RENDER_SCALE"));
        if (pct < 50) pct = 50;
        if (pct > 100) pct = 100;
    }
    fnv_display_configure_scaled((unsigned)px.width, (unsigned)px.height, (unsigned)pct);
    int hz = 60;
    if (screen && [screen respondsToSelector:@selector(maximumFramesPerSecond)])
        hz = (int)screen.maximumFramesPerSecond;
    if (hz <= 0) hz = 60;
    fnv_display_set_refresh(hz);
    fprintf(stderr, "[smr-window] display %ux%u px, render %ux%u (%d%%), %d Hz%s\n",
            (unsigned)px.width, (unsigned)px.height, fnv_display_width(), fnv_display_height(),
            pct, hz, screen && screen.safeAreaInsets.top > 0 ? " (notch)" : "");
}

@interface SMRMetalView : NSView
@end

@implementation SMRMetalView
- (BOOL)acceptsFirstResponder { return YES; }
- (BOOL)wantsUpdateLayer { return YES; }
- (void)viewDidChangeBackingProperties {
    [super viewDidChangeBackingProperties];
    smr_sync_drawable();
}
- (void)setFrameSize:(NSSize)size {
    [super setFrameSize:size];
    smr_sync_drawable();
}
@end

@interface SMRGameWindow : NSWindow <NSWindowDelegate> {
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

// Map window cursor points into the guest backbuffer's active aspect-fit rectangle.
- (void)updateMousePos:(NSEvent *)event {
    NSView *view = self.contentView;
    NSRect bounds = view.bounds;
    double vw = bounds.size.width, vh = bounds.size.height;
    if (vw <= 0.0 || vh <= 0.0) return;
    unsigned gw = fnv_client_width(), gh = fnv_client_height();
    if (!gw) gw = 1024;
    if (!gh) gh = 768;
    double sa = (double)gw / (double)gh, da = vw / vh;
    double fw = vw, fh = vh;
    if (sa > da) fh = vw / sa;
    else if (sa < da) fw = vh * sa;
    double ox = (vw - fw) * 0.5, oy = (vh - fh) * 0.5;
    NSPoint pt = [view convertPoint:event.locationInWindow fromView:nil];
    double lx = pt.x, ly = vh - pt.y;
    double u = fw > 0.0 ? (lx - ox) / fw : 0.0;
    double v = fh > 0.0 ? (ly - oy) / fh : 0.0;
    if (u < 0.0) u = 0.0; else if (u > 1.0) u = 1.0;
    if (v < 0.0) v = 0.0; else if (v > 1.0) v = 1.0;
    int32_t gx = (int32_t)floor(u * (double)gw);
    int32_t gy = (int32_t)floor(v * (double)gh);
    if (gx < 0) gx = 0; else if (gx >= (int32_t)gw) gx = (int32_t)gw - 1;
    if (gy < 0) gy = 0; else if (gy >= (int32_t)gh) gy = (int32_t)gh - 1;
    input_mouse_pos(gx, gy);
}

- (void)sendEvent:(NSEvent *)event {
    if (event.type == NSEventTypeKeyDown || event.type == NSEventTypeKeyUp) {
        NSEventModifierFlags mods = event.modifierFlags;
        NSUInteger code = event.keyCode;
        BOOL down = event.type == NSEventTypeKeyDown;
        // Fullscreen toggles (also reachable from the View menu): Cmd+F, Ctrl+Cmd+F,
        // Option+Return / Option+Enter. These never reach the guest.
        if (down && (((mods & NSEventModifierFlagCommand) && code == 3 /* F */) ||
                     ((mods & NSEventModifierFlagOption) && (code == 36 /* Return */ || code == 76 /* keypad Enter */)))) {
            [self toggleFullScreen:nil];
            return;
        }
        if (code < sizeof(mac2dik) && mac2dik[code] &&
            ((!down && guest_keys[code]) ||
             (down && !(mods & NSEventModifierFlagCommand)))) {
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
            [self updateMousePos:event];
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
            [self updateMousePos:event];
            guest_buttons[button] = NO;
            input_mouse_button((int)button, 0);
        }
        break;
    }
    case NSEventTypeMouseMoved:
        if (self.isKeyWindow && [self containsMouseEvent:event]) {
            [self updateMousePos:event];
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
    case NSEventTypeLeftMouseDragged:
    case NSEventTypeRightMouseDragged:
    case NSEventTypeOtherMouseDragged:
        if (self.isKeyWindow) {
            [self updateMousePos:event];
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
    case NSEventTypeScrollWheel:
        if (self.isKeyWindow && [self containsMouseEvent:event]) {
            double dy = event.hasPreciseScrollingDeltas ? event.scrollingDeltaY * 4.0
                                                        : event.scrollingDeltaY * 120.0;
            int dz = (int)llround(dy);
            if (dz)
                input_mouse_wheel(dz);
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

// The layer must always present at the window's real device-pixel size. The Metal presenter
// renders the guest backbuffer into that drawable with aspect-fit letterboxing, so any window
// size (live resize, fullscreen, moving to another display) stays sharp and unstretched.
- (void)windowDidResize:(NSNotification *)notification { (void)notification; smr_sync_drawable(); }
- (void)windowDidBecomeKey:(NSNotification *)notification { (void)notification; host_set_window_focused(1); }
- (void)windowDidResignKey:(NSNotification *)notification { (void)notification; host_set_window_focused(0); }
- (void)windowDidChangeBackingProperties:(NSNotification *)notification { (void)notification; smr_sync_drawable(); }
- (void)windowDidMove:(NSNotification *)notification { (void)notification; smr_sync_drawable(); }
- (void)windowDidEnterFullScreen:(NSNotification *)notification {
    (void)notification;
    fullscreen_transition = 0;
    smr_sync_drawable();
    fprintf(stderr, "[smr-window] entered full screen, drawable %.0f x %.0f px\n",
            game_layer.drawableSize.width, game_layer.drawableSize.height);
}
- (void)windowDidExitFullScreen:(NSNotification *)notification {
    (void)notification;
    fullscreen_transition = 0;
    smr_sync_drawable();
    fprintf(stderr, "[smr-window] left full screen, drawable %.0f x %.0f px\n",
            game_layer.drawableSize.width, game_layer.drawableSize.height);
}
@end

static void smr_sync_drawable(void) {
    if (!game_window || !game_layer) return;
    NSView *view = game_window.contentView;
    CGFloat scale = game_window.backingScaleFactor;
    if (scale <= 0) scale = 1.0;
    game_layer.contentsScale = scale;
    CGSize px = CGSizeMake(round(view.bounds.size.width * scale), round(view.bounds.size.height * scale));
    if (px.width < 1) px.width = 1;
    if (px.height < 1) px.height = 1;
    if (game_layer.drawableSize.width != px.width || game_layer.drawableSize.height != px.height)
        game_layer.drawableSize = px;
}

// The guest picks its own resolution (Reset 1024x768 for this game). Keep the window inside the
// screen it is already on, preserving the requested aspect: the Metal presenter letterboxes any
// remaining difference instead of stretching.
static NSSize smr_fitted_content_size(NSSize wanted) {
    if (wanted.width < 1 || wanted.height < 1) return NSMakeSize(640, 480);
    NSScreen *screen = game_window.screen ?: NSScreen.mainScreen ?: NSScreen.screens.firstObject;
    if (!screen) return wanted;
    NSRect vis = screen.visibleFrame;
    CGFloat maxW = vis.size.width * 0.95, maxH = vis.size.height * 0.95;
    CGFloat fit = MIN(1.0, MIN(maxW / wanted.width, maxH / wanted.height));
    if (fit <= 0) fit = 1.0;
    return NSMakeSize(floor(wanted.width * fit), floor(wanted.height * fit));
}

static void smr_keep_on_screen(void) {
    NSScreen *screen = game_window.screen ?: NSScreen.mainScreen ?: NSScreen.screens.firstObject;
    if (!screen) return;
    NSRect vis = screen.visibleFrame;
    NSRect frame = game_window.frame;
    if (frame.origin.x < vis.origin.x) frame.origin.x = vis.origin.x;
    if (frame.origin.y < vis.origin.y) frame.origin.y = vis.origin.y;
    if (frame.origin.x + frame.size.width > NSMaxX(vis))
        frame.origin.x = NSMaxX(vis) - frame.size.width;
    if (frame.origin.y + frame.size.height > NSMaxY(vis))
        frame.origin.y = NSMaxY(vis) - frame.size.height;
    [game_window setFrameOrigin:frame.origin];
}

int fnv_run_game(int argc, char **argv);

CAMetalLayer *fnv_surface(id<MTLDevice> device, CGSize size) {
    dispatch_sync(dispatch_get_main_queue(), ^{
        NSScreen *screen = NSScreen.mainScreen ?: NSScreen.screens.firstObject;
        // The renderer passes the swap chain's pixel size; AppKit sizes are points. Dividing by
        // the backing scale keeps a Retina window from being created twice as large as the panel.
        CGFloat scale = smr_screen_scale(screen);
        NSSize wanted = NSMakeSize(size.width > 0 ? size.width / scale : 1280,
                                   size.height > 0 ? size.height / scale : 720);
        NSSize content = smr_fitted_content_size(wanted);
        NSRect bounds = NSMakeRect(0, 0, content.width, content.height);
        game_window = [[SMRGameWindow alloc] initWithContentRect:bounds
            styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable |
                      NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable
              backing:NSBackingStoreBuffered defer:NO];
        game_window.title = @"Shoot Too Many Robots";
        game_window.delegate = (id<NSWindowDelegate>)game_window;
        game_window.collectionBehavior = NSWindowCollectionBehaviorFullScreenPrimary;
        game_window.backgroundColor = NSColor.blackColor;
        game_window.acceptsMouseMovedEvents = YES;
        game_window.releasedWhenClosed = NO;

        SMRMetalView *view = [[SMRMetalView alloc] initWithFrame:bounds];
        view.wantsLayer = YES;
        game_window.contentView = view;

        game_layer = [CAMetalLayer layer];
        game_layer.device = device;
        game_layer.pixelFormat = MTLPixelFormatBGRA8Unorm;
        game_layer.opaque = YES;
        game_layer.contentsGravity = kCAGravityResize;
        game_layer.backgroundColor = CGColorGetConstantColor(kCGColorBlack);
        view.layer = game_layer;
        smr_sync_drawable();

        if (screen) {
            NSRect vis = screen.visibleFrame;
            [game_window setFrameOrigin:NSMakePoint(
                vis.origin.x + (vis.size.width - game_window.frame.size.width) * 0.5,
                vis.origin.y + (vis.size.height - game_window.frame.size.height) * 0.5)];
        } else {
            [game_window center];
        }
        [game_window makeKeyAndOrderFront:nil];
        [game_window makeFirstResponder:view];
        [NSApp activateIgnoringOtherApps:YES];
        // Demo/benchmark escape hatch: the guest may have saved Fullscreen=False, but the host can
        // still open in full screen. Delayed so the game's boot-time windowed style call is done.
        if (smr_env_on("SMR_FORCE_FULLSCREEN")) {
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(1.5 * NSEC_PER_SEC)),
                           dispatch_get_main_queue(), ^{ fnv_set_fullscreen(1); });
        }
        fprintf(stderr, "[smr-window] opened %.0f x %.0f points, drawable %.0f x %.0f px\n",
                content.width, content.height, game_layer.drawableSize.width, game_layer.drawableSize.height);
    });
    return game_layer;
}

void fnv_resize_surface(CGSize size) {
    if (size.width < 1 || size.height < 1) return;
    dispatch_async(dispatch_get_main_queue(), ^{
        if (!game_window || !game_layer) return;
        if (!(game_window.styleMask & NSWindowStyleMaskFullScreen)) {
            CGFloat scale = smr_screen_scale(smr_target_screen());
            NSSize content = smr_fitted_content_size(NSMakeSize(size.width / scale, size.height / scale));
            [game_window setContentSize:content];
            smr_keep_on_screen();
        }
        smr_sync_drawable();
    });
}

void fnv_set_fullscreen(int fullscreen) {
    dispatch_async(dispatch_get_main_queue(), ^{
        if (!game_window) return;
        BOOL is_fullscreen = (game_window.styleMask & NSWindowStyleMaskFullScreen) != 0;
        if ((fullscreen != 0) == (is_fullscreen != 0) || fullscreen_transition) return;
        // The game restyles its window (WS_POPUP + SetWindowPos) around a device Reset; mapping
        // that onto the real window is what turns the guest's "full screen" into full screen.
        fprintf(stderr, "[smr-window] full screen request %s\n", fullscreen ? "enter" : "leave");
        fullscreen_transition = 1;
        [game_window toggleFullScreen:nil];
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

static void smr_install_menu(void) {
    NSMenu *bar = [NSMenu new];
    NSMenuItem *app_item = [NSMenuItem new];
    [bar addItem:app_item];
    NSMenu *app_menu = [[NSMenu alloc] initWithTitle:@"Shoot Too Many Robots"];
    [app_menu addItemWithTitle:@"Hide Shoot Too Many Robots" action:@selector(hide:) keyEquivalent:@"h"];
    [app_menu addItem:[NSMenuItem separatorItem]];
    [app_menu addItemWithTitle:@"Quit Shoot Too Many Robots" action:@selector(terminate:) keyEquivalent:@"q"];
    app_item.submenu = app_menu;

    NSMenuItem *view_item = [NSMenuItem new];
    [bar addItem:view_item];
    NSMenu *view_menu = [[NSMenu alloc] initWithTitle:@"View"];
    NSMenuItem *fullscreen = [view_menu addItemWithTitle:@"Toggle Full Screen"
                                                  action:@selector(toggleFullScreen:)
                                           keyEquivalent:@"f"];
    fullscreen.keyEquivalentModifierMask = NSEventModifierFlagCommand;
    view_item.submenu = view_menu;
    NSApp.mainMenu = bar;
}

int smr_run_windowed(int argc, char **argv) {
    @autoreleasepool { smr_configure_display(); }
    if (getenv("FNV_HEADLESS")) {
        return fnv_run_game(argc, argv);
    }
    @autoreleasepool {
        NSApplication *app = [NSApplication sharedApplication];
        SMRAppDelegate *delegate = [SMRAppDelegate new];
        app.delegate = delegate;
        [app setActivationPolicy:NSApplicationActivationPolicyRegular];
        smr_install_menu();
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
