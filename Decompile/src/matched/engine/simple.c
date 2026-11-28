/*
 * First byte-verified matches (MSVC 2008 SP1, 15.00.30729.01).
 *
 * These four functions are small on purpose: they prove the compiler,
 * flags, object reader and comparator before real reconstruction starts.
 *
 *   00401050  33 c0 c2 10 00        xor eax,eax ; ret 0x10
 *   00941900  8b 44 24 04 c3        mov eax,[esp+4] ; ret
 *   00403740  33 c0 c3              xor eax,eax ; ret
 *   0049eb30  b8 01 00 00 00 c3     mov eax,1 ; ret
 *
 * The names are the decompiler placeholders, not original symbols. They are
 * kept so the object symbols map back to the reference tree's addresses.
 */

int __stdcall FUN_00401050(int a, int b, int c, int d)
{
    (void)a; (void)b; (void)c; (void)d;
    return 0;
}

int __cdecl FUN_00941900(int value)
{
    return value;
}

int __cdecl FUN_00403740(void)
{
    return 0;
}

int __cdecl FUN_0049eb30(void)
{
    return 1;
}
