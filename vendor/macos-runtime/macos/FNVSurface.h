#pragma once
#import <Metal/Metal.h>
#import <QuartzCore/CAMetalLayer.h>

CAMetalLayer *fnv_surface(id<MTLDevice> device, CGSize size);
void fnv_resize_surface(CGSize size);
// Ask the host window to enter (1) or leave (0) full screen. Safe to call from the guest thread;
// the app is applied on the main queue.
void fnv_set_fullscreen(int fullscreen);
void fnv_wait_active(void);
