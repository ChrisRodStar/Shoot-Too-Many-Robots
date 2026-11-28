/*
 * 32-bit field accessors: each original function is
 *   mov eax,[esp+4] ; mov eax,[eax+disp] ; ret
 * so the C is a plain int read at a byte offset. No calls, no constants,
 * no relocations. Verified byte-identical with MSVC 2008 SP1 /O2 /MD.
 *
 * The return type is the machine-level 32-bit value; a symbol may really be
 * an int, a pointer, or a float bit pattern. Types are reconstructed later.
 */
int FUN_007e9730(int *p) { return *(int *)((char *)p + 0x20); }
int FUN_008155c0(int *p) { return *(int *)((char *)p + 0x2c); }
int FUN_008163b0(int *p) { return *(int *)((char *)p + 0x34); }
int FUN_008163c0(int *p) { return *(int *)((char *)p + 0x38); }
int FUN_008457b0(int *p) { return *(int *)((char *)p + 0x1c); }
int FUN_0084acb0(int *p) { return *p; }
int FUN_0084bf20(int *p) { return *(int *)((char *)p + 0x58); }
int FUN_0084f8b0(int *p) { return *(int *)((char *)p + 0x8); }
int FUN_00859950(int *p) { return *(int *)((char *)p + 0x30); }
int FUN_008599f0(int *p) { return *(int *)((char *)p + 0x3c); }
int FUN_00859a00(int *p) { return *(int *)((char *)p + 0x40); }
int FUN_0085b520(int *p) { return *(int *)((char *)p + 0x4); }
int FUN_0085b5b0(int *p) { return *(int *)((char *)p + 0x14); }
int FUN_0086c7d0(int *p) { return *(int *)((char *)p + 0x18); }
int FUN_0086d5b0(int *p) { return *(int *)((char *)p + 0xc); }
int FUN_0086f190(int *p) { return *(int *)((char *)p + 0x10); }
int FUN_00876520(int *p) { return *(int *)((char *)p + 0x68); }
int FUN_0092b1a0(int *p) { return *(int *)((char *)p + 0x60); }
int FUN_009613e0(int *p) { return *(int *)((char *)p + 0xec); }
