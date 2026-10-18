/*
 * temp_ecu.c  -  Engine temperature ECU simulator (Member 3)
 *
 * CAN ID : 0x400      Period : 100 ms     DLC : 8
 * Frame  : bytes 0-1 = temperature in 0.1 degC units, big-endian
 *                      (e.g. 853 = 85.3 C)
 *          byte 2    = rolling counter, bytes 3-7 = padding (0x00)
 *
 * Temperature warms up from 60 C towards ~90 C, then wanders slowly
 * around that point (thermostat behaviour). Slow drift on purpose.
 */
#include "can_common.h"

#include <math.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

#define CAN_IFACE    "vcan0"
#define CAN_ID       0x400
#define PERIOD_NS    100000000L   /* 100 ms */
#define JITTER_NS    500000L      /* +/- 0.5 ms */
#define START_TEMP   60.0         /* degC */
#define TARGET_TEMP  90.0         /* degC */
#define WARMUP_RATE  0.002        /* fraction of the gap closed per tick */

static volatile sig_atomic_t running = 1;
static void on_signal(int sig) { (void)sig; running = 0; }

static void ts_add_ns(struct timespec *t, long ns)
{
    t->tv_nsec += ns;
    while (t->tv_nsec >= 1000000000L) { t->tv_nsec -= 1000000000L; t->tv_sec++; }
    while (t->tv_nsec < 0)            { t->tv_nsec += 1000000000L; t->tv_sec--; }
}

static long rand_symmetric(long max) { return (rand() % (2 * max + 1)) - max; }

int main(void)
{
    signal(SIGINT,  on_signal);
    signal(SIGTERM, on_signal);
    srand((unsigned)time(NULL) ^ 0x400);

    int sock = can_open(CAN_IFACE);
    if (sock < 0) { perror("temp_ecu: can_open (is vcan0 up?)"); return 1; }

    struct timespec next;
    clock_gettime(CLOCK_MONOTONIC, &next);

    double  temp = START_TEMP;
    double  t = 0.0;
    uint8_t counter = 0;

    printf("temp_ecu: sending 0x%X every 100 ms on %s\n", CAN_ID, CAN_IFACE);

    while (running) {
        /* Move a little towards the target, add a slow oscillation
         * (thermostat cycling) and a tiny random nudge. */
        temp += (TARGET_TEMP - temp) * WARMUP_RATE;
        double reading = temp
                       + 1.5 * sin(2.0 * M_PI * t / 40.0)     /* 40 s cycle */
                       + (rand() % 11 - 5) * 0.02;            /* +/-0.1 C   */

        uint16_t value = (uint16_t)(reading * 10.0);          /* 0.1 C units */

        uint8_t data[8] = {0};
        data[0] = (uint8_t)(value >> 8);
        data[1] = (uint8_t)(value & 0xFF);
        data[2] = counter++;

        if (can_send(sock, CAN_ID, data, 8) < 0)
            perror("temp_ecu: can_send");

        ts_add_ns(&next, PERIOD_NS);
        struct timespec wake = next;
        ts_add_ns(&wake, rand_symmetric(JITTER_NS));
        clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &wake, NULL);
        t += PERIOD_NS / 1e9;
    }

    printf("\ntemp_ecu: stopped\n");
    return 0;
}
