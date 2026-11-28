/*
 * 149 pure tail-call thunks: each original function is a single
 *   E9 <rel32>   jmp target
 *
 * They are ABI passthroughs, not reconstructed signatures. The C declares
 * each as void(void) so MSVC emits a bare tail jump; arguments and registers
 * pass through untouched. Byte-verified with MSVC 2008 SP1 /O2 /MD.
 *
 * One further thunk (0x00799990 -> 0x006eeae0 -> 0x006ee940) is excluded:
 * with both ends in this same object the compiler merges the chain and
 * redirects the first call, so it needs its own translation unit.
 */
void FUN_004039f0(void);
void FUN_00408d60(void);
void FUN_00411140(void);
void FUN_00415970(void);
void FUN_00416690(void);
void FUN_0041a2d0(void);
void FUN_0041ed40(void);
void FUN_00428e50(void);
void FUN_0044b990(void);
void FUN_0048fa30(void);
void FUN_0049a500(void);
void FUN_004f0650(void);
void FUN_00517930(void);
void FUN_00528870(void);
void FUN_0055bea0(void);
void FUN_005607d0(void);
void FUN_005607f0(void);
void FUN_00568120(void);
void FUN_00595bd0(void);
void FUN_005ac010(void);
void FUN_005b41d0(void);
void FUN_005b47b0(void);
void FUN_005bc1c0(void);
void FUN_005bccf0(void);
void FUN_005bf020(void);
void FUN_005bf660(void);
void FUN_005c19a0(void);
void FUN_005c5cf0(void);
void FUN_005d4c20(void);
void FUN_005f39d0(void);
void FUN_00608ea0(void);
void FUN_0060bf10(void);
void FUN_0061aad0(void);
void FUN_0063b750(void);
void FUN_0063b7d0(void);
void FUN_00640ad0(void);
void FUN_0064a990(void);
void FUN_00658800(void);
void FUN_0065f9e0(void);
void FUN_006780c0(void);
void FUN_00691620(void);
void FUN_006917e0(void);
void FUN_00691b80(void);
void FUN_006929c0(void);
void FUN_00696610(void);
void FUN_006967e0(void);
void FUN_006adef0(void);
void FUN_006bbb80(void);
void FUN_006ed120(void);
void FUN_006ee4e0(void);
void FUN_006ee940(void);
void FUN_006eeb40(void);
void FUN_006f3500(void);
void FUN_006f3950(void);
void FUN_006f3a10(void);
void FUN_006f4d30(void);
void FUN_006f5040(void);
void FUN_00713380(void);
void FUN_0071c470(void);
void FUN_0071c750(void);
void FUN_0071cb20(void);
void FUN_00720400(void);
void FUN_007271a0(void);
void FUN_00727280(void);
void FUN_00730110(void);
void FUN_00732c50(void);
void FUN_007404b0(void);
void FUN_007432f0(void);
void FUN_00747f00(void);
void FUN_0074c080(void);
void FUN_0074ff50(void);
void FUN_00754570(void);
void FUN_00756390(void);
void FUN_0075d390(void);
void FUN_00760ac0(void);
void FUN_00760ad0(void);
void FUN_00787740(void);
void FUN_00792b00(void);
void FUN_007ae690(void);
void FUN_007b4c90(void);
void FUN_007ef800(void);
void FUN_007ef8f0(void);
void FUN_007fe580(void);
void FUN_0081ffe0(void);
void FUN_00820e60(void);
void FUN_00821200(void);
void FUN_008214a0(void);
void FUN_008225d0(void);
void FUN_00822710(void);
void FUN_0082ebe0(void);
void FUN_0083e178(void);
void FUN_0083e29e(void);
void FUN_00843630(void);
void FUN_008459e0(void);
void FUN_00845c20(void);
void FUN_00845c50(void);
void FUN_0084f6a0(void);
void FUN_0084f7f0(void);
void FUN_0084f820(void);
void FUN_0084fbe0(void);
void FUN_008586e0(void);
void FUN_0085e560(void);
void FUN_0085e5a0(void);
void FUN_0086b8c0(void);
void FUN_0086bd00(void);
void FUN_0087aa10(void);
void FUN_0087aa70(void);
void FUN_0087aaf0(void);
void FUN_0087ab50(void);
void FUN_0088b820(void);
void FUN_008b2f80(void);
void FUN_008b3030(void);
void FUN_008e5da0(void);
void FUN_008fac40(void);
void FUN_008fe710(void);
void FUN_009092d0(void);
void FUN_0091ce70(void);
void FUN_0092c630(void);
void FUN_0092c660(void);
void FUN_0092c680(void);
void FUN_0092ea70(void);
void FUN_009354b0(void);
void FUN_009416e0(void);
void FUN_00962d50(void);

