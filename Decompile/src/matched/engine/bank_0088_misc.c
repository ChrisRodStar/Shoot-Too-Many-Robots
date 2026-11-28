/*
 * bank_0088 misc leaf: 0x008a8cb0, 38 bytes.
 * cdecl: reads a field, writes an out-param and a byte flag.
 * Verified with MSVC 2008 SP1 /O2 /MD. Source statement order matters: the
 * immediate store to *out before the null test is what the original emits.
 */
int FUN_008a8cb0(char *s, int *out)
{
    int r;
    *out = 0;
    r = 0;
    if (s) {
        r = *(int *)(s + 4);
        *out = *(int *)(s + 0xc);
        s[0x211] = 0;
    }
    return r;
}
