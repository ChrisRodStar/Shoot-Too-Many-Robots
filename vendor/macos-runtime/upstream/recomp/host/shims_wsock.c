// POSIX-backed WinSock 1.1 / WinSock 2 shims (WSOCK32.dll / WS2_32.dll).
// Translates Win32 socket handles, sockaddr_in, fd_set, sockopts, IOCTLs, and errors
// onto macOS BSD sockets while keeping DNS resolution offline-safe (loopback + IP literals).
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/ioctl.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>
#include "shims.h"

#define WSAEINTR           10004u
#define WSAEBADF           10009u
#define WSAEACCES          10013u
#define WSAEFAULT          10014u
#define WSAEINVAL          10022u
#define WSAEMFILE          10024u
#define WSAEWOULDBLOCK     10035u
#define WSAEINPROGRESS     10036u
#define WSAEALREADY        10037u
#define WSAENOTSOCK        10038u
#define WSAEDESTADDRREQ    10039u
#define WSAEMSGSIZE        10040u
#define WSAEPROTOTYPE      10041u
#define WSAENOPROTOOPT     10042u
#define WSAEPROTONOSUPPORT 10043u
#define WSAEAFNOSUPPORT    10047u
#define WSAEADDRINUSE      10048u
#define WSAEADDRNOTAVAIL   10049u
#define WSAENETDOWN        10050u
#define WSAENETUNREACH     10051u
#define WSAECONNABORTED    10053u
#define WSAECONNRESET      10054u
#define WSAENOBUFS         10055u
#define WSAEISCONN         10056u
#define WSAENOTCONN        10057u
#define WSAETIMEDOUT       10060u
#define WSAECONNREFUSED    10061u
#define WSAEHOSTUNREACH    10065u
#define WSAHOST_NOT_FOUND  11001u

#define WIN_AF_INET        2u
#define WIN_INVALID_SOCKET 0xFFFFFFFFu
#define WIN_SOCKET_ERROR   0xFFFFFFFFu

#define WIN_SOL_SOCKET     0xFFFFu
#define WIN_IPPROTO_IP     0u
#define WIN_IPPROTO_TCP    6u

#define WIN_SO_DEBUG             0x0001u
#define WIN_SO_REUSEADDR         0x0004u
#define WIN_SO_KEEPALIVE         0x0008u
#define WIN_SO_DONTROUTE         0x0010u
#define WIN_SO_BROADCAST         0x0020u
#define WIN_SO_LINGER            0x0080u
#define WIN_SO_OOBINLINE         0x0100u
#define WIN_SO_SNDBUF            0x1001u
#define WIN_SO_RCVBUF            0x1002u
#define WIN_SO_SNDLOWAT          0x1003u
#define WIN_SO_RCVLOWAT          0x1004u
#define WIN_SO_SNDTIMEO          0x1005u
#define WIN_SO_RCVTIMEO          0x1006u
#define WIN_SO_ERROR             0x1007u
#define WIN_SO_TYPE              0x1008u
#define WIN_SO_EXCLUSIVEADDRUSE  0xFFFFFFFBu

#define WIN_IP_DONTFRAGMENT      14u
#define WIN_TCP_NODELAY          1u

#define WIN_FIONREAD             0x4004667Fu
#define WIN_FIONBIO              0x8004667Eu
#define WIN_SIO_GET_INTERFACE_LIST 0x4004747Fu
#define WIN_SIO_UDP_CONNRESET    0x9800000Cu

#define WIN_FD_SETSIZE     64u
#define SOCK_HANDLE_BASE   0x1000u
#define MAX_SOCKS          512u

static _Thread_local uint32_t wsa_last_error;
static _Thread_local uint32_t tls_ntoa_buf;
static _Thread_local uint32_t tls_hostent_buf;

typedef struct {
    int used;
    int fd;
    int type;
} SockSlot;

static pthread_mutex_t sock_lock = PTHREAD_MUTEX_INITIALIZER;
static SockSlot sock_slots[MAX_SOCKS];

static uint32_t wsa_set(uint32_t err) {
    wsa_last_error = err;
    SETERR(err);
    return err;
}

static uint32_t errno_to_wsa(int err) {
    switch (err) {
    case 0:               return 0;
    case EINTR:           return WSAEINTR;
    case EBADF:           return WSAENOTSOCK;
    case EACCES:
    case EPERM:           return WSAEACCES;
    case EFAULT:          return WSAEFAULT;
    case EINVAL:          return WSAEINVAL;
    case EMFILE:
    case ENFILE:          return WSAEMFILE;
    case EAGAIN:          return WSAEWOULDBLOCK;
    case EINPROGRESS:     return WSAEINPROGRESS;
    case EALREADY:        return WSAEALREADY;
    case ENOTSOCK:        return WSAENOTSOCK;
    case EDESTADDRREQ:    return WSAEDESTADDRREQ;
    case EMSGSIZE:        return WSAEMSGSIZE;
    case EPROTOTYPE:      return WSAEPROTOTYPE;
    case ENOPROTOOPT:     return WSAENOPROTOOPT;
    case EPROTONOSUPPORT: return WSAEPROTONOSUPPORT;
    case EAFNOSUPPORT:    return WSAEAFNOSUPPORT;
    case EADDRINUSE:      return WSAEADDRINUSE;
    case EADDRNOTAVAIL:   return WSAEADDRNOTAVAIL;
    case ENETDOWN:        return WSAENETDOWN;
    case ENETUNREACH:     return WSAENETUNREACH;
    case ECONNABORTED:    return WSAECONNABORTED;
    case ECONNRESET:      return WSAECONNRESET;
    case ENOBUFS:         return WSAENOBUFS;
    case EISCONN:         return WSAEISCONN;
    case ENOTCONN:        return WSAENOTCONN;
    case ETIMEDOUT:       return WSAETIMEDOUT;
    case ECONNREFUSED:    return WSAECONNREFUSED;
    case EHOSTUNREACH:    return WSAEHOSTUNREACH;
    default:              return WSAENETDOWN;
    }
}

