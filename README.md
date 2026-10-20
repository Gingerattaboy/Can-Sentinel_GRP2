# Can-Sentinel_GRP2
Automotive ECU Intrusion Detection System

## Build

From the repo root:

```
make -C c all
```

This builds all four ECUs into `c/build/`.

To build one ECU by hand:

```
gcc -Wall -Wextra -O2 -o rpm_ecu c/rpm_ecu.c c/can_common.c -lm
gcc -Wall -Wextra -O2 -o speed_ecu c/speed_ecu.c c/can_common.c -lm
```

Notes:
- `-lm` is needed because the ECUs use `sin()`.
- Do not use `-std=c99` or `-std=c11`: `clock_gettime`, `struct timespec` need GNU/POSIX features.

## Brake ECU and attacker (Member 2)

The Brake ECU (`c/brake_ecu.c`) sends ID `0x500` every 20 ms. Byte 0 is the brake level (0 to 100), and byte 7 is the rolling counter. `make -C c all` builds it into `c/build/` together with the other ECUs.

`c/can_attacker.c` injects spoofed frames on vcan0 so we can test detection.

**Safety:** it refuses to start on any interface whose name does not begin with `vcan` (exit code 3).

### Usage

Run from the repo root, with the `data/` folder existing:

```
./c/build/can_attacker -m flood|insert [-i vcan0] [-r period_ms] [-d seconds] [-l logfile]
```

| Option | Meaning | Default |
|--------|---------|---------|
| `-m` | `flood` (spoofed brake frames, ID 0x500) or `insert` (extra spoofed RPM frames, ID 0x100) | required |
| `-i` | interface, must start with `vcan` | `vcan0` |
| `-r` | send period in ms | 1 (flood), 5 (insert) |
| `-d` | duration in seconds | 10 |
| `-l` | attack log file | `data/attack_log.csv` |

Examples:

```
./c/build/can_attacker -m flood -d 5
./c/build/can_attacker -m insert -d 10
```

### Attack log

Each run appends one row to `data/attack_log.csv`:

```
start_ts,end_ts,mode,target_id
```

Timestamps are epoch seconds, the same clock as the logger. `start_ts` is taken just before the first frame and `end_ts` just after the last one. Delete or archive the file between recording sessions so test runs do not end up in the dataset.

### Notes

- Flood sends 1000 frames per second on 0x500, alongside the real Brake ECU. If frames go missing during recording, use `-r 2`.
- Spoofed frames look valid. Detection relies on frequency, timing and entropy, not payload values.
- Ctrl+C stops an attack early and still writes the log row.
