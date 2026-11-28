/*
 * Type vocabulary used by Ghidra's decompiler output.
 *
 * The exported tree is a reference decompilation, not yet a building unit, so
 * these are intentionally permissive. When a translation unit is promoted to a
 * matching build, replace them with the original MSVC 2008 declarations and
 * the recovered struct definitions.
 */
#ifndef SMR_GHIDRA_TYPES_H
#define SMR_GHIDRA_TYPES_H

#include <stdint.h>
#include <stddef.h>

typedef uint8_t  undefined;
typedef uint8_t  undefined1;
typedef uint16_t undefined2;
typedef uint32_t undefined3;
typedef uint32_t undefined4;
typedef uint64_t undefined5;
typedef uint64_t undefined6;
typedef uint64_t undefined7;
typedef uint64_t undefined8;

typedef uint8_t  byte;
typedef uint16_t word;
typedef uint32_t dword;
typedef uint64_t qword;

typedef uint8_t  uchar;
typedef uint16_t ushort;
typedef uint32_t uint;
typedef uint64_t ulong;
typedef int64_t  longlong;
typedef uint64_t ulonglong;

/* x87 80-bit extended value.  The host's long double may be narrower; this is
 * only a reading aid until the function is rebuilt with MSVC. */
typedef long double float10;

/* Ghidra's "unknown code" pointer. */
typedef void code;

#ifndef __cdecl
#define __cdecl
#endif
#ifndef __stdcall
#define __stdcall
#endif
#ifndef __thiscall
#define __thiscall
#endif
#ifndef __fastcall
#define __fastcall
#endif
#ifndef __noreturn
#define __noreturn
#endif

#endif /* SMR_GHIDRA_TYPES_H */