static uint32_t sock_alloc(int fd, int type) {
    pthread_mutex_lock(&sock_lock);
    for (uint32_t i = 0; i < MAX_SOCKS; i++) {
        if (!sock_slots[i].used) {
            sock_slots[i].used = 1;
            sock_slots[i].fd = fd;
            sock_slots[i].type = type;
            pthread_mutex_unlock(&sock_lock);
            return SOCK_HANDLE_BASE + i;
        }
    }
    pthread_mutex_unlock(&sock_lock);
    return WIN_INVALID_SOCKET;
}

static int sock_lookup(uint32_t h, int *out_type) {
    if (h < SOCK_HANDLE_BASE || h >= SOCK_HANDLE_BASE + MAX_SOCKS) return -1;
    uint32_t i = h - SOCK_HANDLE_BASE;
    pthread_mutex_lock(&sock_lock);
    int fd = sock_slots[i].used ? sock_slots[i].fd : -1;
    if (out_type) *out_type = sock_slots[i].used ? sock_slots[i].type : 0;
    pthread_mutex_unlock(&sock_lock);
    return fd;
}

static int sock_free(uint32_t h) {
    if (h < SOCK_HANDLE_BASE || h >= SOCK_HANDLE_BASE + MAX_SOCKS) return -1;
    uint32_t i = h - SOCK_HANDLE_BASE;
    pthread_mutex_lock(&sock_lock);
    int fd = -1;
    if (sock_slots[i].used) {
        fd = sock_slots[i].fd;
        sock_slots[i].used = 0;
        sock_slots[i].fd = -1;
        sock_slots[i].type = 0;
    }
    pthread_mutex_unlock(&sock_lock);
    return fd;
}

static int win_to_host_sa(uint32_t gaddr, uint32_t glen, struct sockaddr_in *out) {
    if (!gaddr || glen < 16) {
        wsa_set(WSAEFAULT);
        return -1;
    }
    uint16_t fam = 0;
    memcpy(&fam, MEM + gaddr, 2);
    if (fam != WIN_AF_INET && fam != 0) {
        wsa_set(WSAEAFNOSUPPORT);
        return -1;
    }
    memset(out, 0, sizeof(*out));
    out->sin_len = sizeof(*out);
    out->sin_family = AF_INET;
    memcpy(&out->sin_port, MEM + gaddr + 2, 2);
    memcpy(&out->sin_addr, MEM + gaddr + 4, 4);
    return 0;
}

static void host_to_win_sa(const struct sockaddr_in *in, uint32_t gaddr, uint32_t glen_ptr) {
    uint8_t buf[16];
    memset(buf, 0, sizeof(buf));
    uint16_t fam = WIN_AF_INET;
    memcpy(buf, &fam, 2);
    memcpy(buf + 2, &in->sin_port, 2);
    memcpy(buf + 4, &in->sin_addr, 4);
    uint32_t cap = glen_ptr ? G32(glen_ptr) : 16u;
    if (gaddr && cap > 0) {
        uint32_t copy_n = cap < 16u ? cap : 16u;
        memcpy(MEM + gaddr, buf, copy_n);
    }
    if (glen_ptr) P32(glen_ptr, 16u);
}

static int allow_loopback_or_self(const struct in_addr *addr, char *hostbuf, size_t n) {
    if (gethostname(hostbuf, n) != 0) snprintf(hostbuf, n, "localhost");
    hostbuf[n - 1] = 0;
    // Always treat loopback / unspecified as safe local addresses.
    uint32_t h = ntohl(addr->s_addr);
    return (h >> 24) == 127u || h == 0u;
}

static int resolve_host_ipv4(const char *name, struct in_addr *out) {
    char local[256];
    if (gethostname(local, sizeof(local)) != 0) snprintf(local, sizeof(local), "localhost");
    local[sizeof(local) - 1] = 0;
    if (!name || !*name || strcasecmp(name, "localhost") == 0 || strcasecmp(name, local) == 0) {
        out->s_addr = htonl(INADDR_LOOPBACK);
        return 0;
    }
    if (inet_aton(name, out) != 0) return 0;
    return -1;
}

static uint32_t build_hostent(const char *name, const struct in_addr *addr) {
    // Guest layout (packed pointers for x86):
    // +0x00 struct hostent (16B): h_name@0, h_aliases@4, h_addrtype@8 (short=2), h_length@10 (short=4), h_addr_list@12
    // +0x10 char *aliases[1] = {NULL} (4B)
    // +0x14 char *addr_list[2] = {+0x1c, NULL} (8B)
    // +0x1c struct in_addr (4B)
    // +0x20 char h_name_buf[128]
    if (!tls_hostent_buf) tls_hostent_buf = gmalloc(160);
    uint32_t base = tls_hostent_buf;
    memset(MEM + base, 0, 160);
    const char *label = (name && *name) ? name : "localhost";
    snprintf((char *)MEM + base + 0x20, 128, "%s", label);
    memcpy(MEM + base + 0x1c, &addr->s_addr, 4);
    P32(base + 0x10, 0);
    P32(base + 0x14, base + 0x1c);
    P32(base + 0x18, 0);
    P32(base + 0x00, base + 0x20);
    P32(base + 0x04, base + 0x10);
    uint16_t fam = WIN_AF_INET, len = 4;
    memcpy(MEM + base + 0x08, &fam, 2);
    memcpy(MEM + base + 0x0a, &len, 2);
    P32(base + 0x0c, base + 0x14);
    return base;
}

