/*
 * speed_ecu.c  -  Vehicle speed ECU simulator (Member 2)
 *
 * CAN ID : 0x200      Period : 20 ms      DLC : 8
 * Frame  : bytes 0-1 = speed in km/h, 0..180 (big-endian)
 *          byte  2   = rolling counter (0..255, wraps), bytes 3-7 = 0x00
 *
 * Usage  : ./speed_ecu [interface]      (default interface: vcan0)
 * Jitter : each frame is sent at its ideal time +/- 0.5 ms (see contract).
 */
#include "can_common.h"

#include <math.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

#define CAN_ID     0x200
#define PERIOD_NS  20000000L      /* 20 ms */
#define JITTER_NS  500000L        /* +/- 0.5 ms */
#define SPEED_MIN  0.0
#define SPEED_MAX  180.0
#define SPEED_RATE 0.01           /* radians per frame: slower than the RPM */

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
        double speed = 90.0 + 90.0 * sin(t) + (rand() % 3 - 1);
        if (speed < SPEED_MIN) speed = SPEED_MIN;
        if (speed > SPEED_MAX) speed = SPEED_MAX;

        uint8_t data[8];
        can_pack(data, (uint16_t)speed, counter++);

        usleep((useconds_t)(rand() % (2 * JITTER_NS / 1000 + 1)));
        if (can_send(sock, CAN_ID, data, 8) < 0)
            perror("speed_ecu: can_send");

        t += SPEED_RATE;
        sleep_until(&next, PERIOD_NS);       /* absolute time, no drift */
    }

    close(sock);
    return 0;
}
