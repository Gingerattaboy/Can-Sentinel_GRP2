/* victim_ecu.c - CAN-Sentinel Week 4, Member 2
 *
 * A simulated brake receiver on vcan0.
 *   - Listens for brake frames on ID 0x500 and control frames on ID 0x7F0.
 *   - Control frame: DLC 3, bytes 0-1 = target ID (big-endian), byte 2 = 1 quarantine on, 0 off.
 *   - While quarantine is on it accepts at most ONE 0x500 frame per 20 ms and drops the rest.
 *   - Writes one line per second to a CSV file.
 *
 * THIS IS A SIMULATION at application level on vcan0. It is NOT a real CAN error-frame defence.
 * The 0xA5 tag is read ONLY to count attack frames for the evaluation; it never changes a decision.
 *
 * Build:  gcc -O2 -Wall -Wextra -o victim_ecu victim_ecu.c
 * Run  :  ./victim_ecu                      (vcan0, writes data/victim_stats.csv)
 *         ./victim_ecu -o /tmp/stats.csv
 */
#define _GNU_SOURCE
#include <errno.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <net/if.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <linux/can.h>
#include <linux/can/raw.h>

#define BRAKE_ID      0x500u
#define CONTROL_ID    0x7F0u
#define MIN_GAP_NS    20000000LL          /* 20 ms between accepted frames in quarantine */
#define ATTACK_TAG    0xA5                /* evaluation-only ground truth */

/* ---- rate limiter: pure function so it can be tested without a CAN bus ---- */
typedef struct { int quarantine; long long last_accept_ns; int have_accept; } limiter_t;

static int limiter_accept(limiter_t *l, long long now_ns)
{
    if (l->quarantine && l->have_accept && (now_ns - l->last_accept_ns) < MIN_GAP_NS)
        return 0;                                   /* too soon: drop */
    l->last_accept_ns = now_ns;
    l->have_accept = 1;
    return 1;                                       /* accept */
}

#ifdef SELFTEST
int main(void)
{
    limiter_t l = {0, 0, 0};
    int ok = 1, acc = 0;
    /* quarantine off: every frame is accepted */
    for (int i = 0; i < 10; i++) acc += limiter_accept(&l, i * 1000000LL);
    if (acc != 10) { puts("FAIL off"); ok = 0; }
    /* quarantine on, one frame every 1 ms for 100 ms: expect 1 accepted per 20 ms */
    l.quarantine = 1; l.have_accept = 0; acc = 0;
    for (int i = 0; i < 100; i++) acc += limiter_accept(&l, 100000000LL + i * 1000000LL);
    printf("quarantine on, 100 frames in 100 ms -> accepted %d (expect 5)\n", acc);
    if (acc != 5) ok = 0;
    /* quarantine on, legitimate 50 Hz frames exactly 20 ms apart: all accepted */
    l.have_accept = 0; acc = 0;
    for (int i = 0; i < 50; i++) acc += limiter_accept(&l, 500000000LL + i * 20000000LL);
    printf("quarantine on, 50 frames 20 ms apart -> accepted %d (expect 50)\n", acc);
    if (acc != 50) ok = 0;
    /* quarantine on, a legitimate frame arriving 19 ms after the last one is dropped */
    l.have_accept = 0;
    limiter_accept(&l, 2000000000LL);
    int r = limiter_accept(&l, 2000000000LL + 19000000LL);
    printf("frame 19 ms after the last -> %s (expect dropped)\n", r ? "accepted" : "dropped");
    if (r) ok = 0;
    puts(ok ? "SELFTEST PASSED" : "SELFTEST FAILED");
    return ok ? 0 : 1;
}
#else

static volatile sig_atomic_t stop_flag = 0;
static void on_sigint(int s) { (void)s; stop_flag = 1; }

static long long now_ns(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (long long)ts.tv_sec * 1000000000LL + ts.tv_nsec;
}