// ---- WinSock functions -------------------------------------------------------------------------

SHIM(WSAStartup) {
    uint32_t wsa_data = ARG(c, 1);
    if (wsa_data) {
        memset(MEM + wsa_data, 0, 400);
        uint16_t ver = (uint16_t)ARG(c, 0);
        memcpy(MEM + wsa_data, &ver, 2);
        memcpy(MEM + wsa_data + 2, &ver, 2);
        snprintf((char *)MEM + wsa_data + 4, 256, "WinSock 2.0");
        snprintf((char *)MEM + wsa_data + 261, 128, "Running");
    }
    wsa_set(0);
    RET(c, 0, 2);
}

SHIM(WSACleanup) {
    wsa_set(0);
    RET(c, 0, 0);
}

SHIM(WSAGetLastError) {
    RET(c, wsa_last_error, 0);
}

SHIM(WSASetLastError) {
    wsa_set(ARG(c, 0));
    RET(c, 0, 1);
}

SHIM(WSAAsyncSelect) {
    wsa_set(0);
    RET(c, 0, 4);
}

SHIM(socket) {
    int af = (int)ARG(c, 0);
    int type = (int)ARG(c, 1);
    int proto = (int)ARG(c, 2);
    if (af != WIN_AF_INET) {
        wsa_set(WSAEAFNOSUPPORT);
        RET(c, WIN_INVALID_SOCKET, 3);
        return;
    }
    int fd = socket(AF_INET, type, proto);
    if (fd < 0) {
        wsa_set(errno_to_wsa(errno));
        RET(c, WIN_INVALID_SOCKET, 3);
        return;
    }
    int one = 1;
    setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &one, sizeof(one));
    uint32_t h = sock_alloc(fd, type);
    if (h == WIN_INVALID_SOCKET) {
        close(fd);
        wsa_set(WSAEMFILE);
        RET(c, WIN_INVALID_SOCKET, 3);
        return;
    }
    wsa_set(0);
    RET(c, h, 3);
}

SHIM(closesocket) {
    int fd = sock_free(ARG(c, 0));
    if (fd < 0) {
        wsa_set(WSAENOTSOCK);
        RET(c, WIN_SOCKET_ERROR, 1);
        return;
    }
    shutdown(fd, SHUT_RDWR);
    int rc = close(fd);
    if (rc < 0) {
        wsa_set(errno_to_wsa(errno));
        RET(c, WIN_SOCKET_ERROR, 1);
        return;
    }
    wsa_set(0);
    RET(c, 0, 1);
}

SHIM(shutdown) {
    int fd = sock_lookup(ARG(c, 0), NULL);
    int how = (int)ARG(c, 1);
    if (fd < 0) {
        wsa_set(WSAENOTSOCK);
        RET(c, WIN_SOCKET_ERROR, 2);
        return;
    }
    if (shutdown(fd, how) < 0) {
        wsa_set(errno_to_wsa(errno));
        RET(c, WIN_SOCKET_ERROR, 2);
        return;
    }
    wsa_set(0);
    RET(c, 0, 2);
}

SHIM(bind) {
    int fd = sock_lookup(ARG(c, 0), NULL);
    if (fd < 0) {
        wsa_set(WSAENOTSOCK);
        RET(c, WIN_SOCKET_ERROR, 3);
        return;
    }
    struct sockaddr_in sa;
    if (win_to_host_sa(ARG(c, 1), ARG(c, 2), &sa) < 0) {
        RET(c, WIN_SOCKET_ERROR, 3);
        return;
    }
    if (bind(fd, (const struct sockaddr *)&sa, sizeof(sa)) < 0) {
        wsa_set(errno_to_wsa(errno));
        RET(c, WIN_SOCKET_ERROR, 3);
        return;
    }
    wsa_set(0);
    RET(c, 0, 3);
}

SHIM(listen) {
    int fd = sock_lookup(ARG(c, 0), NULL);
    int backlog = (int)ARG(c, 1);
    if (fd < 0) {
        wsa_set(WSAENOTSOCK);
        RET(c, WIN_SOCKET_ERROR, 2);
        return;
    }
    if (listen(fd, backlog) < 0) {
        wsa_set(errno_to_wsa(errno));
        RET(c, WIN_SOCKET_ERROR, 2);
        return;
    }
    wsa_set(0);
    RET(c, 0, 2);
}

SHIM(accept) {
    int stype = 0;
    int fd = sock_lookup(ARG(c, 0), &stype);
    uint32_t gaddr = ARG(c, 1), glen_ptr = ARG(c, 2);
    if (fd < 0) {
        wsa_set(WSAENOTSOCK);
        RET(c, WIN_INVALID_SOCKET, 3);
        return;
    }
    struct sockaddr_in sa;
    socklen_t salen = sizeof(sa);
    int cfd = accept(fd, (struct sockaddr *)&sa, &salen);
    if (cfd < 0) {
        wsa_set(errno_to_wsa(errno));
        RET(c, WIN_INVALID_SOCKET, 3);
        return;
    }
    int one = 1;
    setsockopt(cfd, SOL_SOCKET, SO_NOSIGPIPE, &one, sizeof(one));
    uint32_t h = sock_alloc(cfd, stype);
    if (h == WIN_INVALID_SOCKET) {
        close(cfd);
        wsa_set(WSAEMFILE);
        RET(c, WIN_INVALID_SOCKET, 3);
        return;
    }
    if (gaddr) host_to_win_sa(&sa, gaddr, glen_ptr);
    wsa_set(0);
    RET(c, h, 3);
}

