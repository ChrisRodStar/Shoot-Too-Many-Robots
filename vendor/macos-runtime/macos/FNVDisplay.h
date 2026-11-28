#pragma once
#include <stdint.h>

void fnv_display_configure(unsigned native_width, unsigned native_height);
void fnv_display_configure_scaled(unsigned native_width, unsigned native_height, unsigned scale_pct);
void fnv_display_set_refresh(int hz);
unsigned fnv_display_width(void);
unsigned fnv_display_height(void);
unsigned fnv_output_width(void);
unsigned fnv_output_height(void);
void fnv_display_client(unsigned width, unsigned height);
unsigned fnv_client_width(void);
unsigned fnv_client_height(void);
const char *fnv_display_adapter_description(void);
