#ifndef CAN_COMMON_H
#define CAN_COMMON_H
#include <stdint.h>
#include <time.h>

/* Open a raw SocketCAN socket bound to ifname (e.g. "vcan0").
   Returns the socket fd, or -1 on error. */
int can_open(const char *ifname);

/* Send one frame. Returns 0 on success, -1 on error. */
int can_send(int sock, uint32_t can_id, const uint8_t data[8], uint8_t dlc);

/* Pack a 16-bit value (big-endian) and a counter into an 8-byte payload. */
void can_pack(uint8_t data[8], uint16_t value, uint8_t counter);

/* Sleep until an absolute time, to avoid drift. */
void sleep_until(struct timespec *next, long period_ns);
#endif