SHIM(connect) {
    int fd = sock_lookup(ARG(c, 0), NULL);
    if (fd < 0) {
        wsa_set(WSAENOTSOCK);
        RET(c, WIN_SOCKET_ERROR, 3);
        return;
    }
    struct sockaddr_in sa;
    if (win_to_host_sa(ARG(c, 1), ARG(c, 2), &sa) < 0) {
        RET(c, WIN_SOCKET_ERROR, 3);
        return;
    }
    char hostbuf[64];
    if (!allow_loopback_or_self(&sa.sin_addr, hostbuf, sizeof(hostbuf)) && !getenv("FNV_ALLOW_EXTERNAL_NET")) {
        wsa_set(WSAECONNREFUSED);
        RET(c, WIN_SOCKET_ERROR, 3);
        return;
    }
    if (connect(fd, (const struct sockaddr *)&sa, sizeof(sa)) < 0) {
        wsa_set(errno_to_wsa(errno));
        RET(c, WIN_SOCKET_ERROR, 3);
        return;
    }
    wsa_set(0);
    RET(c, 0, 3);
}

SHIM(getsockname) {
    int fd = sock_lookup(ARG(c, 0), NULL);
    uint32_t gaddr = ARG(c, 1), glen_ptr = ARG(c, 2);
    if (fd < 0) {
        wsa_set(WSAENOTSOCK);
        RET(c, WIN_SOCKET_ERROR, 3);
        return;
    }
    if (!gaddr || !glen_ptr) {
        wsa_set(WSAEFAULT);
        RET(c, WIN_SOCKET_ERROR, 3);
        return;
    }
    struct sockaddr_in sa;
    socklen_t salen = sizeof(sa);
    if (getsockname(fd, (struct sockaddr *)&sa, &salen) < 0) {
        wsa_set(errno_to_wsa(errno));
        RET(c, WIN_SOCKET_ERROR, 3);
        return;
    }
    host_to_win_sa(&sa, gaddr, glen_ptr);
    wsa_set(0);
    RET(c, 0, 3);
}

SHIM(getpeername) {
    int fd = sock_lookup(ARG(c, 0), NULL);
    uint32_t gaddr = ARG(c, 1), glen_ptr = ARG(c, 2);
    if (fd < 0) {
        wsa_set(WSAENOTSOCK);
        RET(c, WIN_SOCKET_ERROR, 3);
        return;
    }
    if (!gaddr || !glen_ptr) {
        wsa_set(WSAEFAULT);
        RET(c, WIN_SOCKET_ERROR, 3);
        return;
    }
    struct sockaddr_in sa;
    socklen_t salen = sizeof(sa);
    if (getpeername(fd, (struct sockaddr *)&sa, &salen) < 0) {
        wsa_set(errno_to_wsa(errno));
        RET(c, WIN_SOCKET_ERROR, 3);
        return;
    }
    host_to_win_sa(&sa, gaddr, glen_ptr);
    wsa_set(0);
    RET(c, 0, 3);
}

SHIM(send) {
    int fd = sock_lookup(ARG(c, 0), NULL);
    uint32_t buf = ARG(c, 1);
    int len = (int)ARG(c, 2), flags = (int)ARG(c, 3);
    if (fd < 0) {
        wsa_set(WSAENOTSOCK);
        RET(c, WIN_SOCKET_ERROR, 4);
        return;
    }
    ssize_t rc = send(fd, MEM + buf, (size_t)(len > 0 ? len : 0), flags);
    if (rc < 0) {
        wsa_set(errno_to_wsa(errno));
        RET(c, WIN_SOCKET_ERROR, 4);
        return;
    }
    wsa_set(0);
    RET(c, (uint32_t)rc, 4);
}

SHIM(recv) {
    int fd = sock_lookup(ARG(c, 0), NULL);
    uint32_t buf = ARG(c, 1);
    int len = (int)ARG(c, 2), flags = (int)ARG(c, 3);
    if (fd < 0) {
        wsa_set(WSAENOTSOCK);
        RET(c, WIN_SOCKET_ERROR, 4);
        return;
    }
    ssize_t rc = recv(fd, MEM + buf, (size_t)(len > 0 ? len : 0), flags);
    if (rc < 0) {
        wsa_set(errno_to_wsa(errno));
        RET(c, WIN_SOCKET_ERROR, 4);
        return;
    }
    wsa_set(0);
    RET(c, (uint32_t)rc, 4);
}

SHIM(sendto) {
    int fd = sock_lookup(ARG(c, 0), NULL);
    uint32_t buf = ARG(c, 1), to = ARG(c, 4), tolen = ARG(c, 5);
    int len = (int)ARG(c, 2), flags = (int)ARG(c, 3);
    if (fd < 0) {
        wsa_set(WSAENOTSOCK);
        RET(c, WIN_SOCKET_ERROR, 6);
        return;
    }
    struct sockaddr_in sa;
    const struct sockaddr *dst = NULL;
    socklen_t dlen = 0;
    if (to) {
        if (win_to_host_sa(to, tolen, &sa) < 0) {
            RET(c, WIN_SOCKET_ERROR, 6);
            return;
        }
        char hostbuf[64];
        if (!allow_loopback_or_self(&sa.sin_addr, hostbuf, sizeof(hostbuf)) && !getenv("FNV_ALLOW_EXTERNAL_NET")) {
            wsa_set(WSAEACCES);
            RET(c, WIN_SOCKET_ERROR, 6);
            return;
        }
        dst = (const struct sockaddr *)&sa;
        dlen = sizeof(sa);
    }
    ssize_t rc = sendto(fd, MEM + buf, (size_t)(len > 0 ? len : 0), flags, dst, dlen);
    if (rc < 0) {
        wsa_set(errno_to_wsa(errno));
        RET(c, WIN_SOCKET_ERROR, 6);
        return;
    }
    wsa_set(0);
    RET(c, (uint32_t)rc, 6);
}

