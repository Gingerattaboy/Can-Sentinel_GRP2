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

---

# WEEK 2 ADDITIONS: Attacker, Features and ML Detection

Status: DRAFT, pending team sign-off. Values marked **(proposed)** are not in the Week 2 plan and need the owner's
confirmation. Everything else comes from the Week 2 task split.

Last updated: 20.10.2026 |  Agreed by: Abdul Wahid [ ]  Hudaa [ ]  Nilesh Gupta [ ]  Deepak Panwar [ ]

## 10. Week 2 roles

| Member | Name | Week 2 focus |
|--------|------|--------------|
| Member 1 | Abdul Wahid | Data capture, labelling, packet-loss audit |
| Member 2 | Hudaa | C attacker, Brake ECU |
| Member 3 | Nilesh Gupta | Windowing, features, tests |
| Member 4 | Deepak Panwar | Model training and evaluation |

Cross-review pairs: Member 2 and 3 review each other's code; Member 1 and 4 review each other's scripts.

## 11. Safety rule

The attacker and every other attack or sniffing tool run on **`vcan0` only**. `can_attacker.c` must refuse to start
on any interface whose name does not begin with `vcan`.

## 12. New ECU: Brake

| ECU | CAN ID | Period | Rate | Owner | Source file | Signal |
|-----|--------|--------|------|-------|-------------|--------|
| Brake | `0x500` | 20 ms | 50 Hz | Member 2 | `c/brake_ecu.c` | Brake state (byte 0) |

Brake state values **(proposed, Member 2 to confirm)**: `0x00` = released, `0x01` = applied.
The Brake ECU is added to the Makefile and `scripts/run_all_ecus.sh`. All five ECUs run together from now on.

## 13. Frame layout per ID (replaces "3. Frame format")

Every frame has DLC 8 and a standard 11-bit ID. **The rolling counter is not in the same byte for every ID.**

| CAN ID | Bytes 0 and 1 | Byte 2 | Bytes 3 to 6 | Byte 7 |
|--------|---------------|--------|--------------|--------|
| `0x100` RPM | value, big-endian | rolling counter | `0x00` | `0x00` |
| `0x200` Speed | value, big-endian | rolling counter | `0x00` | `0x00` |
| `0x300` Steering | value, big-endian | rolling counter | `0x00` | `0x00` |
| `0x400` Temperature | value, big-endian | rolling counter | `0x00` | `0x00` |
| `0x500` Brake | byte 0 = brake state, byte 1 = `0x00` | `0x00` | `0x00` | **rolling counter** |

The counter runs 0 to 255 and wraps. Any script that reads it must use this table:

```python
COUNTER_BYTE = {0x100: 2, 0x200: 2, 0x300: 2, 0x400: 2, 0x500: 7}
```

Things that must be updated because of this: the README counter-check snippet, any packet-loss or data-quality
check that reads byte 2, and `check_data.py` (it must also know `0x500` every 20 ms). Spoofed attack frames may
use any payload (see section 14).

## 14. Attacker

| Item | Agreed value |
|------|--------------|
| Source file | `c/can_attacker.c` (Member 2) |
| Options | interface, mode, rate, duration. Names **(proposed)**: `--interface`, `--mode flood\|insert`, `--rate`, `--duration` |
| Mode A, `flood` | Spoofed brake frames on ID `0x500` every 1 ms (1000 frames per second) for the chosen duration, running alongside the real Brake ECU |
| Mode B, `insert` | Extra spoofed RPM frames on ID `0x100` every 5 ms, interleaved with the real 10 ms RPM frames (200 extra frames per second) |
| Payload | Spoofed frames may look like valid frames. Detection must rely on frequency, timing and entropy, not on payload values |
| Attack log | `data/attack_log.csv`, one row per run, appended (header written once) |

Attack log columns:

| Column | Meaning | Example |
|--------|---------|---------|
| `start_ts` | Epoch seconds when the attack started (same clock as the logger timestamps) | `1792300030.120000` |
| `end_ts` | Epoch seconds when the attack ended | `1792300050.121500` |
| `mode` | `flood` or `insert` **(proposed spelling)** | `flood` |
| `target_id` | Targeted CAN ID, hex with `0x` prefix | `0x500` |

