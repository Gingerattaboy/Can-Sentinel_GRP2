# CAN-Sentinel: Automotive ECU Intrusion Detection System

A virtual car network (`vcan0`) with simulated ECUs, a logger that records the traffic into a CSV file,
and (in later weeks) an attacker script, a machine-learning detector and a dashboard.

**Week 1 goal:** a working virtual car network with four simulated ECUs, plus a CSV dataset of normal traffic.

## Team

| Member | Name | Focus area |
|--------|------|------------|
| Member 1 | Abdul Wahid | Infrastructure and testing: vcan0 setup, packet-loss test, README |
| Member 2 | Hudaa | Shared C library, RPM ECU, Speed ECU |
| Member 3 | Nilesh Gupta | Steering ECU, Temperature ECU, Makefile, launcher |
| Member 4 | Deepak Panwar | Python logger, data checker, dataset |

The values every part of the project must agree on (CAN IDs, rates, frame layout, CSV columns) are in
[`docs/contract.md`](docs/contract.md). Change them only with team agreement.

## Repository layout

```
Makefile    builds all four ECUs into build/
c/          ECU source files and the shared CAN library (can_common.h/.c)
build/      compiled ECUs (created by make, not committed)
python/     logger.py, check_data.py, make_demo_dataset.py, requirements.txt
data/       normal_traffic.csv (real recording), demo_traffic.csv (synthetic demo)
docs/       contract.md and notes
scripts/    setup_vcan.sh, run_all_ecus.sh, packet_loss_test.sh
```

## 1. Requirements

- Ubuntu 22.04 or 24.04 on a **virtual machine (VirtualBox, VMware) or a native install**.
  Recommended VM size: 2 CPUs, 4 GB RAM, 30 GB disk. Use 24.04 LTS (or 22.04 LTS) and the same version as the rest of the team.
- Packages:

```bash
sudo apt update
sudo apt install -y can-utils git build-essential python3-pip python3-venv
```

### WSL caveat (Windows users, please read)

**Do not use WSL.** `vcan` is a Linux kernel module and the default WSL2 kernel does not include CAN support,
so `sudo modprobe vcan` typically fails and `candump` reports `Address family not supported by protocol`.
The original WSL (WSL1) has no real kernel at all. Building a custom WSL2 kernel is possible but slow,
can break other tools such as Docker Desktop, and is not supported by this team.
Google Cloud Shell, Colab and GitHub Codespaces are containers that share the host kernel, so they usually fail too.
**Use an Ubuntu VM.** Quick check on any machine:

```bash
sudo modprobe vcan && echo "vcan available" || echo "vcan NOT available: use an Ubuntu VM"
```

## 2. Get the code

```bash
git clone https://github.com/Gingerattaboy/Can-Sentinel_GRP2.git
cd Can-Sentinel_GRP2
```

If a script is not executable, run `chmod +x scripts/*.sh` once.

## 3. Set up the virtual CAN network

```bash
./scripts/setup_vcan.sh
```

The script loads the `vcan` kernel module, creates `vcan0` if it does not exist and brings it up.
It is safe to run more than once. Give it another name with `./scripts/setup_vcan.sh vcan1`.

### Test the network

Open two terminals.

```bash
candump vcan0                      # terminal 1: listen
cansend vcan0 123#DEADBEEF         # terminal 2: send one frame
```

Terminal 1 should print a line like `vcan0  123   [4]  DE AD BE EF`. If it does, `vcan0` works.

| Problem | Fix |
|---------|-----|
| `candump: command not found` | `sudo apt install -y can-utils` |
| `Cannot find device "vcan0"` | Run `./scripts/setup_vcan.sh` first |
| `modprobe: FATAL: Module vcan not found` | `sudo apt install -y linux-modules-extra-$(uname -r)`, then run the setup script again. If it still fails, use a VirtualBox VM |
| `Permission denied` on a script | `chmod +x scripts/*.sh` |
| Nothing shows in `candump` | Check both commands use `vcan0` and that `candump` was started first |

## 4. Build and run the ECUs