SHIM(recvfrom) {
    int fd = sock_lookup(ARG(c, 0), NULL);
    uint32_t buf = ARG(c, 1), from = ARG(c, 4), fromlen_ptr = ARG(c, 5);
    int len = (int)ARG(c, 2), flags = (int)ARG(c, 3);
    if (fd < 0) {
        wsa_set(WSAENOTSOCK);
        RET(c, WIN_SOCKET_ERROR, 6);
        return;
    }
    struct sockaddr_in sa;
    socklen_t salen = sizeof(sa);
    ssize_t rc = recvfrom(fd, MEM + buf, (size_t)(len > 0 ? len : 0), flags,
                          from ? (struct sockaddr *)&sa : NULL, from ? &salen : NULL);
    if (rc < 0) {
        wsa_set(errno_to_wsa(errno));
        RET(c, WIN_SOCKET_ERROR, 6);
        return;
    }
    if (from && salen >= (socklen_t)sizeof(struct sockaddr_in))
        host_to_win_sa(&sa, from, fromlen_ptr);
    wsa_set(0);
    RET(c, (uint32_t)rc, 6);
}

static int map_sol_opt(uint32_t opt) {
    switch (opt) {
    case WIN_SO_DEBUG:     return SO_DEBUG;
    case WIN_SO_REUSEADDR: return SO_REUSEADDR;
    case WIN_SO_KEEPALIVE: return SO_KEEPALIVE;
    case WIN_SO_DONTROUTE: return SO_DONTROUTE;
    case WIN_SO_BROADCAST: return SO_BROADCAST;
    case WIN_SO_LINGER:    return SO_LINGER;
    case WIN_SO_OOBINLINE: return SO_OOBINLINE;
    case WIN_SO_SNDBUF:    return SO_SNDBUF;
    case WIN_SO_RCVBUF:    return SO_RCVBUF;
    case WIN_SO_SNDLOWAT:  return SO_SNDLOWAT;
    case WIN_SO_RCVLOWAT:  return SO_RCVLOWAT;
    case WIN_SO_SNDTIMEO:  return SO_SNDTIMEO;
    case WIN_SO_RCVTIMEO:  return SO_RCVTIMEO;
    case WIN_SO_ERROR:     return SO_ERROR;
    case WIN_SO_TYPE:      return SO_TYPE;
    default:               return -1;
    }
}

SHIM(setsockopt) {
    int fd = sock_lookup(ARG(c, 0), NULL);
    uint32_t level = ARG(c, 1), opt = ARG(c, 2), val = ARG(c, 3);
    int len = (int)ARG(c, 4);
    if (fd < 0) {
        wsa_set(WSAENOTSOCK);
        RET(c, WIN_SOCKET_ERROR, 5);
        return;
    }
    if (!val || len < 0) {
        wsa_set(WSAEFAULT);
        RET(c, WIN_SOCKET_ERROR, 5);
        return;
    }
    if (level == WIN_IPPROTO_IP && opt == WIN_IP_DONTFRAGMENT) {
        wsa_set(0);
        RET(c, 0, 5);
        return;
    }
    if (level == WIN_SOL_SOCKET && opt == WIN_SO_EXCLUSIVEADDRUSE) {
        wsa_set(0);
        RET(c, 0, 5);
        return;
    }
    if (level == WIN_SOL_SOCKET && opt == WIN_SO_LINGER) {
        if (len < 4) { wsa_set(WSAEFAULT); RET(c, WIN_SOCKET_ERROR, 5); return; }
        uint16_t on = 0, sec = 0;
        memcpy(&on, MEM + val, 2);
        memcpy(&sec, MEM + val + 2, 2);
        struct linger l = { (int)on, (int)sec };
        if (setsockopt(fd, SOL_SOCKET, SO_LINGER, &l, sizeof(l)) < 0) {
            wsa_set(errno_to_wsa(errno));
            RET(c, WIN_SOCKET_ERROR, 5);
            return;
        }
        wsa_set(0);
        RET(c, 0, 5);
        return;
    }
    if (level == WIN_SOL_SOCKET && (opt == WIN_SO_SNDTIMEO || opt == WIN_SO_RCVTIMEO)) {
        if (len < 4) { wsa_set(WSAEFAULT); RET(c, WIN_SOCKET_ERROR, 5); return; }
        uint32_t ms = G32(val);
        struct timeval tv = { (time_t)(ms / 1000u), (suseconds_t)((ms % 1000u) * 1000u) };
        int hopt = (opt == WIN_SO_SNDTIMEO) ? SO_SNDTIMEO : SO_RCVTIMEO;
        if (setsockopt(fd, SOL_SOCKET, hopt, &tv, sizeof(tv)) < 0) {
            wsa_set(errno_to_wsa(errno));
            RET(c, WIN_SOCKET_ERROR, 5);
            return;
        }
        wsa_set(0);
        RET(c, 0, 5);
        return;
    }
    int hlevel = -1, hopt = -1;
    if (level == WIN_SOL_SOCKET) {
        hlevel = SOL_SOCKET;
        hopt = map_sol_opt(opt);
    } else if (level == WIN_IPPROTO_TCP && opt == WIN_TCP_NODELAY) {
        hlevel = IPPROTO_TCP;
        hopt = TCP_NODELAY;
    }
    if (hlevel < 0 || hopt < 0) {
        wsa_set(0);
        RET(c, 0, 5);
        return;
    }
    int ival = (len >= 4) ? (int)G32(val) : (len >= 1 ? (int)MEM[val] : 0);
    if (setsockopt(fd, hlevel, hopt, &ival, sizeof(ival)) < 0) {
        wsa_set(errno_to_wsa(errno));
        RET(c, WIN_SOCKET_ERROR, 5);
        return;
    }
    wsa_set(0);
    RET(c, 0, 5);
}

