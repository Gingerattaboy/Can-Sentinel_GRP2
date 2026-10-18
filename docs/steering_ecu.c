/*
 * steering_ecu.c  -  Steering ECU simulator (Member 3)
 *
 * CAN ID : 0x300      Period : 50 ms      DLC : 8
 * Frame  : bytes 0-1 = steering angle (big-endian, 32768 = straight ahead)
 *          byte  2   = rolling counter, bytes 3-7 = padding (0x00)
 *
 * The angle is a slow sine wave (a driver gently steering left/right)
 * plus a little random wobble, so the ML model sees a smooth pattern.
 */
#include "can_common.h"

#include <math.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

#define CAN_IFACE   "vcan0"
#define CAN_ID      0x300
#define PERIOD_NS   50000000L     /* 50 ms  */
#define JITTER_NS   500000L       /* +/- 0.5 ms */
#define CENTER      32768.0
#define AMPLITUDE   12000.0       /* max swing from centre */
#define SINE_PERIOD 8.0           /* seconds for one left-right cycle */

static volatile sig_atomic_t running = 1;
static void on_signal(int sig) { (void)sig; running = 0; }

/* Add ns nanoseconds to a timespec, keeping tv_nsec in [0, 1e9). */
static void ts_add_ns(struct timespec *t, long ns)
{
    t->tv_nsec += ns;
    while (t->tv_nsec >= 1000000000L) { t->tv_nsec -= 1000000000L; t->tv_sec++; }
    while (t->tv_nsec < 0)            { t->tv_nsec += 1000000000L; t->tv_sec--; }
}

/* Random number in [-max, +max]. */
static long rand_symmetric(long max) { return (rand() % (2 * max + 1)) - max; }

int main(void)
{
    signal(SIGINT,  on_signal);
    signal(SIGTERM, on_signal);
    srand((unsigned)time(NULL) ^ 0x300);

    int sock = can_open(CAN_IFACE);
    if (sock < 0) { perror("steering_ecu: can_open (is vcan0 up?)"); return 1; }

    struct timespec next;                 /* ideal schedule, no jitter */
    clock_gettime(CLOCK_MONOTONIC, &next);

    double  t = 0.0;                      /* simulated time in seconds */
    double  wobble = 0.0;                 /* small random-walk component */
    uint8_t counter = 0;

    printf("steering_ecu: sending 0x%X every 50 ms on %s\n", CAN_ID, CAN_IFACE);

    while (running) {
        /* --- compute the signal ------------------------------------ */
        wobble += (rand() % 41 - 20);            /* tiny random step    */
        wobble *= 0.95;                          /* pull back to zero   */
        double angle = CENTER
                     + AMPLITUDE * sin(2.0 * M_PI * t / SINE_PERIOD)
                     + wobble;
        if (angle < 0)      angle = 0;
        if (angle > 65535)  angle = 65535;
        uint16_t value = (uint16_t)angle;

        /* --- build the frame --------------------------------------- */
        uint8_t data[8] = {0};
        data[0] = (uint8_t)(value >> 8);         /* big-endian high byte */
        data[1] = (uint8_t)(value & 0xFF);       /* big-endian low byte  */
        data[2] = counter++;                     /* rolling counter      */

        if (can_send(sock, CAN_ID, data, 8) < 0)
            perror("steering_ecu: can_send");

        /* --- wait until the next slot (absolute time = no drift) --- */
        ts_add_ns(&next, PERIOD_NS);
        struct timespec wake = next;
        ts_add_ns(&wake, rand_symmetric(JITTER_NS)); /* jitter moves only
                                                        this one wake-up */
        clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &wake, NULL);
        t += PERIOD_NS / 1e9;
    }

    printf("\nsteering_ecu: stopped\n");
    return 0;
}
