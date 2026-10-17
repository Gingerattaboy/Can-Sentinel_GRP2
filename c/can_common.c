#include "can_common.h"
#include <linux/can.h>
#include <linux/can/raw.h>
#include <sys/socket.h>
#include <sys/ioctl.h>
#include <net/if.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h>
#include <stdio.h>

int can_open(const char *ifname) {
    int s = socket(PF_CAN, SOCK_RAW, CAN_RAW);
    if (s < 0) { perror("socket"); return -1; }
    struct ifreq ifr;
    memset(&ifr, 0, sizeof(ifr));
    strncpy(ifr.ifr_name, ifname, IFNAMSIZ - 1);
    if (ioctl(s, SIOCGIFINDEX, &ifr) < 0) { perror("ioctl"); close(s); return -1; }
    struct sockaddr_can addr;
    memset(&addr, 0, sizeof(addr));
    addr.can_family = AF_CAN;
    addr.can_ifindex = ifr.ifr_ifindex;
    if (bind(s, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("bind"); close(s); return -1;
    }
    return s;
}

int can_send(int sock, uint32_t can_id, const uint8_t data[8], uint8_t dlc) {
    if (dlc > 8) return -1;
    struct can_frame f;
    memset(&f, 0, sizeof(f));
    f.can_id = can_id;
    f.can_dlc = dlc;
    memcpy(f.data, data, dlc);
    return write(sock, &f, sizeof(f)) == (ssize_t)sizeof(f) ? 0 : -1;
}

/* Byte 0 = value high byte, byte 1 = value low byte, byte 2 = counter,
   bytes 3 to 7 = 0x00 padding (see docs/contract.md). */
void can_pack(uint8_t data[8], uint16_t value, uint8_t counter) {
    memset(data, 0, 8);
    data[0] = value >> 8;
    data[1] = value & 0xFF;
    data[2] = counter;
}

static void normalize(struct timespec *t) {
    while (t->tv_nsec >= 1000000000L) { t->tv_nsec -= 1000000000L; t->tv_sec++; }
    while (t->tv_nsec < 0)            { t->tv_nsec += 1000000000L; t->tv_sec--; }
}

/* Moves the schedule forward by one period (so it never drifts), then sleeps
   until that exact time. */
void sleep_until(struct timespec *next, long period_ns) {
    next->tv_nsec += period_ns;
    normalize(next);
    clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, next, NULL);
}