SHIM(getsockopt) {
    int fd = sock_lookup(ARG(c, 0), NULL);
    uint32_t level = ARG(c, 1), opt = ARG(c, 2), val = ARG(c, 3), len_ptr = ARG(c, 4);
    if (fd < 0) {
        wsa_set(WSAENOTSOCK);
        RET(c, WIN_SOCKET_ERROR, 5);
        return;
    }
    if (!val || !len_ptr) {
        wsa_set(WSAEFAULT);
        RET(c, WIN_SOCKET_ERROR, 5);
        return;
    }
    int cap = (int)G32(len_ptr);
    if (cap < 4) {
        wsa_set(WSAEFAULT);
        RET(c, WIN_SOCKET_ERROR, 5);
        return;
    }
    if (level == WIN_SOL_SOCKET && opt == WIN_SO_LINGER) {
        struct linger l = {0, 0};
        socklen_t lsz = sizeof(l);
        if (getsockopt(fd, SOL_SOCKET, SO_LINGER, &l, &lsz) < 0) {
            wsa_set(errno_to_wsa(errno));
            RET(c, WIN_SOCKET_ERROR, 5);
            return;
        }
        uint16_t on = (uint16_t)l.l_onoff, sec = (uint16_t)l.l_linger;
        memcpy(MEM + val, &on, 2);
        memcpy(MEM + val + 2, &sec, 2);
        P32(len_ptr, 4);
        wsa_set(0);
        RET(c, 0, 5);
        return;
    }
    if (level == WIN_SOL_SOCKET && (opt == WIN_SO_SNDTIMEO || opt == WIN_SO_RCVTIMEO)) {
        struct timeval tv = {0, 0};
        socklen_t tsz = sizeof(tv);
        int hopt = (opt == WIN_SO_SNDTIMEO) ? SO_SNDTIMEO : SO_RCVTIMEO;
        if (getsockopt(fd, SOL_SOCKET, hopt, &tv, &tsz) < 0) {
            wsa_set(errno_to_wsa(errno));
            RET(c, WIN_SOCKET_ERROR, 5);
            return;
        }
        uint32_t ms = (uint32_t)(tv.tv_sec * 1000 + tv.tv_usec / 1000);
        P32(val, ms);
        P32(len_ptr, 4);
        wsa_set(0);
        RET(c, 0, 5);
        return;
    }
    int hlevel = -1, hopt = -1;
    if (level == WIN_SOL_SOCKET) {
        hlevel = SOL_SOCKET;
        hopt = map_sol_opt(opt);
    } else if (level == WIN_IPPROTO_TCP && opt == WIN_TCP_NODELAY) {
        hlevel = IPPROTO_TCP;
        hopt = TCP_NODELAY;
    }
    if (hlevel < 0 || hopt < 0) {
        wsa_set(WSAENOPROTOOPT);
        RET(c, WIN_SOCKET_ERROR, 5);
        return;
    }
    int ival = 0;
    socklen_t isz = sizeof(ival);
    if (getsockopt(fd, hlevel, hopt, &ival, &isz) < 0) {
        wsa_set(errno_to_wsa(errno));
        RET(c, WIN_SOCKET_ERROR, 5);
        return;
    }
    if (level == WIN_SOL_SOCKET && opt == WIN_SO_ERROR)
        ival = (int)errno_to_wsa(ival);
    P32(val, (uint32_t)ival);
    P32(len_ptr, 4);
    wsa_set(0);
    RET(c, 0, 5);
}

SHIM(ioctlsocket) {
    int fd = sock_lookup(ARG(c, 0), NULL);
    uint32_t cmd = ARG(c, 1), argp = ARG(c, 2);
    if (fd < 0) {
        wsa_set(WSAENOTSOCK);
        RET(c, WIN_SOCKET_ERROR, 3);
        return;
    }
    if (!argp) {
        wsa_set(WSAEFAULT);
        RET(c, WIN_SOCKET_ERROR, 3);
        return;
    }
    if (cmd == WIN_FIONBIO) {
        int fl = fcntl(fd, F_GETFL, 0);
        if (fl < 0) {
            wsa_set(errno_to_wsa(errno));
            RET(c, WIN_SOCKET_ERROR, 3);
            return;
        }
        uint32_t nonblock = G32(argp);
        fl = nonblock ? (fl | O_NONBLOCK) : (fl & ~O_NONBLOCK);
        if (fcntl(fd, F_SETFL, fl) < 0) {
            wsa_set(errno_to_wsa(errno));
            RET(c, WIN_SOCKET_ERROR, 3);
            return;
        }
        wsa_set(0);
        RET(c, 0, 3);
        return;
    }
    if (cmd == WIN_FIONREAD) {
        int avail = 0;
        if (ioctl(fd, FIONREAD, &avail) < 0) {
            wsa_set(errno_to_wsa(errno));
            RET(c, WIN_SOCKET_ERROR, 3);
            return;
        }
        P32(argp, (uint32_t)avail);
        wsa_set(0);
        RET(c, 0, 3);
        return;
    }
    wsa_set(WSAEINVAL);
    RET(c, WIN_SOCKET_ERROR, 3);
}

typedef struct {
    uint32_t count;
    uint32_t handles[WIN_FD_SETSIZE];
    int fds[WIN_FD_SETSIZE];
} WinFdMap;

