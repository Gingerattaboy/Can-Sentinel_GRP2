#ifndef CAN_COMMON_H
#define CAN_COMMON_H
#include <stdint.h>
#include <time.h>

int can_open(const char *ifname);
int can_send(int sock, uint32_t id, const uint8_t *data, uint8_t dlc);
void sleep_until_next(struct timespec *next, long period_ns, long jitter_ns);
#endif