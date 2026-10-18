/*
 * rpm_ecu.c  -  Engine RPM ECU simulator (Member 2)
 *
 * CAN ID : 0x100      Period : 10 ms      DLC : 8
 * Frame  : bytes 0-1 = engine RPM, 800..6000 (big-endian)
 *          byte  2   = rolling counter (0..255, wraps), bytes 3-7 = 0x00
 *
 * Usage  : ./rpm_ecu [interface]        (default interface: vcan0)
 * Jitter : each frame is sent at its ideal time +/- 0.5 ms (see contract).
 */
#include "can_common.h"

#include <math.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

#define CAN_ID     0x100
#define PERIOD_NS  10000000L      /* 10 ms */
#define JITTER_NS  500000L        /* +/- 0.5 ms */
#define RPM_MIN    800.0
#define RPM_MAX    6000.0
#define RPM_RATE   0.008          /* radians per frame: slow rise and fall */

static volatile sig_atomic_t running = 1;
static void stop(int s) { (void)s; running = 0; }

int main(int argc, char **argv)
{
    const char *ifname = (argc > 1) ? argv[1] : "vcan0";

    signal(SIGINT,  stop);
    signal(SIGTERM, stop);
    srand((unsigned)getpid());

    int sock = can_open(ifname);
    if (sock < 0) return 1;

    struct timespec next;
    clock_gettime(CLOCK_MONOTONIC, &next);
    /* Run the schedule JITTER_NS early. Each frame then waits a random
     * 0..2*JITTER_NS after waking, so it is sent at its ideal time
     * +/- JITTER_NS. */
    if (next.tv_nsec < JITTER_NS) { next.tv_sec--; next.tv_nsec += 1000000000L; }
    next.tv_nsec -= JITTER_NS;

    uint8_t counter = 0;
    double  t = 0;

    while (running) {
        double rpm = 3400.0 + 2600.0 * sin(t) + (rand() % 41 - 20);
        if (rpm < RPM_MIN) rpm = RPM_MIN;
        if (rpm > RPM_MAX) rpm = RPM_MAX;

        uint8_t data[8];
        can_pack(data, (uint16_t)rpm, counter++);

        usleep((useconds_t)(rand() % (2 * JITTER_NS / 1000 + 1)));
        if (can_send(sock, CAN_ID, data, 8) < 0)
            perror("rpm_ecu: can_send");

        t += RPM_RATE;
        sleep_until(&next, PERIOD_NS);       /* absolute time, no drift */
    }

    close(sock);
    return 0;
}