static int load_win_fdset(uint32_t gset, fd_set *hset, WinFdMap *map, int *maxfd) {
    FD_ZERO(hset);
    map->count = 0;
    if (!gset) return 0;
    uint32_t n = G32(gset);
    if (n > WIN_FD_SETSIZE) n = WIN_FD_SETSIZE;
    for (uint32_t i = 0; i < n; i++) {
        uint32_t h = G32(gset + 4 + i * 4);
        int fd = sock_lookup(h, NULL);
        if (fd < 0 || fd >= FD_SETSIZE) {
            wsa_set(WSAENOTSOCK);
            return -1;
        }
        FD_SET(fd, hset);
        map->handles[map->count] = h;
        map->fds[map->count] = fd;
        map->count++;
        if (fd > *maxfd) *maxfd = fd;
    }
    return 0;
}

static void store_win_fdset(uint32_t gset, const fd_set *hset, const WinFdMap *map) {
    if (!gset) return;
    uint32_t out = 0;
    for (uint32_t i = 0; i < map->count; i++) {
        if (FD_ISSET(map->fds[i], hset))
            P32(gset + 4 + (out++) * 4, map->handles[i]);
    }
    P32(gset, out);
}

SHIM(select) {
    uint32_t rfds_g = ARG(c, 1), wfds_g = ARG(c, 2), efds_g = ARG(c, 3), tv_g = ARG(c, 4);
    fd_set rfds, wfds, efds;
    WinFdMap rmap, wmap, emap;
    int maxfd = -1;
    if (load_win_fdset(rfds_g, &rfds, &rmap, &maxfd) < 0 ||
        load_win_fdset(wfds_g, &wfds, &wmap, &maxfd) < 0 ||
        load_win_fdset(efds_g, &efds, &emap, &maxfd) < 0) {
        RET(c, WIN_SOCKET_ERROR, 5);
        return;
    }
    if (maxfd < 0) {
        wsa_set(WSAEINVAL);
        RET(c, WIN_SOCKET_ERROR, 5);
        return;
    }
    struct timeval tv, *ptv = NULL;
    if (tv_g) {
        int32_t sec = (int32_t)G32(tv_g), usec = (int32_t)G32(tv_g + 4);
        if (sec < 0 || usec < 0) {
            wsa_set(WSAEINVAL);
            RET(c, WIN_SOCKET_ERROR, 5);
            return;
        }
        tv.tv_sec = sec;
        tv.tv_usec = usec;
        ptv = &tv;
    }
    int rc = select(maxfd + 1,
                    rfds_g ? &rfds : NULL,
                    wfds_g ? &wfds : NULL,
                    efds_g ? &efds : NULL,
                    ptv);
    if (rc < 0) {
        wsa_set(errno_to_wsa(errno));
        RET(c, WIN_SOCKET_ERROR, 5);
        return;
    }
    store_win_fdset(rfds_g, &rfds, &rmap);
    store_win_fdset(wfds_g, &wfds, &wmap);
    store_win_fdset(efds_g, &efds, &emap);
    wsa_set(0);
    RET(c, (uint32_t)rc, 5);
}

SHIM(__WSAFDIsSet) {
    uint32_t h = ARG(c, 0), gset = ARG(c, 1);
    if (!gset) { RET(c, 0, 2); return; }
    uint32_t n = G32(gset);
    if (n > WIN_FD_SETSIZE) n = WIN_FD_SETSIZE;
    for (uint32_t i = 0; i < n; i++) {
        if (G32(gset + 4 + i * 4) == h) {
            RET(c, 1, 2);
            return;
        }
    }
    RET(c, 0, 2);
}

SHIM(WSAIoctl) {
    int fd = sock_lookup(ARG(c, 0), NULL);
    uint32_t code = ARG(c, 1);
    uint32_t out_buf = ARG(c, 4), out_len = ARG(c, 5), ret_ptr = ARG(c, 6);
    if (fd < 0) {
        wsa_set(WSAENOTSOCK);
        RET(c, WIN_SOCKET_ERROR, 9);
        return;
    }
    if (code == WIN_SIO_GET_INTERFACE_LIST) {
        if (!ret_ptr) {
            wsa_set(WSAEFAULT);
            RET(c, WIN_SOCKET_ERROR, 9);
            return;
        }
        if (!out_buf || out_len < 76u) {
            P32(ret_ptr, 76u);
            wsa_set(WSAEFAULT);
            RET(c, WIN_SOCKET_ERROR, 9);
            return;
        }
        // Single loopback INTERFACE_INFO (76 bytes: flags@0, addr@4, bcast@28, mask@52).
        memset(MEM + out_buf, 0, 76u);
        P32(out_buf, 0x00000003u); // IFF_UP | IFF_BROADCAST
        struct sockaddr_in sa;
        memset(&sa, 0, sizeof(sa));
        sa.sin_len = sizeof(sa);
        sa.sin_family = AF_INET;
        sa.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        host_to_win_sa(&sa, out_buf + 4u, 0);
        sa.sin_addr.s_addr = htonl(0x7FFFFFFFu);
        host_to_win_sa(&sa, out_buf + 28u, 0);
        sa.sin_addr.s_addr = htonl(0xFF000000u);
        host_to_win_sa(&sa, out_buf + 52u, 0);
        P32(ret_ptr, 76u);
        wsa_set(0);
        RET(c, 0, 9);
        return;
    }
    if (code == WIN_SIO_UDP_CONNRESET) {
        if (ret_ptr) P32(ret_ptr, 0);
        wsa_set(0);
        RET(c, 0, 9);
        return;
    }
    if (ret_ptr) P32(ret_ptr, 0);
    wsa_set(WSAEINVAL);
    RET(c, WIN_SOCKET_ERROR, 9);
}

SHIM(htonl) { RET(c, htonl(ARG(c, 0)), 1); }
SHIM(htons) { RET(c, (uint16_t)htons((uint16_t)ARG(c, 0)), 1); }
SHIM(ntohl) { RET(c, ntohl(ARG(c, 0)), 1); }
SHIM(ntohs) { RET(c, (uint16_t)ntohs((uint16_t)ARG(c, 0)), 1); }

