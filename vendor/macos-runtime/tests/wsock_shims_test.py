"""Unit tests for POSIX-backed WinSock2 host shims."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]

SOURCE = r'''
#include <arpa/inet.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "shims.h"

uint8_t *MEM;
_Thread_local uint32_t host_last_error;
HostImport host_imports[MAX_IMPORTS];
int host_import_count;

extern const ShimTable wsock_shims;

static uint32_t heap = 0x80000;
uint32_t gmalloc(uint32_t n) {
    uint32_t p = heap + 16;
    P32(p - 4, n);
    heap = (p + n + 15) & ~15u;
    if (heap >= 4u << 20) abort();
    return p;
}
void gfree(uint32_t p) { if (p) memset(MEM + p, 0xdd, G32(p - 4)); }

static int failed;
static void check(const char *name, int ok) {
    printf("%s: %s\n", ok ? "PASS" : "FAIL", name);
    failed += !ok;
}

static ShimFn shim(const char *name) {
    for (int i = 0; i < wsock_shims.count; i++)
        if (strcmp(wsock_shims.list[i].name, name) == 0) return wsock_shims.list[i].fn;
    fprintf(stderr, "Missing shim %s\n", name);
    abort();
}

static uint32_t invoke(ShimFn fn, const uint32_t *args, unsigned count) {
    CPU c = {0};
    SETREG(&c, R_ESP, 0x2000);
    P32(0x2000, 0xabc);
    for (unsigned i = 0; i < count; i++) P32(0x2004 + 4 * i, args[i]);
    fn(&c);
    if (REG(&c, R_ESP) != 0x2004 + 4 * count) {
        fprintf(stderr, "Wrong stack cleanup: %#x count=%u\n", REG(&c, R_ESP), count);
        abort();
    }
    return REG(&c, R_EAX);
}

#define CALL0(name) invoke(shim(name), NULL, 0)
#define CALL(name, ...) invoke(shim(name), (uint32_t[]){__VA_ARGS__}, \
    sizeof((uint32_t[]){__VA_ARGS__}) / sizeof(uint32_t))

int main(void) {
    MEM = calloc(1, 4u << 20);

    // 1. Verify ordinal mapping matches Windows WS2_32.dll (esp #10, #11, #12).
    check("ordinal #10 is ioctlsocket", shim("ws2_32#10") == shim("ioctlsocket"));
    check("ordinal #11 is inet_addr", shim("ws2_32#11") == shim("inet_addr"));
    check("ordinal #12 is inet_ntoa", shim("ws2_32#12") == shim("inet_ntoa"));
    check("ordinal #6 is getsockname", shim("ws2_32#6") == shim("getsockname"));
    check("ordinal #17 is recvfrom", shim("ws2_32#17") == shim("recvfrom"));
    check("ordinal #20 is sendto", shim("ws2_32#20") == shim("sendto"));

    // 2. WSAStartup & WSACleanup.
    uint32_t wsadata = 0x4000;
    check("WSAStartup succeeds", CALL("WSAStartup", 0x0202, wsadata) == 0);

    // 3. socket / setsockopt / bind / getsockname / non-blocking / sendto / select / recvfrom.
    uint32_t s = CALL("socket", 2 /* AF_INET */, 2 /* SOCK_DGRAM */, 17 /* IPPROTO_UDP */);
    check("UDP socket created", s != 0xFFFFFFFFu && s != 0);

    uint32_t one = 0x4400; P32(one, 1);
    check("setsockopt SO_REUSEADDR", CALL("setsockopt", s, 0xFFFFu, 4, one, 4) == 0);
    check("setsockopt IP_DONTFRAGMENT", CALL("setsockopt", s, 0, 14, one, 4) == 0);
    uint32_t linger_g = 0x4410;
    P32(linger_g, 0x00020001u); // l_onoff=1, l_linger=2
    check("setsockopt SO_LINGER", CALL("setsockopt", s, 0xFFFFu, 0x80u, linger_g, 4) == 0);
    uint32_t lsz = 0x4418; P32(lsz, 4); P32(linger_g, 0);
    check("getsockopt SO_LINGER", CALL("getsockopt", s, 0xFFFFu, 0x80u, linger_g, lsz) == 0 && G32(linger_g) == 0x00020001u);

    uint32_t sa_bind = 0x4500;
    memset(MEM + sa_bind, 0, 16);
    MEM[sa_bind] = 2; // AF_INET
    P32(sa_bind + 4, inet_addr("127.0.0.1"));
    check("bind 127.0.0.1:0", CALL("bind", s, sa_bind, 16) == 0);

    uint32_t sa_out = 0x4520, len_out = 0x4540;
    P32(len_out, 16);
    check("getsockname", CALL("getsockname", s, sa_out, len_out) == 0 && G32(len_out) == 16);
    uint16_t bound_port_be = 0; memcpy(&bound_port_be, MEM + sa_out + 2, 2);
    check("getsockname assigned port", bound_port_be != 0);

    // SIO_GET_INTERFACE_LIST returns >= 1 valid 76-byte INTERFACE_INFO.
    uint32_t ifbuf = 0x5000, ifret = 0x4f00;
    check("WSAIoctl SIO_GET_INTERFACE_LIST",
          CALL("WSAIoctl", s, 0x4004747Fu, 0, 0, ifbuf, 0x5F0u, ifret, 0, 0) == 0 &&
          G32(ifret) == 76u && G32(ifbuf + 8) == htonl(INADDR_LOOPBACK));

    // Loopback sendto -> select -> __WSAFDIsSet -> recvfrom.
    uint32_t nb = 0x4600; P32(nb, 1);
    check("ioctlsocket FIONBIO", CALL("ioctlsocket", s, 0x8004667Eu, nb) == 0);

    uint32_t msg = 0x4700, rbuf = 0x4800, from = 0x4900, fromlen = 0x4920;
    memcpy(MEM + msg, "SMR!", 4);
    check("sendto loopback", CALL("sendto", s, msg, 4, 0, sa_out, 16) == 4);

    uint32_t rfds = 0x4a00, tv = 0x4b00;
    P32(rfds, 1); P32(rfds + 4, s);
    P32(tv, 1); P32(tv + 4, 0);
    int sel = (int)CALL("select", 0, rfds, 0, 0, tv);
    check("select readable", sel == 1 && CALL("__WSAFDIsSet", s, rfds) == 1);

    P32(fromlen, 16);
    check("recvfrom loopback",
          CALL("recvfrom", s, rbuf, 64, 0, from, fromlen) == 4 &&
          memcmp(MEM + rbuf, "SMR!", 4) == 0);

    // gethostname / gethostbyname / getaddrinfo / freeaddrinfo.
    uint32_t hbuf = 0x6000;
    check("gethostname", CALL("gethostname", hbuf, 128) == 0 && strlen((char *)MEM + hbuf) > 0);
    uint32_t he = CALL("gethostbyname", hbuf);
    check("gethostbyname(self) returns loopback", he != 0 && G32(G32(G32(he + 12))) == htonl(INADDR_LOOPBACK));

    uint32_t ext = 0x6100;
    strcpy((char *)MEM + ext, "example.invalid");
    check("gethostbyname(external) fails cleanly", CALL("gethostbyname", ext) == 0 && CALL0("WSAGetLastError") == 11001u);

    uint32_t res_ptr = 0x6200, loc = 0x6220;
    strcpy((char *)MEM + loc, "localhost");
    check("getaddrinfo(localhost)", CALL("getaddrinfo", loc, 0, 0, res_ptr) == 0 && G32(res_ptr) != 0);
    CALL("freeaddrinfo", G32(res_ptr));

    check("closesocket", CALL("closesocket", s) == 0);
    check("WSACleanup", CALL0("WSACleanup") == 0);

    free(MEM);
    return failed ? 1 : 0;
}
'''

with tempfile.TemporaryDirectory(prefix='fnv-wsock-test-') as temp:
    temp = Path(temp)
    src = temp / 'test.c'
    binary = temp / 'test'
    src.write_text(SOURCE)
    subprocess.run([
        'xcrun', 'clang', '-std=gnu11', '-O1',
        '-I', str(ROOT / 'upstream/recomp/host'),
        '-I', str(ROOT / 'upstream/recomp'),
        str(src), str(ROOT / 'upstream/recomp/host/shims_wsock.c'),
        '-pthread', '-o', str(binary),
    ], check=True)
    res = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
    print(res.stdout + res.stderr, flush=True)
    assert res.returncode == 0, 'wsock_shims_test failed'