void FUN_00401130(void) { FUN_005d4c20(); }
void FUN_00404730(void) { FUN_004039f0(); }
void FUN_004092a0(void) { FUN_00408d60(); }
void FUN_0041ee90(void) { FUN_0041ed40(); }
void FUN_00424050(void) { FUN_00416690(); }
void FUN_00425d90(void) { FUN_0041a2d0(); }
void FUN_00428a50(void) { FUN_00411140(); }
void FUN_00428eb0(void) { FUN_00415970(); }
void FUN_0042ac50(void) { FUN_00428e50(); }
void FUN_00482820(void) { FUN_004f0650(); }
void FUN_004919f0(void) { FUN_0048fa30(); }
void FUN_00498ef0(void) { FUN_0049a500(); }
void FUN_004dc270(void) { FUN_0044b990(); }
void FUN_004f99c0(void) { FUN_00595bd0(); }
void FUN_00517d30(void) { FUN_00517930(); }
void FUN_00528af0(void) { FUN_00528870(); }
void FUN_0054ee20(void) { FUN_0055bea0(); }
void FUN_0055d3c0(void) { FUN_005607d0(); }
void FUN_0055d3d0(void) { FUN_005607f0(); }
void FUN_0055d800(void) { FUN_00568120(); }
void FUN_0056a550(void) { FUN_005607d0(); }
void FUN_0057f090(void) { FUN_00760ac0(); }
void FUN_00580b10(void) { FUN_005b41d0(); }
void FUN_00581ae0(void) { FUN_007432f0(); }
void FUN_0059fbe0(void) { FUN_00760ad0(); }
void FUN_0059fc00(void) { FUN_00760ac0(); }
void FUN_005a19a0(void) { FUN_005c5cf0(); }
void FUN_005a1ed0(void) { FUN_005c5cf0(); }
void FUN_005abed0(void) { FUN_00760ac0(); }
void FUN_005ac270(void) { FUN_005ac010(); }
void FUN_005ac280(void) { FUN_005ac010(); }
void FUN_005aca80(void) { FUN_00760ad0(); }
void FUN_005aca90(void) { FUN_00760ac0(); }
void FUN_005acc60(void) { FUN_00760ac0(); }
void FUN_005acec0(void) { FUN_00756390(); }
void FUN_005adf10(void) { FUN_00760ac0(); }
void FUN_005b49d0(void) { FUN_005b47b0(); }
void FUN_005bc430(void) { FUN_005bc1c0(); }
void FUN_005bd0a0(void) { FUN_005bccf0(); }
void FUN_005bd0b0(void) { FUN_005bccf0(); }
void FUN_005bf360(void) { FUN_005bf020(); }
void FUN_005bf370(void) { FUN_005bf020(); }
void FUN_005bf7d0(void) { FUN_005bf660(); }
void FUN_005bf7e0(void) { FUN_005bf660(); }
void FUN_005bf800(void) { FUN_005bf660(); }
void FUN_005c1ac0(void) { FUN_005c19a0(); }
void FUN_005dca40(void) { FUN_0083e178(); }
void FUN_005df560(void) { FUN_00608ea0(); }
void FUN_005e35b0(void) { FUN_0063b750(); }
void FUN_005e35c0(void) { FUN_0063b7d0(); }
void FUN_005f3af0(void) { FUN_005f39d0(); }
void FUN_005faa60(void) { FUN_0060bf10(); }
void FUN_0061ab40(void) { FUN_0061aad0(); }
void FUN_00640b40(void) { FUN_00640ad0(); }
void FUN_0064aa00(void) { FUN_0064a990(); }
void FUN_00658a00(void) { FUN_00658800(); }
void FUN_0065fa50(void) { FUN_0065f9e0(); }
void FUN_00678700(void) { FUN_006780c0(); }
void FUN_00692570(void) { FUN_00691620(); }
void FUN_00692580(void) { FUN_006917e0(); }
void FUN_00692590(void) { FUN_00691b80(); }
void FUN_006931a0(void) { FUN_006929c0(); }
void FUN_006969a0(void) { FUN_00696610(); }
void FUN_006969e0(void) { FUN_006967e0(); }
void FUN_006af8e0(void) { FUN_006adef0(); }
void FUN_006bbdb0(void) { FUN_006bbb80(); }
void FUN_006ed1f0(void) { FUN_006ed120(); }
void FUN_006eeae0(void) { FUN_006ee940(); }
void FUN_006eeba0(void) { FUN_006eeb40(); }
void FUN_006ef9e0(void) { FUN_006ee940(); }
void FUN_006f3590(void) { FUN_006f3500(); }
void FUN_006f3a00(void) { FUN_006f3950(); }
void FUN_006f3a80(void) { FUN_006f3a10(); }
void FUN_006f4de0(void) { FUN_006f4d30(); }
void FUN_006f5220(void) { FUN_006f5040(); }
void FUN_007134c0(void) { FUN_00713380(); }
void FUN_0071c740(void) { FUN_0071c470(); }
void FUN_0071cc10(void) { FUN_0071c750(); }
void FUN_0071cc20(void) { FUN_0071cb20(); }
void FUN_00722cc0(void) { FUN_008fe710(); }
void FUN_00724f60(void) { FUN_008214a0(); }
void FUN_00727240(void) { FUN_007271a0(); }
void FUN_007325e0(void) { FUN_00730110(); }
void FUN_00732fb0(void) { FUN_00732c50(); }
void FUN_007414a0(void) { FUN_007404b0(); }
void FUN_0074d730(void) { FUN_0074c080(); }
void FUN_00750850(void) { FUN_0074ff50(); }
void FUN_00754fd0(void) { FUN_00754570(); }
void FUN_0075d5b0(void) { FUN_0075d390(); }
void FUN_0075fab0(void) { FUN_00820e60(); }
void FUN_0075fac0(void) { FUN_0083e29e(); }
void FUN_0075fad0(void) { FUN_0083e29e(); }
void FUN_007877d0(void) { FUN_00787740(); }
void FUN_00792fb0(void) { FUN_00727280(); }
void FUN_00799910(void) { FUN_00792b00(); }
void FUN_007ab860(void) { FUN_008fac40(); }
void FUN_007ae700(void) { FUN_007ae690(); }
void FUN_007b4d60(void) { FUN_007b4c90(); }
void FUN_007ef9e0(void) { FUN_007ef800(); }
void FUN_007ef9f0(void) { FUN_007ef8f0(); }
void FUN_007fe7d0(void) { FUN_007fe580(); }
void FUN_008202d0(void) { FUN_0081ffe0(); }
void FUN_00822790(void) { FUN_00822710(); }
void FUN_008248f0(void) { FUN_00720400(); }
void FUN_0082ec50(void) { FUN_0082ebe0(); }
void FUN_00831d30(void) { FUN_008225d0(); }
void FUN_0083c150(void) { FUN_0083e29e(); }
void FUN_0083c160(void) { FUN_0083e29e(); }
void FUN_008493b0(void) { FUN_00843630(); }
void FUN_008586c0(void) { FUN_0084fbe0(); }
void FUN_008586d0(void) { FUN_0084f820(); }
void FUN_008587b0(void) { FUN_008586e0(); }
void FUN_00871710(void) { FUN_0084f6a0(); }
void FUN_00874200(void) { FUN_00845c20(); }
void FUN_0087d280(void) { FUN_0085e560(); }
void FUN_0087d350(void) { FUN_0084f7f0(); }
void FUN_0087d3a0(void) { FUN_0085e5a0(); }
void FUN_0087f280(void) { FUN_0087aa70(); }
void FUN_0087f290(void) { FUN_0087aa10(); }
void FUN_0087f2a0(void) { FUN_0087ab50(); }
void FUN_0087f2b0(void) { FUN_0087aaf0(); }
void FUN_0087f3f0(void) { FUN_00845c50(); }
void FUN_008827f0(void) { FUN_0086b8c0(); }
void FUN_00882800(void) { FUN_0086bd00(); }
void FUN_0088b970(void) { FUN_0088b820(); }
void FUN_008a92a0(void) { FUN_00747f00(); }
void FUN_008b30e0(void) { FUN_008b2f80(); }
void FUN_008b30f0(void) { FUN_008b3030(); }
void FUN_008b3d00(void) { FUN_008b2f80(); }
void FUN_008b3d10(void) { FUN_008b3030(); }
void FUN_008b3d20(void) { FUN_008b2f80(); }
void FUN_008b3d30(void) { FUN_008b3030(); }
void FUN_008b3d40(void) { FUN_008b2f80(); }
void FUN_008b3d50(void) { FUN_008b3030(); }
void FUN_008b3d60(void) { FUN_008b2f80(); }
void FUN_008b3d70(void) { FUN_008b3030(); }
void FUN_009078b0(void) { FUN_009092d0(); }
void FUN_0091d6f0(void) { FUN_0092c680(); }
void FUN_0091d760(void) { FUN_0092c660(); }
void FUN_0091d770(void) { FUN_008e5da0(); }
void FUN_0091d7d0(void) { FUN_0092c630(); }
void FUN_0091d7e0(void) { FUN_0092ea70(); }
void FUN_009293c0(void) { FUN_0091ce70(); }
void FUN_0092c870(void) { FUN_00962d50(); }
void FUN_00935590(void) { FUN_009354b0(); }
void FUN_00941760(void) { FUN_009416e0(); }
void FUN_00974b00(void) { FUN_008459e0(); }
void FUN_009c9770(void) { FUN_006ee4e0(); }
void FUN_009cac40(void) { FUN_00821200(); }