SHIM(inet_addr) {
    const char *s = GSTR(ARG(c, 0));
    if (!s) { RET(c, 0xFFFFFFFFu, 1); return; }
    RET(c, (uint32_t)inet_addr(s), 1);
}

SHIM(inet_ntoa) {
    struct in_addr in;
    in.s_addr = ARG(c, 0);
    const char *s = inet_ntoa(in);
    if (!tls_ntoa_buf) tls_ntoa_buf = gmalloc(32);
    snprintf((char *)MEM + tls_ntoa_buf, 32, "%s", s ? s : "0.0.0.0");
    RET(c, tls_ntoa_buf, 1);
}

SHIM(gethostname) {
    uint32_t p = ARG(c, 0), len = ARG(c, 1);
    if (!p || (int32_t)len < 0) {
        wsa_set(WSAEFAULT);
        RET(c, WIN_SOCKET_ERROR, 2);
        return;
    }
    char host[256];
    if (gethostname(host, sizeof(host)) != 0) snprintf(host, sizeof(host), "localhost");
    host[sizeof(host) - 1] = 0;
    size_t n = strlen(host) + 1;
    if (len < n) {
        wsa_set(WSAEFAULT);
        RET(c, WIN_SOCKET_ERROR, 2);
        return;
    }
    memcpy(MEM + p, host, n);
    wsa_set(0);
    RET(c, 0, 2);
}

SHIM(gethostbyname) {
    const char *name = GSTR(ARG(c, 0));
    struct in_addr addr;
    if (resolve_host_ipv4(name, &addr) < 0) {
        wsa_set(WSAHOST_NOT_FOUND);
        RET(c, 0, 1);
        return;
    }
    wsa_set(0);
    RET(c, build_hostent(name, &addr), 1);
}

SHIM(getaddrinfo) {
    uint32_t node_g = ARG(c, 0), serv_g = ARG(c, 1), hints_g = ARG(c, 2), res_ptr = ARG(c, 3);
    if (!res_ptr) {
        wsa_set(WSAEFAULT);
        RET(c, WSAEFAULT, 4);
        return;
    }
    P32(res_ptr, 0);
    const char *node = GSTR(node_g);
    const char *serv = GSTR(serv_g);
    struct in_addr addr;
    if (resolve_host_ipv4(node, &addr) < 0) {
        wsa_set(WSAHOST_NOT_FOUND);
        RET(c, WSAHOST_NOT_FOUND, 4);
        return;
    }
    int socktype = hints_g ? (int)G32(hints_g + 8) : 0;
    int proto = hints_g ? (int)G32(hints_g + 12) : 0;
    uint16_t port = 0;
    if (serv && *serv) {
        char *end = NULL;
        long p = strtol(serv, &end, 10);
        if (end && *end == '\0' && p >= 0 && p <= 65535) port = htons((uint16_t)p);
    }
    uint32_t ai = gmalloc(32);
    uint32_t sa = gmalloc(16);
    memset(MEM + ai, 0, 32);
    P32(ai + 4, WIN_AF_INET);
    P32(ai + 8, (uint32_t)socktype);
    P32(ai + 12, (uint32_t)proto);
    P32(ai + 16, 16u);
    P32(ai + 24, sa);
    struct sockaddr_in sin;
    memset(&sin, 0, sizeof(sin));
    sin.sin_len = sizeof(sin);
    sin.sin_family = AF_INET;
    sin.sin_port = port;
    sin.sin_addr = addr;
    host_to_win_sa(&sin, sa, 0);
    P32(res_ptr, ai);
    wsa_set(0);
    RET(c, 0, 4);
}

SHIM(freeaddrinfo) {
    uint32_t cur = ARG(c, 0);
    while (cur) {
        uint32_t next = G32(cur + 28);
        uint32_t sa = G32(cur + 24);
        uint32_t canon = G32(cur + 20);
        if (sa) gfree(sa);
        if (canon) gfree(canon);
        gfree(cur);
        cur = next;
    }
    RET(c, 0, 1);
}

#define O(ord, fn) { "wsock32#" #ord, fn##_ }, { "ws2_32#" #ord, fn##_ },
SHIM_TABLE(wsock_shims,
    O(1, accept) O(2, bind) O(3, closesocket) O(4, connect)
    O(5, getpeername) O(6, getsockname) O(7, getsockopt) O(8, htonl) O(9, htons)
    O(10, ioctlsocket) O(11, inet_addr) O(12, inet_ntoa) O(13, listen)
    O(14, ntohl) O(15, ntohs) O(16, recv) O(17, recvfrom) O(18, select)
    O(19, send) O(20, sendto) O(21, setsockopt) O(22, shutdown) O(23, socket)
    O(52, gethostbyname) O(57, gethostname) O(101, WSAAsyncSelect)
    O(111, WSAGetLastError) O(112, WSASetLastError) O(115, WSAStartup)
    O(116, WSACleanup) O(151, __WSAFDIsSet)
    E(accept) E(bind) E(closesocket) E(connect)
    E(getpeername) E(getsockname) E(getsockopt) E(htonl) E(htons)
    E(ioctlsocket) E(inet_addr) E(inet_ntoa) E(listen)
    E(ntohl) E(ntohs) E(recv) E(recvfrom) E(select)
    E(send) E(sendto) E(setsockopt) E(shutdown) E(socket)
    E(gethostbyname) E(gethostname) E(WSAAsyncSelect)
    E(WSAGetLastError) E(WSASetLastError) E(WSAStartup) E(WSACleanup) E(__WSAFDIsSet)
    E(WSAIoctl) E(getaddrinfo) E(freeaddrinfo))
