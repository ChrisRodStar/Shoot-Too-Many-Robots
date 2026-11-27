from native_test_toolchain import COMPILER, PLATFORM_FLAGS, LIBRARIES
import subprocess, tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
host = root / 'upstream/recomp/host'

SOURCE = r'''
// D3DPRESENT_PARAMETERS offsets and UP-draw unbinding.
#include "FNVGuestMemory.h"
#ifndef FNV_D3D_SOURCE
#define FNV_D3D_SOURCE "../upstream/recomp/host/d3d9.c"
#endif
#include FNV_D3D_SOURCE
#include <assert.h>
#include "no_core.h"
uint8_t *MEM; HostImport host_imports[MAX_IMPORTS]; int host_import_count;
void rt_trap(CPU *c,int n,uint32_t a){(void)c;fprintf(stderr,"trap %d at %#x\n",n,a);abort();}
static uint32_t stack;
static uint32_t invoke(ShimFn fn,const uint32_t *args,unsigned count){
    CPU c={0}; SETREG(&c,R_ESP,stack); P32(stack,0xe7d2e0);
    for(unsigned i=0;i<count;i++)P32(stack+4+4*i,args[i]);
    fn(&c); uint32_t actual=REG(&c,R_ESP), expected=stack+4+4*count;
    if(actual!=expected){fprintf(stderr,"ESP mismatch count=%u actual=%#x expected=%#x\n",count,actual,expected);abort();}
    return REG(&c,R_EAX);
}
#define CALL(fn,...) invoke(fn,(uint32_t[]){__VA_ARGS__},sizeof((uint32_t[]){__VA_ARGS__})/4)
static int good=1;
#define CHECK(x) do{if(!(x)){fprintf(stderr,"FAIL: %s\n",#x);good=0;}}while(0)
static void reap_all(void){g_d3d.frames+=4;reap();g_d3d.frames+=4;reap();}
static void present_params(uint32_t pp,uint32_t enable,uint32_t dsfmt,uint32_t flags){
    memset(MEM+pp,0,56);
    P32(pp,64);P32(pp+4,64);P32(pp+8,21);P32(pp+12,1);P32(pp+16,0);P32(pp+20,0);
    P32(pp+24,1);P32(pp+28,0);P32(pp+32,1);P32(pp+36,enable);P32(pp+40,dsfmt);P32(pp+44,flags);
}
int main(int argc,char **argv){
    fnv_test_disable_core_dumps();
    assert(argc==2); MEM=fnv_reserve_guest(); assert(MEM!=MAP_FAILED); make_vtables(); stack=gmalloc(256);
    const char *mode=argv[1];
    if(!strcmp(mode,"create-device-auto-depth")){
        uint32_t pp=gmalloc(56),out=gmalloc(4);
        present_params(pp,1,75,2);
        CALL(D3D_CreateDevice,0,0,0,0,0,pp,out);
        CHECK(g_d3d.ds!=0);
        CHECK(G32(out)!=0);
        if(g_d3d.ds)CHECK(G32(OBJ_F(g_d3d.ds,S_FMT))==75);
    }else if(!strcmp(mode,"create-device-no-depth")){
        uint32_t pp=gmalloc(56),out=gmalloc(4);
        present_params(pp,0,75,2);
        CALL(D3D_CreateDevice,0,0,0,0,0,pp,out);
        CHECK(g_d3d.ds==0);
        CHECK(G32(out)!=0);
    }else if(!strcmp(mode,"reset-depth")){
        uint32_t pp=gmalloc(56);
        g_d3d.ds=0;
        present_params(pp,1,75,2);
        CALL(Dev_Reset,0,pp);
        CHECK(g_d3d.ds!=0);
        if(g_d3d.ds)CHECK(G32(OBJ_F(g_d3d.ds,S_FMT))==75);
        uint32_t ds=new_surface(0,32,32,80,2,0,0,0,0,0);
        g_d3d.ds=ds;
        present_params(pp,1,75,2);
        CALL(Dev_Reset,0,pp);
        CHECK(g_d3d.ds==ds);
        CHECK(G32(OBJ_F(ds,S_FMT))==75);
        CHECK(G32(OBJ_F(ds,S_W))==64);
        CHECK(G32(OBJ_F(ds,S_H))==64);
    }else if(!strcmp(mode,"draw-primitive-up")){
        uint64_t live_before=d3d_buf_live;
        uint32_t vb=new_buffer(0,K_VB,256,0,0,1);
        CALL(Dev_SetStreamSource,0,0,vb,0,16);
        CHECK(G32(vb+4)==2);
        CHECK(g_d3d.stream[0]==vb);
        CALL(Dev_DrawPrimitiveUP,0,4,0,0,0);
        CHECK(g_d3d.stream[0]==0);
        CHECK(G32(vb+4)==1);
        CALL(Unk_Release,vb);
        reap_all();
        CHECK(d3d_buf_live==live_before);
        CHECK(ngrave==0);
    }else if(!strcmp(mode,"draw-indexed-primitive-up")){
        uint64_t live_before=d3d_buf_live;
        uint32_t vb=new_buffer(0,K_VB,256,0,0,1),ib=new_buffer(0,K_IB,256,0,101,1);
        CALL(Dev_SetStreamSource,0,0,vb,0,16);
        CALL(Dev_SetIndices,0,ib);
        CHECK(G32(vb+4)==2&&G32(ib+4)==2);
        CALL(Dev_DrawIndexedPrimitiveUP,0,4,0,0,0,0,0,0,0);
        CHECK(g_d3d.stream[0]==0);
        CHECK(g_d3d.indices==0);
        CHECK(G32(vb+4)==1&&G32(ib+4)==1);
        CALL(Unk_Release,vb);CALL(Unk_Release,ib);
        reap_all();
        CHECK(d3d_buf_live==live_before);
        CHECK(ngrave==0);
    }else return 2;
    printf("%s: %s\n",good?"PASS":"FAIL",mode);return good?0:1;
}
'''

with tempfile.TemporaryDirectory() as temp:
    work = Path(temp)
    cfile = work / 'd3d9_state_test.c'
    cfile.write_text(SOURCE)
    binary = work / 'd3d9-state-test'
    subprocess.run([*COMPILER, *PLATFORM_FLAGS, '-O1',
        '-I', str(root / 'macos'), '-I', str(host), '-I', str(root / 'upstream/recomp'), '-I', str(root / 'tests'),
        '-DFNV_D3D_SOURCE="' + str(host / 'd3d9.c') + '"',
        str(cfile), str(root / 'macos/FNVDisplay.c'),
        *[str(host / (n + '.c')) for n in ['d3d9_null', 'gheap', 'com']], *LIBRARIES, '-o', str(binary)], check=True)
    for mode in ['create-device-auto-depth', 'create-device-no-depth', 'reset-depth',
                 'draw-primitive-up', 'draw-indexed-primitive-up']:
        subprocess.run([str(binary), mode], check=True, timeout=20)