```bash
make all                           # run from the repo root: builds all four ECUs into build/
./scripts/run_all_ecus.sh          # checks vcan0, builds, then starts all four ECUs
```

Watch the traffic in another terminal with `candump vcan0` (or `candump -td vcan0` to see the time gap between frames).
Press Ctrl+C in the launcher's terminal to stop all four ECUs. `make clean` removes the `build/` folder.

The Makefile builds with `-std=gnu11` and links `-lm`. Do not switch to `-std=c99` or `-std=c11`:
`clock_nanosleep`, `CLOCK_MONOTONIC` and `M_PI` need GNU/POSIX features.

| ECU | CAN ID | Period | Rate | Signal | Raw value range | Source |
|-----|--------|--------|------|--------|-----------------|--------|
| RPM | `0x100` | 10 ms | 100 Hz | Engine RPM | 800 to 6000 | `c/rpm_ecu.c` |
| Speed | `0x200` | 20 ms | 50 Hz | Speed in km/h | 0 to 180 | `c/speed_ecu.c` |
| Steering | `0x300` | 50 ms | 20 Hz | Steering angle, 500 = straight | 0 to 1000 | `c/steering_ecu.c` |
| Temperature | `0x400` | 100 ms | 10 Hz | Coolant temp in 0.1 deg C (853 = 85.3 C) | 700 to 1100 | `c/temp_ecu.c` |

### Frame format

Every frame has DLC 8 and a standard 11-bit ID.

| Byte | Content |
|------|---------|
| 0 | Value, high byte (big-endian) |
| 1 | Value, low byte |
| 2 | Rolling counter, 0 to 255, wraps around |
| 3 to 7 | Padding `0x00` |

Signals drift smoothly (sine waves with a small random wobble) and each send time has about +/- 0.5 ms of random
jitter around an absolute schedule, so the rates do not drift. The shared library in `c/can_common.c`
provides `can_open`, `can_send`, `can_pack` and `sleep_until`.

### Check the ECU output

With all four ECUs running, capture 4000 frames and check the value range and rolling counter of every ID:

```bash
candump -L -n 4000 vcan0 > /tmp/run.log
python3 - <<'EOF'
import collections
last, bad, rng = {}, collections.Counter(), {}
for line in open("/tmp/run.log"):
    _, _, f = line.split()
    cid, data = f.split("#")
    v, c = int(data[:4], 16), int(data[4:6], 16)
    if cid in last and (c - last[cid]) % 256 != 1:
        bad[cid] += 1
    last[cid] = c
    lo, hi = rng.get(cid, (v, v))
    rng[cid] = (min(lo, v), max(hi, v))
for cid in sorted(rng):
    print(cid, "value range", rng[cid], "counter gaps:", bad[cid])
EOF
```

Expected: value ranges inside the table above and **0 counter gaps** for every ID (the counter in byte 2 goes up
by 1 on every frame, so a gap means a frame was lost).

### Test status

| Environment | Ubuntu version | Result | Tested by | Date |
|-------------|----------------|--------|-----------|------|
| VirtualBox VM | (fill in with `lsb_release -d`) | (pass / fail) | (name) | (date) |
| Hudaa's Ubuntu VM | (unknown) | Reported OK, not yet independently verified | Hudaa | (date) |

Fill in a row only after running the check above yourself.

## 5. Record normal traffic (logger)

One-time Python setup (Ubuntu 24.04 does not allow `pip install` outside a virtual environment):

```bash
python3 -m venv .venv
source .venv/bin/activate          # repeat in every new terminal
pip install -r python/requirements.txt
```

Start the ECUs first, then run the logger in a second terminal:

```bash
python python/logger.py --duration 600 -o data/normal_traffic.csv
```

| Option | Default | Meaning |
|--------|---------|---------|
| `-o`, `--output` | `data/normal_traffic.csv` | Output CSV file |
| `-c`, `--channel` | `vcan0` | CAN interface to read |
| `-d`, `--duration` | `0` | Seconds to record; `0` records until Ctrl+C |
| `--force` | off | Overwrite the output file if it already exists |