Member 2 should also print the number of frames sent at exit (used for the packet-loss audit).
Clock check: the attacker and logger must both use epoch real-time. Member 1 verifies this with one short run
before any real recording.

## 15. Datasets, labels and recording rules

| File | Contents | Owner |
|------|----------|-------|
| `data/normal_v2.csv` | 10 minutes of normal traffic, all five ECUs, attacker not running | Member 1 |
| `data/attack_flood_1.csv` to `_3.csv` | 3 flood recordings, different durations | Members 1 and 2 |
| `data/attack_insert_1.csv` to `_3.csv` | 3 insertion recordings, different durations | Members 1 and 2 |
| `data/features_*.csv` | Window features for every recording | Member 3 |
| `models/iforest.joblib` | Trained model | Member 4 |

Recording protocol **(proposed)**: each attack recording is about 90 seconds with all ECUs running. The attacker starts
about 30 seconds in and runs for 10, 20 or 30 seconds, so every file has normal traffic before and after the attack.
`attack_flood_1` and `attack_insert_1` are the validation runs used for tuning. The other four runs are used only for
final numbers.

Labelling rule (frame level, done by `scripts/label_data.py`, or `python/label_data.py`):
- A frame has `label = 1` if `start_ts <= timestamp <= end_ts` for any row of `attack_log.csv`, otherwise `0`.
  This also applies to the real ECU frames that happen to fall inside an attack interval.
- A **window** has `label = 1` if it overlaps any attack interval.
- Attack recordings are never used for training.

## 16. Windows and features

| Item | Agreed value |
|------|--------------|
| Window | 200 ms, non-overlapping. Option name `--window-ms` (sliding windows come in Week 3) |
| Window start **(proposed)** | Windows start at the first frame of the recording; the last partial window is dropped |
| Feature order | `total_count`, `unique_ids`, `count_0x100`, `count_0x200`, `count_0x300`, `count_0x400`, `count_0x500`, `mean_gap`, `std_gap`, `payload_entropy` |
| `mean_gap`, `std_gap` **(proposed)** | Mean and standard deviation, in seconds, of the gaps between consecutive frames of all IDs in the window. A window with fewer than 2 frames gets `mean_gap` = window length and `std_gap` = 0 |
| `payload_entropy` **(proposed)** | Shannon entropy in bits (0 to 8) of all payload bytes of all frames in the window |
| Features CSV columns **(proposed)** | `window_start`, the ten features above, then `label` when the input was labelled |

## 17. Training and evaluation rules

- Train on normal windows only. Split by time: the first 70 percent for training, the last 30 percent held out.
- `random_state = 42` in every script.
- Tune the threshold and contamination on one validation attack run. Report final numbers only on runs not used for tuning.
- Report precision, recall, F1, the confusion matrix and ROC AUC, and state the split in the results table.
- Compare two window sizes (for example 100 ms and 200 ms) using `--window-ms`.

## 18. Week 1 values that must be settled now

| Item | Status |
|------|--------|
| Temperature | Raw value in **0.1 deg C** (853 = 85.3 C), range 700 to 1100. Update the section 2 row, which still says deg C 70 to 110 |
| Steering range | Contract says 0 to 1000, centre 500. Nilesh's latest file uses a 32768 centre. **Decide one** and fix the other side |
| Temperature start | Must stay inside the range (72 C or above) |

## 19. Open questions (settle in the Day 1 meeting)

- [ ] Brake counter in byte 7 (section 13) accepted by everyone?
- [ ] Brake state values and attacker option names (sections 12 and 14)
- [ ] Which two runs are the validation runs?
- [ ] `mean_gap`, `std_gap`, `payload_entropy` definitions (section 16)
- [ ] Steering range and temperature units (section 18)

## Change log row to add to section 9

| Date | Change | Changed by |
|------|--------|------------|
| (date) | Added Week 2 sections 10 to 19; Brake ECU `0x500`; per-ID counter byte | Abdul Wahid |
