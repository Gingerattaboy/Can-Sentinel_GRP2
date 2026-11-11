# CAN-Sentinel: Automotive ECU Intrusion Detection System

CAN-Sentinel is a safe, fully simulated intrusion detection system for an automotive CAN bus. It runs
entirely on a virtual CAN interface (`vcan0`), generates realistic ECU traffic, injects attacks, detects them
live with a machine-learning model, shows the result on a desktop dashboard, and (as a bonus) demonstrates a
**simulated** countermeasure.

---

## Table of contents
1. [What it does](#1-what-it-does)
2. [Why CAN needs this](#2-why-can-needs-this)
3. [Architecture](#3-architecture)
4. [Repository layout](#4-repository-layout)
5. [Requirements and setup](#5-requirements-and-setup)
6. [Running the demo](#6-running-the-demo)
7. [Component reference](#7-component-reference)
8. [Protocols and data formats](#8-protocols-and-data-formats)
9. [Detection method](#9-detection-method)
10. [Suspect attribution](#10-suspect-attribution)
11. [Simulated countermeasure](#11-simulated-countermeasure)
12. [Latency: what "real-time" means here](#12-latency-what-real-time-means-here)
13. [Testing](#13-testing)
14. [Evaluation](#14-evaluation)
15. [Limitations and future work](#15-limitations-and-future-work)
16. [Team and workflow](#16-team-and-workflow)
17. [Troubleshooting](#17-troubleshooting)

---

## 1. What it does

| Stage | What happens |
|-------|--------------|
| Simulate | Simulated ECUs (engine, drivetrain, steering, cooling, brakes) broadcast periodic frames on `vcan0` |
| Attack | A `can_attacker` injects malicious frames (for example flooding or spoofing an ID) |
| Capture | A small C sniffer reads every frame with kernel timestamps and streams it to Python |
| Detect | A Python service computes sliding-window features and scores them with an Isolation Forest trained on normal traffic only |
| Explain | Each verdict names the **suspect ID**, which the dashboard maps to a system on a car diagram |
| Display | A PyQt5 dashboard shows a live frame table, a threat gauge (0 to 100), alerts and the car diagram |
| Defend (bonus) | A defender sends a quarantine command; a simulated victim ECU rate-limits the attacked ID |

## 2. Why CAN needs this

CAN was designed in the 1980s for closed, trusted in-vehicle networks. A CAN frame carries an ID, not a sender
address, and frames are broadcast to every node. There is no authentication, no encryption, and the 8-byte
payload leaves no room for message authentication codes. Any node on the bus can therefore:

- **Spoof** another ECU by sending frames with its ID
- **Flood** the bus with high-priority IDs (low IDs win arbitration) to starve legitimate traffic
- **Replay** captured frames
- **Fuzz** IDs and payloads

Because the protocol itself cannot stop these, an intrusion detection system watches the traffic for behaviour
that does not match normal operation.

## 3. Architecture

```
 ECUs + attacker                                                       
 (vcan0)                                                               
    |                                                                  
    v                                                                  
 +-----------------+  21-byte records   +-----------------------+  JSON lines   +---------------+
 | Sniffer         | -----------------> | Inference service     | ------------> | Dashboard     |
 | C, SocketCAN    |  frames socket     | Python, scikit-learn  | events socket | PyQt5         |
 +-----------------+                    +-----------------------+               +---------------+
                                                   |
                                                   | verdict events
                                                   v
                                           +---------------+  control frame 0x7F0  +-------------+
                                           | Defender      | --------------------> | Victim ECU  |
                                           | Python        |        (vcan0)        | C (brakes)  |
                                           +---------------+                       +-------------+
```

- **Frames socket:** `/tmp/can_sentinel_frames.sock` (Unix domain, `SOCK_STREAM`). The inference service is the server, the sniffer is the client.
- **Events socket:** `/tmp/can_sentinel_events.sock` (Unix domain, newline-delimited JSON). The inference service is the server; the dashboard and defender are clients.
- **Start order:** inference service, then sniffer, then dashboard. `scripts/run_demo.sh` does this for you.

## 4. Repository layout

The Week 1 contract fixes the top-level folders: `c/ python/ data/ docs/ scripts/`. Later weeks add `models/` and
`tests/`. Files marked (M1) to (M4) are owned by that team member for the week named.

```
CAN-Sentinel/
├── README.md
├── requirements.txt              # pinned dependencies (python-can, PyQt5, scikit-learn, numpy, pandas, joblib, ...)
├── Makefile                      # builds all C programs (set the source paths to match your layout)
├── c/
│   ├── can_common.h / .c         # W1 (M2) shared SocketCAN helper
│   ├── rpm_ecu.c  speed_ecu.c    # W1 (M2) IDs 0x100 and 0x200
│   ├── steering_ecu.c temp_ecu.c # W1 (M3) IDs 0x300 and 0x400
│   ├── brake_ecu.c               # W2 (M2) ID 0x500
│   ├── can_attacker.c            # W2 (M2) flood and insertion attacks; W4 adds the 0xA5 tag
│   ├── sniffer.c                 # W3 (M1) SocketCAN to Unix socket sender
│   └── victim_ecu.c              # W4 (M2) simulated brake receiver with quarantine rate limiter
├── python/
│   ├── logger.py  check_data.py  # W1 (M4) recording and rate check
│   ├── label_data.py             # W2 (M1) adds the label column from attack_log.csv
│   ├── features.py               # W2 (M3) windowing and features; shared by training and live inference
│   ├── train_model.py evaluate.py# W2 (M4) Isolation Forest training and evaluation
│   ├── inference_service.py      # W3 (M2) frame receiver, scoring, event publisher
│   ├── attribution.py            # W4 (M1) per-ID baseline and suspect scoring
│   ├── defender.py               # W4 (M1) verdicts to quarantine commands on vcan0
│   ├── benchmark_latency.py      # W3 (M4) transport and detection latency
│   └── dashboard/                # W3/W4 (M3, M4) PyQt5 window, table, gauge, alerts, car diagram
├── data/
│   ├── normal_traffic.csv  normal_v2.csv          # normal recordings (v2 includes the Brake ECU)
│   ├── attack_flood_N.csv  attack_insert_N.csv    # labelled attack recordings
│   ├── attack_log.csv                              # attacker ground truth: start_ts, end_ts, mode, target_id
│   ├── features_*.csv                              # window features
│   ├── defense_log.csv  victim_stats.csv           # W4 defender and victim outputs
├── models/
│   ├── iforest.joblib            # trained Isolation Forest
│   └── baseline_stats.json       # per-ID normal mean and std, for attribution
├── scripts/
│   ├── setup_vcan.sh  packet_loss_test.sh  run_all_ecus.sh      # W1, W2
│   ├── run_demo.sh               # W3/W4 (M4) starts everything in order; supports --attack
│   └── demo_defense.sh           # W4 (M2) attack without and with the defence
├── tests/
│   ├── test_features.py          # W2 (M3)
│   ├── test_defender.py  test_attribution.py  sample_events.jsonl   # W4 (M1)
│   └── mock_server.py  mock_sniffer.py  mock_events_server.py       # W3 mocks (M1, M2, M3)
└── docs/
    ├── features.md               # W2 (M3) plain-language feature explanations
    ├── protocol.md               # W3 (M1) record format, sockets, events, control frame
    └── countermeasure.md         # W4 (M1) defender logic and the simulation disclosure
```

## 5. Requirements and setup

**Platform:** Linux with SocketCAN support (an Ubuntu desktop VM is recommended). The dashboard needs a display,
so a bare server or WSL without an X server will not work.

**System packages**
```bash
sudo apt update
sudo apt install build-essential can-utils python3 python3-venv python3-pip iproute2
```

**Python environment**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Virtual CAN interface** (repeat after every reboot)
```bash
scripts/setup_vcan.sh       # loads vcan, creates and brings up vcan0 (or run the three commands below)
# sudo modprobe vcan; sudo ip link add dev vcan0 type vcan; sudo ip link set up vcan0
ip link show vcan0          # should show vcan0 and state UP/UNKNOWN
candump vcan0               # quick check that frames are flowing
```

> **WSL2 caveat:** WSL2 kernels often do not include the `vcan` module. Use an Ubuntu VM or a dual boot.

**Build the C programs**
```bash
make
```

**Record data and train the model** (only needed if `models/iforest.joblib` and `models/baseline_stats.json` are not in the repo)
```bash
scripts/run_all_ecus.sh                                   # start all ECUs
python3 python/logger.py --out data/normal_v2.csv         # Ctrl+C saves the file
python3 python/check_data.py data/normal_v2.csv           # every ID should be at its expected rate
python3 python/features.py <csv> --window-ms 200          # CSV to features CSV (batch mode)
python3 python/train_model.py                             # normal windows only, time split, random_state 42
python3 python/evaluate.py                                # precision, recall, F1, confusion matrix, ROC AUC
python3 python/attribution.py fit --csv data/normal_v2.csv --out models/baseline_stats.json
```
(Option names above follow the task plans; check each script's `--help` for the exact flags.) The attribution
baseline uses the default CSV columns `timestamp` and `can_id`, which match the agreed CSV format. Fit it on the
same normal data as the model.

## 6. Running the demo

**One command (recommended)**
```bash
scripts/run_demo.sh            # normal traffic only
scripts/run_demo.sh --attack   # also starts the attacker
```

**Manually, in separate terminals**
```bash
# 1. inference service
python3 inference_service.py
# 2. sniffer
./sniffer
# 3. dashboard
python3 dashboard/main.py
# 4. traffic: all five ECUs, then optionally the attacker
scripts/run_all_ecus.sh
./can_attacker <interface> <mode> <rate> <duration>   # vcan0 only; modes: flood (0x500) or insert (0x100)
# 5. (bonus) defender and victim ECU
./victim_ecu &
python3 defender.py
```

**What you should see**
1. Normal traffic: the frame table scrolls, the gauge stays green (0 to 39).
2. Attack starts: the gauge climbs through amber (40 to 69) to red (70 to 100), an alert banner appears, the
   alert history gains entries, and the car diagram highlights the suspect system.
3. With the defender running: after 3 anomalous verdicts a "Quarantine Active" indicator appears; the victim ECU
   starts dropping excess attacker frames. After 10 clean verdicts the quarantine is released.

**Before and after defence**
```bash
scripts/demo_defense.sh        # attack without the defence, then with it
```

**Stopping:** press `Ctrl+C` in the demo script's terminal. It stops all processes and removes the socket files.

## 7. Component reference

### Sniffer (`sniffer.c`)
Opens a raw SocketCAN socket on `vcan0`, reads frames with kernel timestamps (`SO_TIMESTAMP`), packs each into a
21-byte record and sends it to the frames socket.

- All socket calls are non-blocking and whole records are queued (about 4096 records), so a partial send can never leave half a record in the stream.
- It **never blocks the bus**. If the queue is full or the service is not connected, the frame is dropped and counted.
- If the service disconnects, any half-sent data is discarded and the sniffer reconnects every 500 ms.
- Prints once per second: `fps, sent, drops (queue_full, no_link), totals, link up/down`.
- `-s PATH` changes the socket path. `-i` accepts only `vcan0`; anything else is refused.

### Inference service (`inference_service.py`)
Server for the frames socket. Keeps a ring buffer, computes sliding-window features (200 ms window, 100 ms step)
by **importing** `features.py`, scores each window with the Isolation Forest, converts the score to a threat
level, adds the suspect ID, and publishes `frames` and `verdict` events. Logs per-window inference time. Deletes
a stale socket file before binding.

### Dashboard (`dashboard/`)
PyQt5 application.
- **Event reader:** a `QThread` reads the events socket so the GUI never blocks; shows a connection status indicator.
- **Frame table:** `QTableView` with a model, last 500 rows, repainted at most 10 times per second; rows whose ID appears in an anomalous verdict are highlighted.
- **ThreatGauge:** custom-painted 0 to 100 gauge with green, amber and red zones.
- **Alert panel:** banner plus history (time, threat level, window counts), with CSV export and a clear button.
- **CarDiagram:** four regions (Engine, Drivetrain, Steering, Brakes); the suspect's region turns red while verdicts are anomalous.
- **Quarantine Active indicator:** shown when a `0x7F0` frame with command 1 appears in the frame stream.
- A reset shortcut, a consistent theme, and clear error states (for example when disconnected).

### Attribution (`attribution.py`)
Saves per-ID baseline statistics at training time and names the suspect ID for each verdict. See [section 10](#10-suspect-attribution).

### Defender (`defender.py`)
Reads verdicts and sends quarantine commands. See [section 11](#11-simulated-countermeasure).

```
python3 defender.py [--on-after 3] [--off-after 10] [--cooldown 1.0]
                    [--events-sock PATH] [--log data/defense_log.csv]
                    [--replay FILE.jsonl] [--dry-run]
```

### Victim ECU (`victim_ecu.c`)
Models a brake receiver on ID `0x500`. Listens for the control ID `0x7F0`. While quarantine is on it accepts at
most one `0x500` frame per 20 ms and drops the rest. Writes per-second statistics (accepted, dropped, spoofed
applied) to `data/victim_stats.csv`. **This simulates an error-frame defence.**

### Benchmark (`benchmark_latency.py`)
Measures transport time (sniffer kernel timestamp to service receipt) and detection delay (window end to verdict).

## 8. Protocols and data formats

Full details are in [`docs/protocol.md`](docs/protocol.md). Summary:

**Frame record** (sniffer to service): 21 bytes, little-endian, no padding. Python format `<dIB8s`.

| Offset | Size | Type | Field |
|-------:|-----:|------|-------|
| 0 | 8 | float64 | timestamp (seconds since epoch) |
| 8 | 4 | uint32 | CAN ID |
| 12 | 1 | uint8 | DLC |
| 13 | 8 | bytes | data, zero-padded |

**Events** (service to dashboard and defender), one JSON object per line:
```json
{"type": "frames", "items": [[ts, id, dlc, "data_hex"], ...]}
{"type": "verdict", "window_start": ts, "score": s, "threat_level": 0-100,
 "is_anomaly": true, "counts": {"256": 20, "1280": 61}, "suspect_id": 1280, "suspect_z": 14.2}
```
`frames` events are sent every 100 ms; `verdict` events every window step.

**Simulated ECUs** (all frames DLC 8; value in the first 2 bytes, big-endian; the remaining bytes are a rolling counter or padding; values drift smoothly with small timing jitter)

| ECU | CAN ID | Period |
|-----|-------:|-------:|
| RPM | `0x100` | 10 ms |
| Speed | `0x200` | 20 ms |
| Steering | `0x300` | 50 ms |
| Temperature | `0x400` | 100 ms |
| Brake | `0x500` | 20 ms (byte 0 = brake state, last byte = rolling counter) |

**Dataset CSV columns:** `timestamp, can_id, dlc, data_hex, label` (`label` 0 = normal, 1 = attack; epoch seconds).
**Attack log** (`data/attack_log.csv`): `start_ts, end_ts, mode, target_id`. A frame is label 1 if its timestamp falls
inside an attack interval; a window is label 1 if it overlaps one.

**Attacks** (vcan only; the attacker refuses any interface not named `vcan*`):
- **Mode A, flood:** spoofed brake frames on `0x500` every 1 ms for a chosen duration, alongside the real Brake ECU.
- **Mode B, insertion:** extra spoofed RPM frames on `0x100` every 5 ms, interleaved with the real 10 ms frames.
- Spoofed payloads may look valid. Detection relies on frequency, timing and entropy, **not** payload values.

**ID to system map**

| CAN ID | System |
|-------:|--------|
| `0x100` | Engine (RPM) |
| `0x200` | Drivetrain (speed) |
| `0x300` | Steering |
| `0x400` | Engine cooling (temperature) |
| `0x500` | Brakes |
| `0x7F0` | Quarantine control frame (defender to victim ECU) |

**Quarantine control frame:** CAN ID `0x7F0`, DLC 3. Bytes 0 and 1 are the target ID (big-endian); byte 2 is
`1` for quarantine on and `0` for off. Example: `7F0#050001` quarantines `0x500`.

**Ground-truth tag:** the attacker sets the last data byte to `0xA5`. The real Brake ECU counter wraps at `0x7F`
and never produces `0xA5`. **Only the evaluation uses this tag; the detector and defender never read it.**

Any change to the frame record or event format needs agreement from all four members, because both sides must
change together.

## 9. Detection method

- **Windows:** 200 ms (`--window-ms`). Training uses non-overlapping windows; live inference uses a sliding
  window with a 100 ms step.
- **Features** (computed by `features.py`, fixed order, shared by training and live inference; the service imports it and never copies it):
  `total_count, unique_ids, count_0x100, count_0x200, count_0x300, count_0x400, count_0x500, mean_gap, std_gap, payload_entropy`.
  Frequency comes from the counts, timing from the mean and standard deviation of inter-arrival gaps, and payload
  entropy from the byte distribution in the window. See `docs/features.md`.
- **Model:** Isolation Forest (`random_state` 42), trained on **normal windows only** with a time split (first 70 percent train, last 30 percent held out). Thresholds are tuned on one validation attack run; final numbers are reported only on runs not used for tuning. Attack recordings are never used for training. It learns what normal looks like and scores how
  unusual a window is, which means it needs no labelled attack data and can flag attack types it has not seen.
- **Threat level:** an integer 0 to 100 derived from the anomaly score, scaled with the min and max scores on
  normal data saved next to the model. 0 to 39 is green, 40 to 69 amber, 70 to 100 red.

## 10. Suspect attribution

The verdict says *that* something is wrong; attribution says *where*.

- **Training time:** `attribution.py fit` computes, for each ID, the mean and standard deviation of its count per
  200 ms window on normal data and saves them to `models/baseline_stats.json`.
- **Live:** for each window, the suspect is the ID whose count is furthest from its normal mean, measured in
  standard deviations (absolute z-score). The service adds `suspect_id` and `suspect_z` to the verdict.
- IDs never seen in normal traffic use a mean of 0, so an attacker injecting a new ID stands out. IDs that vanish
  from the window also count.
- A minimum standard deviation of 0.5 counts is applied, because strictly periodic IDs have almost zero variance
  and would otherwise produce huge z-scores from tiny deviations.

```python
from attribution import Attributor
attr = Attributor.load("models/baseline_stats.json")
verdict["suspect_id"], verdict["suspect_z"] = attr.suspect(verdict["counts"])
```

The z-score is shown so the reasoning is visible, and `suspect_id` should be checked against known attack runs.

## 11. Simulated countermeasure

> **This defence is simulated at application level on `vcan0`. It is not a real CAN error-frame implementation.**

**Why simulated.** On a physical bus, a node can destroy a frame in flight by driving a dominant bit, which
triggers an error frame; repeated errors push the sender's transmit error counter up until it goes
error-passive and then bus-off. That needs a real CAN controller and physical layer. `vcan0` is a software
loopback, so no bus-level arbitration or error signalling exists. The simulation imitates the *effect* only.

**Defender logic** (`defender.py`)
1. Read `verdict` events from the events socket.
2. **Quarantine ON** after `--on-after` (default 3) consecutive anomalous verdicts naming the **same** `suspect_id`.
3. **Quarantine OFF** after `--off-after` (default 10) consecutive clean verdicts. An anomaly resets the clean count.
4. Commands are sent as the `0x7F0` control frame.

**Safety limits**
- `vcan0` only; any other interface name is refused.
- Targets restricted to the five known IDs (`0x100` to `0x500`); anything else is refused and logged once.
- Cooldown between commands (`--cooldown`, default 1 second).
- Active quarantines are released when the defender exits.
- Every action (ON, OFF, REFUSED) is appended to `data/defense_log.csv`.

**Victim behaviour.** In quarantine, `victim_ecu` accepts at most one `0x500` frame per 20 ms and drops the
rest. Legitimate frames can be dropped too; this **collateral** is measured and reported, not hidden.

More detail: [`docs/countermeasure.md`](docs/countermeasure.md).

## 12. Latency: what "real-time" means here

Two different numbers, reported separately:

| Measure | Definition | Target |
|---------|------------|--------|
| **Transport latency** (per frame) | Service receive time minus sniffer kernel timestamp | Median under 1 ms |
| **Detection delay** (per window) | Window end to verdict | At most one window step (100 ms) plus inference time |

The detection decision is made per window, so it always arrives after the traffic it judges. **Do not claim
sub-millisecond detection.** Run `python3 benchmark_latency.py` to measure both.

## 13. Testing

```bash
python3 -m unittest discover -s tests          # defender and attribution unit tests

# sniffer without the real service
python3 tests/mock_server.py                    # terminal 1
./sniffer                                       # terminal 2
cansend vcan0 123#1122334455667788              # terminal 3
python3 tests/mock_server.py --close-after 3    # tests sniffer reconnect
python3 tests/mock_server.py --slow-ms 200      # tests drop counting (flood with: cangen vcan0 -g 1)

# defender without a bus
python3 defender.py --replay tests/sample_events.jsonl
```

Each stage can be tested against a mock of its neighbour: `mock_server.py` (stands in for the service),
`mock_sniffer.py` (replays a CSV as frame records), `mock_events_server.py` (replays events to the dashboard).

## 14. Evaluation

Five attack scenarios are run with and without the defence. For each, record:

| Metric | Meaning |
|--------|---------|
| Detection delay (s) | Attack start to first anomalous verdict |
| Attacker frames accepted by the victim | With and without the defence |
| Legitimate frames dropped (collateral) | Cost of the rate limiter |
| Quarantine duration | Time from ON to OFF |

The `0xA5` ground-truth tag identifies attacker frames for these counts. Results table: *(fill in from your runs)*.

## 15. Limitations and future work

- **Frequency-based detection** can be evaded by an attacker who copies the normal timing and payload patterns.
- **Detection is per window**, so there is an inherent delay of up to one step plus inference time.
- **The defence is a simulation.** A real defence would need CAN controller support and carries risk to legitimate traffic.
- Trained on simulated traffic; real vehicle traffic is more varied.
- Future work: payload-level and sequence features, supervised or hybrid models, running on real CAN hardware,
  message authentication (for example AUTOSAR SecOC).

## 16. Team and workflow

| Member | Name | Focus |
|--------|------|-------|
| 1 | Abdul Wahid | C sniffer, suspect attribution, defender, countermeasure docs |
| 2 | Hudaa | Inference service, C victim ECU, attacker tag, defence demo |
| 3 | Nilesh Gupta | PyQt window, live table, event reader, car diagram |
| 4 | Deepak Panwar | Threat gauge, alerts, polish, evaluation, packaging, report |

Rules:
- Each person works on their own branch; never commit directly to `main`.
- Every change goes through a pull request reviewed by another member. Cross-review pairs: Members 1 and 2; Members 3 and 4.
- Pull from `main` before starting work each day.
- Never commit passwords, keys or private data; use `.gitignore`.
- The inference service must reuse `features.py`; do not copy feature code.
- Feature freeze at the end of Day 5 of Week 4; after that only bug fixes and documentation.
- Keep all attack and sniffing tools on `vcan0` only.

## 17. Troubleshooting

| Problem | Fix |
|---------|-----|
| `interface vcan0 not found` | Run the three `modprobe` / `ip link` commands in [section 5](#5-requirements-and-setup); they must be repeated after a reboot |
| Sniffer prints `link=down` | The inference service is not running yet, or has not created its socket. Start the service first |
| Service will not start: address in use | A stale socket file. The service deletes it before binding; otherwise `rm /tmp/can_sentinel_*.sock` |
| Dashboard does not open | It needs a display. Use an Ubuntu desktop VM or a working X server |
| Dashboard shows "disconnected" | The inference service (events socket) is not running |
| Sniffer reports many `queue_full` drops | The detector is slower than the bus. This is expected back-pressure behaviour; report the drop rate |
| `make: *** missing separator` | Recipe lines in the Makefile must start with a tab, not spaces |
| `Permission denied` creating vcan0 | Use `sudo` |

---

*This project is a safe, isolated simulation. Do not point any of these tools at a real vehicle or a physical CAN bus.*
