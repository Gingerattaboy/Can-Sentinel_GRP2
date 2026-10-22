# Feature Guide (Member 3)

The model never sees raw CAN frames. We cut the traffic into **200 ms windows**
(no overlap) and describe each window with 10 numbers. A normal window looks
like the same "fingerprint" every time; an attack changes the fingerprint.

**One normal 200 ms window should hold roughly:** 20 RPM + 10 Speed + 4 Steering
+ 2 Temperature + 10 Brake frames = about 46 frames.

| # | Feature | In plain words | Normal looks like | What an attack does |
|---|---------|----------------|-------------------|---------------------|
| 1 | `total_count` | How many frames arrived in the window | about 46, very steady | Flood: jumps to about 250. Insertion: about 85 |
| 2 | `unique_ids` | How many different CAN IDs were seen | 5 (all ECUs speaking) | Usually unchanged. The attacker copies IDs that already exist, so this alone cannot catch it |
| 3 | `count_0x100` | RPM frames in the window | about 20 (one every 10 ms) | Insertion: about 60 (extra frames every 5 ms) |
| 4 | `count_0x200` | Speed frames | about 10 (every 20 ms) | Unchanged in our two attacks |
| 5 | `count_0x300` | Steering frames | about 4 (every 50 ms) | Unchanged in our two attacks |
| 6 | `count_0x400` | Temperature frames | about 2 (every 100 ms) | Unchanged in our two attacks |
| 7 | `count_0x500` | Brake frames | about 10 (every 20 ms) | Flood: about 210 (a frame every 1 ms) |
| 8 | `mean_gap` | Average time between two frames, in ms | about 4.4 ms | Frames arrive faster, so the gap shrinks (flood: under 1 ms) |
| 9 | `std_gap` | How uneven those gaps are, in ms | about 4.7 ms (ECUs take turns) | A flood makes traffic very regular and fast, so the spread drops |
| 10 | `payload_entropy` | How varied the data bytes are, in bits (0 to 8) | about 3.3 bits (counters and drifting values) | Spoofed frames repeat similar bytes, so variety drops |

(Numbers above are typical values. Replace them with the real averages from
`data/features_normal_v2.csv` before the review.)

## Rules used when building the windows

- Windows start at the first frame of the recording and do not overlap.
- The last, incomplete window is dropped, because a short window would look like a fake dip in traffic.
- A window with no frames is kept and every feature is 0 (a silent bus is itself unusual).
- Gaps are measured between consecutive frames of **any** ID inside one window, in milliseconds.
- `std_gap` is the population standard deviation. A window with fewer than two frames has gaps of 0.
- `payload_entropy` pools every data byte in the window and measures how evenly the 256 possible values are used: 0 bits means every byte is identical, 8 bits means every value is equally likely.
- A window's `label` is 1 if **any** frame inside it has label 1 (it overlaps an attack interval), otherwise 0.

## Why entropy and timing, not payload values

The attacker may copy valid-looking payloads, so we do not judge individual
values. Detection relies on **how often** frames arrive (counts), **how evenly**
they arrive (gap mean and std) and **how varied** the bytes are (entropy).

## Output file format

`data/features_<name>.csv`, one row per window:

`window_start, total_count, unique_ids, count_0x100, count_0x200, count_0x300, count_0x400, count_0x500, mean_gap, std_gap, payload_entropy[, label]`

`window_start` is the epoch time of the window's start (same clock as the logger).
`label` appears only when the input recording has a label column.
Model code should select the 10 feature columns by name, in this order.
Non-default window sizes are saved with a suffix, e.g. `features_normal_v2_w100.csv`.
