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
- Do not use `-std=c99` or `-std=c11`: `clock_gettime`, `struct timespec` and `M_PI` need GNU/POSIX features.