The logger never overwrites an existing file unless you pass `--force`. Ctrl+C stops it cleanly: every row is
already written to disk and the CAN interface is closed properly. Only standard data frames are recorded.

A 10-minute recording with all four ECUs is about 108,000 rows (roughly 60,000 for `0x100`, 30,000 for `0x200`,
12,000 for `0x300` and 6,000 for `0x400`).

### CSV format

One header row, then one row per frame, comma separated. This matches `docs/contract.md`.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `timestamp` | float | Seconds since epoch, as reported by python-can | `1792334936.595389` |
| `can_id` | string | Hex with `0x` prefix, lowercase | `0x100` |
| `dlc` | int | Data length, always 8 | `8` |
| `data_hex` | string | The 8 data bytes as 16 uppercase hex characters, no spaces | `0BB8010000000000` |
| `label` | int | `0` = normal traffic, `1` = attack (used from Week 2) | `0` |

Example rows:

```
timestamp,can_id,dlc,data_hex,label
1792334936.595389,0x100,8,0BB8010000000000,0
1792334936.605412,0x100,8,0BB9020000000000,0
```

### Check the data

```bash
python python/check_data.py                    # checks data/normal_traffic.csv
python python/check_data.py data/other.csv     # checks another file
```

It validates the format (columns, DLC 8, 16 hex characters, label 0 or 1, known IDs, increasing timestamps),
then prints the frame count and average gap per ID and marks each ID `PASS` or `CHECK`.
An ID is flagged if its average gap is more than 10% away from its expected period.
At most 20 format errors are shown.

| Exit code | Meaning |
|-----------|---------|
| 0 | All checks passed |
| 1 | File problem or format errors |
| 2 | Format is fine, but a rate is off or there is too little data |

### Demo dataset (synthetic)

`data/demo_traffic.csv` is a **synthetic** 10-minute dataset (108,000 frames) generated by
`python/make_demo_dataset.py`. It simulates the four ECUs using the contract values (IDs, periods, ranges,
byte layout, rolling counter, +/- 0.5 ms jitter) and exists only to develop and test the checker and the Week 2
machine-learning code before the real recording is available. It is **not** a recording and is not the Week 1
dataset. The real recording is `data/normal_traffic.csv`, made with `logger.py` while the real ECUs run.

```bash
python python/make_demo_dataset.py                                   # 10 minutes, seed 42
python python/make_demo_dataset.py -d 300 -o data/demo_traffic.csv --seed 1
python python/check_data.py data/demo_traffic.csv
```

## 6. Packet-loss test

With the ECUs running:

```bash
./scripts/packet_loss_test.sh [interface] [seconds] [tolerance_percent]
./scripts/packet_loss_test.sh vcan0 60 2       # the defaults
```

It records `vcan0` with `candump` for 60 seconds, counts the frames per CAN ID, compares them with the number
expected from the contract rates and prints PASS or FAIL for each ID. A few extra frames at the edges of the
time window are normal. Paste the final table into the mid-project review notes.

## 7. Team workflow

- Work on your own branch (for example `m2-rpm-speed-ecu`) and never commit directly to `main`.
- Open a pull request for every change. Another member reviews it before it is merged.
- Review pairs: Member 2 and Member 3 review each other's C code; Member 1 and Member 4 review each other's scripts.
- Use **Squash and merge**, then delete the branch and start the next piece from a fresh `git pull` on `main`.
- Pull `main` before starting work each day.
- Anything that fails the data check is fixed by the person who owns it.
- Never commit passwords, keys or private data.

## 8. Week 1 checklist

- [x] `vcan0` can be set up with one script (`scripts/setup_vcan.sh`)
- [ ] All four ECUs run together and `candump` shows all four IDs (reported by Hudaa, to be verified)
- [ ] `data/normal_traffic.csv` recorded with `logger.py` from the real ECUs (5 to 10 minutes, agreed format)
- [ ] `check_data.py` confirms every ID is within tolerance on the final dataset
- [ ] Packet-loss test run and result saved
- [ ] A fresh clone can follow this README from scratch
