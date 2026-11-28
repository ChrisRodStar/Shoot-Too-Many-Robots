/*
 * 00401000  27 bytes
 *   51                 push ecx
 *   ff 15 <rand>       call dword ptr [__imp__rand]
 *   89 04 24           mov [esp], eax
 *   db 04 24           fild dword ptr [esp]
 *   dc 0d <2^-15>      fmul qword ptr [__real@3f00000000000000]
 *   d9 1c 24           fstp dword ptr [esp]
 *   d9 04 24           fld dword ptr [esp]
 *   59                 pop ecx
 *   c3                 ret
 *
 * Verified byte-identical with MSVC 2008 SP1 /O2 /MD.
 * The two relocations resolve to the MSVCR90 rand IAT slot and the double
 * constant at 0x009ce1f8.
 */
#include <stdlib.h>

float FUN_00401000(void)
{
    return (float)(rand() * 3.0517578125e-05);
}
