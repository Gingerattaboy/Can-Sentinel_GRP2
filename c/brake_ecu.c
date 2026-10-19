/* brake_ecu.c - Brake ECU for CAN-Sentinel (Week 2, Member 2)
 *
 * CAN ID 0x500, every 20 ms (50 Hz), DLC 8.
 * Payload (Week 2 contract):
 *   byte 0     brake level 0..100 (smooth triangle wave, never constant)
 *   byte 1..6  0x00 padding
 *   byte 7     rolling counter, 0..255, wraps
 * Timing: absolute clock_nanosleep, +/- 0.5 ms random jitter (same as the
 * other Member 2 ECUs). Jitter is applied around the ideal tick so it never
 * accumulates as drift.
 *
 * Usage: ./brake_ecu [interface]      (default vcan0)
 */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include "can_common.h"

#define BRAKE_ID      0x500
#define PERIOD_NS     20000000L   /* 20 ms */
#define JITTER_NS     500000L     /* +/- 0.5 ms */
#define CYCLE_TICKS   500         /* one 0 -> 100 -> 0 sweep = 10 s */

static volatile sig_atomic_t stop_flag = 0;
static void on_signal(int s) { (void)s; stop_flag = 1; }

static void ts_add_ns(struct timespec *t, long ns)
{
    t->tv_nsec += ns;
    while (t->tv_nsec >= 1000000000L) { t->tv_nsec -= 1000000000L; t->tv_sec++; }
    while (t->tv_nsec < 0)            { t->tv_nsec += 1000000000L; t->tv_sec--; }
}

/* triangle wave 0..100 over CYCLE_TICKS */
static uint8_t brake_level(unsigned long tick)
{
    unsigned long p = tick % CYCLE_TICKS;
    unsigned long half = CYCLE_TICKS / 2;
    unsigned long up = (p < half) ? p : (CYCLE_TICKS - p);
    return (uint8_t)((up * 100UL) / half);
}

int main(int argc, char **argv)
{
    const char *ifname = (argc > 1) ? argv[1] : "vcan0";

    int sock = can_open(ifname);
    if (sock < 0) {
        fprintf(stderr, "brake_ecu: cannot open %s\n", ifname);
        return 1;
    }

    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_handler = on_signal;           /* no SA_RESTART: sleep is interrupted */
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    srand((unsigned)(time(NULL) ^ getpid()));

    struct timespec next;
    clock_gettime(CLOCK_MONOTONIC, &next);

    unsigned long tick = 0;
    uint8_t counter = 0;

    while (!stop_flag) {
        ts_add_ns(&next, PERIOD_NS);                 /* ideal tick, no drift */

        long jitter = (rand() % (2 * JITTER_NS + 1)) - JITTER_NS;
        struct timespec target = next;
        ts_add_ns(&target, jitter);

        int r;
        while ((r = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &target, NULL)) == EINTR
               && !stop_flag)
            ;
        if (stop_flag) break;

        uint8_t data[8] = {0};
        data[0] = brake_level(tick);
        data[7] = counter;

        if (can_send(sock, BRAKE_ID, data, 8) < 0)
            perror("brake_ecu: can_send");

        counter++;      /* uint8_t wraps 255 -> 0 */
        tick++;
    }

    close(sock);
    return 0;
}
