/*
 * bank_0088: small thiscall methods (MSVC 2008 SP1, /O2 /MD /TP).
 *
 * The original functions have `this` in ECX and either return `this` (EAX=ECX)
 * or take two stack arguments and use `ret 8`. The class names below are
 * anonymous placeholders except NxEffectorDesc, which came from RTTI; only the
 * layout and the emitted code are verified.
 */

struct Anon_8b0a40 { int f0, f1, f2, f3, f4, f5; Anon_8b0a40(); };
Anon_8b0a40::Anon_8b0a40() { f0=0; f1=0; f2=0; f3=0; f4=0; f5=0; }

struct Anon_8b10e0 { short f0, f1; int pad; int f2; Anon_8b10e0(); };
Anon_8b10e0::Anon_8b10e0() { f0=0; f1=0; f2=0; }

struct Anon_8b0230 { int f0; float f1; int f2; Anon_8b0230(); };
Anon_8b0230::Anon_8b0230() { f0=0; f1=0.0f; f2=0; }

struct Anon_8b0be0 { short f0, f1; float f2, f3; int f4; Anon_8b0be0(); };
Anon_8b0be0::Anon_8b0be0() { f0=0; f1=0; f2=0.0f; f3=0.0f; f4=0; }

struct Anon_8b2e00 { float f0, f1, f2, f3, f4; int f5; Anon_8b2e00(); };
Anon_8b2e00::Anon_8b2e00() { f0=0.0f; f1=0.0f; f2=0.0f; f3=0.0f; f4=0.0f; f5=0; }

struct NxEffectorDesc { int a, b, c, d; void clear(); };
void NxEffectorDesc::clear() { c=0; d=0; }

struct Anon_8b1510 { int f0, f1, f2, f3, f4; void copyFrom(const Anon_8b1510&, int); };
void Anon_8b1510::copyFrom(const Anon_8b1510& o, int)
{ f0=o.f0; f1=o.f1; f2=o.f2; f3=o.f3; f4=o.f4; }

struct Anon_8b10a0 { int f0, f1, f2, f3; void copyFrom(const Anon_8b10a0&, int); };
void Anon_8b10a0::copyFrom(const Anon_8b10a0& o, int)
{ f0=o.f0; f1=o.f1; f2=o.f2; f3=o.f3; }

struct Anon_8b10c0 { int f0, f1, f2, f3; void copyTo(Anon_8b10c0&, int); };
void Anon_8b10c0::copyTo(Anon_8b10c0& o, int)
{ o.f0=f0; o.f1=f1; o.f2=f2; o.f3=f3; }

struct Anon_8b15e0 { float f0, f1, f2; void copyFrom(const Anon_8b15e0&, int); };
void Anon_8b15e0::copyFrom(const Anon_8b15e0& o, int)
{ f0=o.f0; f1=o.f1; f2=o.f2; }

/* Two cdecl wrappers that call an unreconstructed C++ method. The method
 * symbols are bound to their original addresses in config/matched.json. */
struct C {
    ~C();
    int g(int, int);
    int g(C *, int, int);
};
void del(void *);
void f(C *p) { if (p) { p->~C(); del(p); } }
int FUN_008a8ba0(C *p, int a, int b) { int r = 0; if (p) r = p->g(a, b); return r; }
int FUN_008a8ab0(C *a1, int a2, int a3, C *a4)
{ int r = 0; if (a4) r = a4->g(a1, a2, a3); return r; }

/* Four field-copy + method-call setters. Distinct placeholder classes keep
 * each call target's symbol unique for the relocation map. */
struct A1 { char pad[0x18]; int f18; };
struct B1 { void method(void *c, A1 *a); };
struct C1 { char pad[0x20]; int f20; void f(A1 *a, B1 *b); };
void C1::f(A1 *a, B1 *b) { f20 = a->f18; b->method(this, a); }

struct A2 { char pad[0x18]; int f18; };
struct B2 { void method(A2 *a, void *c); };
struct C2 { char pad[0x20]; int f20; void f(A2 *a, B2 *b); };
void C2::f(A2 *a, B2 *b) { a->f18 = f20; b->method(a, this); }

struct A3 { char pad[0x18]; int f18; };
struct B3 { void method(void *c, A3 *a); };
struct C3 { char pad[0x18]; int f18; void f(A3 *a, B3 *b); };
void C3::f(A3 *a, B3 *b) { f18 = a->f18; b->method(this, a); }

struct A4 { char pad[0x18]; int f18; };
struct B4 { void method(A4 *a, void *c); };
struct C4 { char pad[0x18]; int f18; void f(A4 *a, B4 *b); };
void C4::f(A4 *a, B4 *b) { a->f18 = f18; b->method(a, this); }

/* Float-field copies followed by a tail call to the shared routine at
 * 0x008b1fa0. The class names differ only to keep relocation symbols unique. */
struct FA1 { char pad[0x6c]; float f6c; };
struct FC1 { char pad[0x70]; float f70; void base(FA1 *); void f(FA1 *a); };
void FC1::f(FA1 *a) { f70 = a->f6c; base(a); }

struct FA3 { char pad[0x6c]; float f6c, f70, f74; };
struct FC3 { char pad[0x70]; float f70, f74, f78; void base(FA3 *); void f(FA3 *a); };
void FC3::f(FA3 *a) { f70 = a->f6c; f74 = a->f70; f78 = a->f74; base(a); }

struct FA4 { char pad[0x6c]; float f6c, f70, f74, f78; };
struct FC4 { char pad[0x70]; float f70, f74, f78, f7c; void base(FA4 *); void f(FA4 *a); };
void FC4::f(FA4 *a) { f70 = a->f6c; f74 = a->f70; f78 = a->f74; f7c = a->f78; base(a); }

struct FA2 { char pad[0x6c]; float f6c, f70; int f74; };
struct FC2 { char pad[0x70]; float f70, f74; int f78; void base(FA2 *); void f(FA2 *a); };
void FC2::f(FA2 *a) { f70 = a->f6c; f74 = a->f70; f78 = a->f74; base(a); }

/* Method call followed by a float copy. */
struct CCA { char pad[0x6c]; float f6c; };
struct CC { char pad[0x70]; float f70; void g(CCA *, int); void f(CCA *, int); };
void CC::f(CCA *a, int x) { g(a, x); a->f6c = f70; }
