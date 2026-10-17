#include "can_common.h"
#include <math.h>
#include <signal.h>
#include <stdlib.h>
#include <unistd.h>

static volatile int running = 1;
static void stop(int s) { (void)s; running = 0; }

int main(void) {
    signal(SIGINT, stop);
    srand(getpid());
    int sock = can_open("vcan0");
    if (sock < 0) return 1;

    struct timespec next;
    clock_gettime(CLOCK_MONOTONIC, &next);
    uint8_t counter = 0;
    double t = 0;

    while (running) {
        uint16_t value = (uint16_t)(90 + 90 * sin(t));   /* 0 to 180 km/h, every 20 ms */
        uint8_t data[8];
        can_pack(data, value, counter++);
        usleep(rand() % 1001);             /* random jitter, 0 to 1 ms after the slot */
        can_send(sock, 0x200, data, 8);
        t += 0.02;
        sleep_until(&next, 20000000L);     /* absolute time, no drift */
    }
    return 0;
}
