[contract.md](https://github.com/user-attachments/files/33468584/contract.md)
# CAN-Sentinel: Shared Contract (Week 1)

This is the single source of truth for the C side (ECUs) and the Python side (logger).
If anything here changes, tell the whole team and update this file in a PR.

## Team

| Member | Name | Role | Focus area |
|--------|------|------|------------|
| Member 1 | Abdul Wahid | Infrastructure and Testing | Repo, vcan0 setup, packet-loss test, README |
| Member 2 | Hudaa | C ECUs, Part A | Shared library, RPM ECU, Speed ECU |
| Member 3 | Nilesh Gupta | C ECUs, Part B | Steering ECU, Temperature ECU, Makefile, launcher |
| Member 4 | Deepak Panwar | Python Logging and Data Quality | logger.py, check_data.py, dataset |

Last updated: 15 Oct 2026  |  Agreed by: Abdul Wahid [ ]  Hudaa [ ]  Nilesh Gupta [ ]  Deepak Panwar [ ] 

## 1. Network

| Item | Agreed value |
|------|--------------|
| CAN interface | `vcan0` |
| Setup script | `scripts/setup_vcan.sh` |
| Platform | Ubuntu (VM or native). WSL2 may lack the `vcan` module |

## 2. ECUs

| ECU | CAN ID | Period | Rate | Owner | Source file | Signal | Proposed range |
|-----|--------|--------|------|-------|-------------|--------|----------------|
| RPM | `0x100` | 10 ms | 100 Hz | Member 2 | `c/rpm_ecu.c` | Engine RPM | 800 to 6000 |
| Speed | `0x200` | 20 ms | 50 Hz | Member 2 | `c/speed_ecu.c` | Speed in km/h | 0 to 180 |
| Steering | `0x300` | 50 ms | 20 Hz | Member 3 | `c/steering_ecu.c` | Steering angle (offset-encoded) | 0 to 1000 (500 = centre) |
| Temperature | `0x400` | 100 ms | 10 Hz | Member 3 | `c/temp_ecu.c` | Coolant temp in deg C | 70 to 110 |

Timing jitter: about +/- 0.5 ms random, added by Member 2's ECUs (agree whether Member 3's ECUs do the same).
Use `clock_nanosleep` with absolute time to avoid drift.

## 3. Frame format

| Byte | Content |
|------|---------|
| 0 | Value, high byte (big-endian) |
| 1 | Value, low byte |
| 2 | Rolling counter, 0 to 255, wraps around |
| 3 to 7 | Padding `0x00` |

- DLC is always 8.
- Standard 11-bit IDs, no CAN FD.
- Values must drift smoothly (e.g. RPM rising and falling), never stay constant, so the Week 2 model has patterns to learn.

## 4. CSV format (logger output)

File: `data/normal_traffic.csv`

| Column | Type | Description |
|--------|------|-------------|
| `timestamp` | float | Seconds since epoch, as reported by python-can |
| `can_id` | string | Hex with prefix, e.g. `0x100` |
| `dlc` | int | Always 8 for now |
| `data_hex` | string | 16 hex characters, no spaces, e.g. `0BB8010000000000`-style (8 bytes) |
| `label` | int | `0` = normal traffic, `1` = attack (Week 2) |

One header row, one row per frame, comma separated.

## 5. Shared C library (`c/can_common.h`)

Proposed signatures (Members 2 and 3 to confirm on Day 1):

```c
// Open a raw SocketCAN socket bound to ifname (e.g. "vcan0").
// Returns the socket fd, or -1 on error.
int can_open(const char *ifname);

// Send one frame. Returns 0 on success, -1 on error.
int can_send(int sock, uint32_t can_id, const uint8_t data[8], uint8_t dlc);

// Pack a 16-bit value (big-endian) and a counter into an 8-byte payload.
void can_pack(uint8_t data[8], uint16_t value, uint8_t counter);

// Sleep until an absolute time, to avoid drift.
void sleep_until(struct timespec *next, long period_ns);
```

## 6. Data-quality rule (used by `check_data.py`)

An ID is flagged if its average gap is more than **10%** away from its expected period
(proposed; adjust after the first real run).

## 7. Repo layout

```
CAN-Sentinel/
  c/          ECU source, can_common.h/.c, Makefile
  python/     logger.py, check_data.py
  data/       normal_traffic.csv
  docs/       contract.md and notes
  scripts/    setup_vcan.sh, run_all_ecus.sh, packet_loss_test.sh
```

## 8. Open questions (settle in the Day 1 meeting)

- [ ] Signal ranges in section 2 OK?
- [ ] Do all four ECUs use the same jitter?
- [ ] Is the 10% rate tolerance OK?
- [ ] Final function signatures for `can_common.h`

## 9. Change log

| Date | Change | Changed by |
|------|--------|------------|
| | Initial version | Member 1 |
