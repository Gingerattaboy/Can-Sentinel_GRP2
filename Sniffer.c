/*
 * sniffer.c - CAN-Sentinel Week 3
 *
 * Reads classic CAN frames from vcan0 (SocketCAN raw socket, kernel
 * timestamps) and streams them as fixed 21-byte little-endian records over
 * a Unix domain socket to the inference service:
 *
 *     float64 timestamp | uint32 can_id | uint8 dlc | uint8 data[8]
 *
 * Never blocks the bus: all sends are non-blocking, records are queued in a
 * small buffer, and when the buffer is full (or the service is not
 * connected) frames are DROPPED and counted. Reconnects automatically.
 *
 * SAFETY: the interface is hard-wired to vcan0. Any other name is refused.
 */
#define _GNU_SOURCE
#include <endian.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/can.h>
#include <linux/can/raw.h>
#include <net/if.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

#define CAN_IFACE        "vcan0"
#define DEFAULT_SOCK     "/tmp/can_sentinel_frames.sock"
#define REC_SIZE         21
#define OUTBUF_RECORDS   4096                 /* ~86 KB queue */
#define OUTBUF_SIZE      (REC_SIZE * OUTBUF_RECORDS)
#define RECONNECT_MS     500
#define STATS_MS         1000
#define MAX_READS_PER_LOOP 512

static volatile sig_atomic_t g_run = 1;
static void on_signal(int sig) { (void)sig; g_run = 0; }

static int64_t mono_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (int64_t)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

/* ---- record packing (explicit little-endian, no padding) -------------- */
static void pack_record(uint8_t out[REC_SIZE], double ts, uint32_t id,
                        uint8_t dlc, const uint8_t data[8])
{
    uint64_t t64;
    uint32_t id_le = htole32(id);
    memcpy(&t64, &ts, sizeof t64);
    t64 = htole64(t64);
    memcpy(out, &t64, 8);
    memcpy(out + 8, &id_le, 4);
    out[12] = dlc;
    memcpy(out + 13, data, 8);
}

/* ---- outgoing queue: only whole records are ever appended ------------- */
static uint8_t g_buf[OUTBUF_SIZE];
static size_t  g_off = 0, g_len = 0;     /* unsent bytes are g_buf[g_off..g_len) */

static int queue_record(const uint8_t rec[REC_SIZE])
{
    if (g_len + REC_SIZE > OUTBUF_SIZE) {
        if (g_off > 0) {                     /* compact */
            memmove(g_buf, g_buf + g_off, g_len - g_off);
            g_len -= g_off;
            g_off = 0;
        }
        if (g_len + REC_SIZE > OUTBUF_SIZE)
            return -1;                       /* full -> caller drops */
    }
    memcpy(g_buf + g_len, rec, REC_SIZE);
    g_len += REC_SIZE;
    return 0;
}

/* returns 0 ok / still pending, -1 if the connection is broken */
static int flush_queue(int fd)
{
    while (g_off < g_len) {
        ssize_t n = send(fd, g_buf + g_off, g_len - g_off,
                         MSG_DONTWAIT | MSG_NOSIGNAL);
        if (n > 0) { g_off += (size_t)n; continue; }
        if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) return 0;
        if (n < 0 && errno == EINTR) continue;
        return -1;
    }
    g_off = g_len = 0;
    return 0;
}

/* ---- sockets ----------------------------------------------------------- */
static int open_can(void)
{
    int fd = socket(PF_CAN, SOCK_RAW | SOCK_NONBLOCK | SOCK_CLOEXEC, CAN_RAW);
    if (fd < 0) { perror("socket(PF_CAN)"); return -1; }

    struct ifreq ifr;
    memset(&ifr, 0, sizeof ifr);
    strncpy(ifr.ifr_name, CAN_IFACE, IFNAMSIZ - 1);
    if (ioctl(fd, SIOCGIFINDEX, &ifr) < 0) {
        fprintf(stderr, "interface %s not found (sudo ip link add dev vcan0 type vcan; "
                        "sudo ip link set up vcan0)\n", CAN_IFACE);
        close(fd);
        return -1;
    }
    struct sockaddr_can addr;
    memset(&addr, 0, sizeof addr);
    addr.can_family  = AF_CAN;
    addr.can_ifindex = ifr.ifr_ifindex;
    if (bind(fd, (struct sockaddr *)&addr, sizeof addr) < 0) {
        perror("bind(can)");
        close(fd);
        return -1;
    }
    int on = 1;                              /* kernel receive timestamps */
    if (setsockopt(fd, SOL_SOCKET, SO_TIMESTAMP, &on, sizeof on) < 0)
        perror("setsockopt(SO_TIMESTAMP) - falling back to userspace time");
    return fd;
}

static int try_connect(const char *path)
{
    int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
    if (fd < 0) return -1;
    struct sockaddr_un sa;
    memset(&sa, 0, sizeof sa);
    sa.sun_family = AF_UNIX;
    strncpy(sa.sun_path, path, sizeof sa.sun_path - 1);
    if (connect(fd, (struct sockaddr *)&sa, sizeof sa) < 0) {
        close(fd);                           /* ENOENT/ECONNREFUSED/EAGAIN: retry later */
        return -1;
    }
    return fd;
}