int main(int argc, char **argv)
{
    const char *ifname = "vcan0";
    const char *out_path = "data/victim_stats.csv";
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "-i") && i + 1 < argc) ifname = argv[++i];
        else if (!strcmp(argv[i], "-o") && i + 1 < argc) out_path = argv[++i];
        else { fprintf(stderr, "usage: %s [-i vcan0] [-o stats.csv]\n", argv[0]); return 2; }
    }
    if (strcmp(ifname, "vcan0") != 0) {             /* project rule: vcan0 only */
        fprintf(stderr, "refusing to run on '%s': this tool is for vcan0 only\n", ifname);
        return 2;
    }

    int s = socket(PF_CAN, SOCK_RAW, CAN_RAW);
    if (s < 0) { perror("socket(PF_CAN)"); return 1; }
    struct ifreq ifr;
    memset(&ifr, 0, sizeof ifr);
    strncpy(ifr.ifr_name, ifname, IFNAMSIZ - 1);
    if (ioctl(s, SIOCGIFINDEX, &ifr) < 0) { perror("SIOCGIFINDEX (does vcan0 exist?)"); return 1; }
    struct sockaddr_can addr;
    memset(&addr, 0, sizeof addr);
    addr.can_family = AF_CAN;
    addr.can_ifindex = ifr.ifr_ifindex;
    if (bind(s, (struct sockaddr *)&addr, sizeof addr) < 0) { perror("bind"); return 1; }

    struct can_filter flt[2] = {
        { .can_id = BRAKE_ID,   .can_mask = CAN_SFF_MASK },
        { .can_id = CONTROL_ID, .can_mask = CAN_SFF_MASK },
    };
    setsockopt(s, SOL_CAN_RAW, CAN_RAW_FILTER, flt, sizeof flt);

    FILE *out = fopen(out_path, "w");
    if (!out) { perror(out_path); return 1; }
    fprintf(out, "second,quarantine,accepted,dropped,spoofed_applied,legit_dropped\n");
    fflush(out);

    signal(SIGINT, on_sigint);
    signal(SIGTERM, on_sigint);

    limiter_t lim = {0, 0, 0};
    long accepted = 0, dropped = 0, spoofed = 0, legit_dropped = 0;
    long second = 0;
    long long next_tick = now_ns() + 1000000000LL;
    printf("victim_ecu up on %s, writing %s (simulated defence, vcan0 only)\n", ifname, out_path);
    fflush(stdout);

    while (!stop_flag) {
        long long t = now_ns();
        int wait_ms = (int)((next_tick - t) / 1000000LL);
        if (wait_ms < 0) wait_ms = 0;
        struct pollfd pfd = { .fd = s, .events = POLLIN };
        int pr = poll(&pfd, 1, wait_ms);
        if (pr < 0 && errno != EINTR) { perror("poll"); break; }

        if (pr > 0 && (pfd.revents & POLLIN)) {
            struct can_frame f;
            ssize_t n = read(s, &f, sizeof f);
            if (n == (ssize_t)sizeof f &&
                !(f.can_id & (CAN_EFF_FLAG | CAN_RTR_FLAG | CAN_ERR_FLAG))) {
                long long ft = now_ns();
                if (f.can_id == CONTROL_ID) {
                    if (f.can_dlc == 3) {
                        unsigned target = ((unsigned)f.data[0] << 8) | f.data[1];
                        if (target == BRAKE_ID && (f.data[2] == 0 || f.data[2] == 1)) {
                            lim.quarantine = f.data[2];
                            lim.have_accept = 0;
                            printf("[%ld s] quarantine %s for 0x%03X\n", second,
                                   lim.quarantine ? "ON" : "OFF", target);
                            fflush(stdout);
                        }
                    }
                } else if (f.can_id == BRAKE_ID) {
                    int tagged = (f.can_dlc > 0 && f.data[f.can_dlc - 1] == ATTACK_TAG);
                    if (limiter_accept(&lim, ft)) {
                        accepted++;
                        if (tagged) spoofed++;
                    } else {
                        dropped++;
                        if (!tagged) legit_dropped++;
                    }
                }
            }
        }

        if (now_ns() >= next_tick) {
            second++;
            fprintf(out, "%ld,%d,%ld,%ld,%ld,%ld\n", second, lim.quarantine,
                    accepted, dropped, spoofed, legit_dropped);
            fflush(out);
            accepted = dropped = spoofed = legit_dropped = 0;
            next_tick += 1000000000LL;
        }
    }
    fprintf(out, "%ld,%d,%ld,%ld,%ld,%ld\n", second + 1, lim.quarantine,
            accepted, dropped, spoofed, legit_dropped);
    fclose(out);
    close(s);
    return 0;
}
#endif