/* ---- one frame from the CAN socket; returns 1 got frame, 0 none ------- */
static int read_frame(int can_fd, double *ts, struct can_frame *fr)
{
    char ctrl[CMSG_SPACE(sizeof(struct timeval))];
    struct iovec iov = { fr, sizeof *fr };
    struct msghdr msg;
    memset(&msg, 0, sizeof msg);
    msg.msg_iov = &iov;
    msg.msg_iovlen = 1;
    msg.msg_control = ctrl;
    msg.msg_controllen = sizeof ctrl;

    ssize_t n = recvmsg(can_fd, &msg, MSG_DONTWAIT);
    if (n != (ssize_t)sizeof *fr) return 0;

    int have = 0;
    for (struct cmsghdr *c = CMSG_FIRSTHDR(&msg); c; c = CMSG_NXTHDR(&msg, c)) {
        if (c->cmsg_level == SOL_SOCKET && c->cmsg_type == SCM_TIMESTAMP) {
            struct timeval tv;
            memcpy(&tv, CMSG_DATA(c), sizeof tv);
            *ts = (double)tv.tv_sec + (double)tv.tv_usec / 1e6;
            have = 1;
        }
    }
    if (!have) {
        struct timespec t;
        clock_gettime(CLOCK_REALTIME, &t);
        *ts = (double)t.tv_sec + (double)t.tv_nsec / 1e9;
    }
    return 1;
}

static void usage(const char *p)
{
    fprintf(stderr, "usage: %s [-s socket_path] [-i vcan0]\n"
                    "  -s  frames socket (default %s)\n"
                    "  -i  interface; only %s is accepted (safety rule)\n",
            p, DEFAULT_SOCK, CAN_IFACE);
}

int main(int argc, char **argv)
{
    const char *sock_path = DEFAULT_SOCK;
    int opt;
    while ((opt = getopt(argc, argv, "s:i:h")) != -1) {
        switch (opt) {
        case 's': sock_path = optarg; break;
        case 'i':
            if (strcmp(optarg, CAN_IFACE) != 0) {
                fprintf(stderr, "refused: this tool only runs on %s\n", CAN_IFACE);
                return 2;
            }
            break;
        default: usage(argv[0]); return opt == 'h' ? 0 : 2;
        }
    }

    if (htole32(1) != 1) { fprintf(stderr, "big-endian host not supported\n"); return 2; }

    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_handler = on_signal;
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);
    signal(SIGPIPE, SIG_IGN);

    int can_fd = open_can();
    if (can_fd < 0) return 1;

    int out_fd = -1;
    int64_t next_try = 0, next_stat = mono_ms() + STATS_MS;
    unsigned long long total_rx = 0, total_sent = 0, total_drop = 0;
    unsigned rx_s = 0, sent_s = 0, drop_full_s = 0, drop_link_s = 0;

    fprintf(stderr, "sniffer: %s -> %s\n", CAN_IFACE, sock_path);

    while (g_run) {
        int64_t now = mono_ms();

        if (out_fd < 0 && now >= next_try) {
            out_fd = try_connect(sock_path);
            next_try = now + RECONNECT_MS;
            if (out_fd >= 0) {
                g_off = g_len = 0;           /* never resume mid-record */
                fprintf(stderr, "sniffer: connected to service\n");
            }
        }

        struct pollfd p[2] = { { can_fd, POLLIN, 0 }, { out_fd, POLLIN, 0 } };
        if (out_fd >= 0 && g_off < g_len) p[1].events |= POLLOUT;
        int timeout = (out_fd >= 0 && g_off < g_len) ? 5 : 50;
        poll(p, out_fd >= 0 ? 2 : 1, timeout);

        /* service closed its end? */
        if (out_fd >= 0 && (p[1].revents & (POLLHUP | POLLERR | POLLIN))) {
            char tmp[64];
            ssize_t n = recv(out_fd, tmp, sizeof tmp, MSG_DONTWAIT);
            if (n == 0 || (n < 0 && errno != EAGAIN && errno != EINTR)) {
                fprintf(stderr, "sniffer: service disconnected, will retry\n");
                close(out_fd); out_fd = -1; g_off = g_len = 0;
            }
        }

        for (int i = 0; i < MAX_READS_PER_LOOP; i++) {
            double ts; struct can_frame fr;
            if (!read_frame(can_fd, &ts, &fr)) break;
            if (fr.can_id & CAN_ERR_FLAG) continue;      /* skip error frames */
            rx_s++; total_rx++;

            if (out_fd < 0) { drop_link_s++; total_drop++; continue; }

            uint8_t rec[REC_SIZE];
            uint8_t dlc = fr.can_dlc > 8 ? 8 : fr.can_dlc;
            pack_record(rec, ts, fr.can_id & CAN_EFF_MASK, dlc, fr.data);
            if (queue_record(rec) < 0) { drop_full_s++; total_drop++; }
        }

        if (out_fd >= 0) {
            int before = (int)(g_len - g_off);
            if (flush_queue(out_fd) < 0) {
                fprintf(stderr, "sniffer: send failed, will reconnect\n");
                close(out_fd); out_fd = -1; g_off = g_len = 0;
            } else {
                int after = (int)(g_len - g_off);
                int sent_bytes = before - after;
                if (sent_bytes > 0) { sent_s += sent_bytes / REC_SIZE; total_sent += sent_bytes / REC_SIZE; }
            }
        }

        now = mono_ms();
        if (now >= next_stat) {
            fprintf(stderr, "fps=%u sent=%u drops=%u (queue_full=%u no_link=%u) "
                            "total_rx=%llu total_drops=%llu link=%s\n",
                    rx_s, sent_s, drop_full_s + drop_link_s, drop_full_s, drop_link_s,
                    total_rx, total_drop, out_fd >= 0 ? "up" : "down");
            rx_s = sent_s = drop_full_s = drop_link_s = 0;
            next_stat += STATS_MS;
        }
    }

    fprintf(stderr, "sniffer: stopping (rx=%llu sent=%llu dropped=%llu)\n",
            total_rx, total_sent, total_drop);
    if (out_fd >= 0) close(out_fd);
    close(can_fd);
    return 0;
}
