#!/usr/bin/env python3
"""
make_demo_dataset.py - generate a SYNTHETIC CAN-Sentinel demo dataset.

This is NOT a recording. It simulates what the four ECUs send (IDs, periods,
value ranges, byte layout, rolling counter, +/-0.5 ms jitter) so the logger
output format, check_data.py and the Week 2 ML code can be developed before the
real recording exists. The real deliverable data/normal_traffic.csv must still be
recorded with logger.py while the ECUs run on vcan0.

Usage:
    python python/make_demo_dataset.py                       # 10 minutes
    python python/make_demo_dataset.py -d 300 -o data/demo_traffic.csv --seed 1
"""

import argparse
import csv
import math
import random
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent

PERIODS = {0x100: 0.010, 0x200: 0.020, 0x300: 0.050, 0x400: 0.100}  # seconds
JITTER = 0.0005  # +/- 0.5 ms


def clamp(value, low, high):
    return max(low, min(high, value))


def generate(duration, start, rng):
    rows = []
    wobble = 0.0
    temp = 72.0
    for can_id, period in PERIODS.items():
        for k in range(int(duration / period)):
            t = k * period
            if can_id == 0x100:      # RPM, 800..6000
                value = 3400 + 2600 * math.sin(0.8 * t) + rng.randint(-20, 20)
                value = clamp(value, 800, 6000)
            elif can_id == 0x200:    # speed, 0..180
                value = 90 + 90 * math.sin(0.5 * t) + rng.randint(-1, 1)
                value = clamp(value, 0, 180)
            elif can_id == 0x300:    # steering, 0..1000, 500 = straight
                wobble = (wobble + rng.randint(-2, 2)) * 0.95
                value = 500 + 400 * math.sin(2 * math.pi * t / 8.0) + wobble
                value = clamp(value, 0, 1000)
            else:                    # temperature, raw 0.1 degC, 700..1100
                temp += (90.0 - temp) * 0.002
                reading = (temp + 1.5 * math.sin(2 * math.pi * t / 40.0)
                           + rng.randint(-5, 5) * 0.02)
                value = clamp(reading * 10.0, 700, 1100)
            timestamp = start + t + rng.uniform(-JITTER, JITTER) + JITTER
            rows.append((timestamp, can_id, int(value), k % 256))
    rows.sort()
    return rows


def main():
    parser = argparse.ArgumentParser(description="Generate a synthetic demo CSV.")
    parser.add_argument("-o", "--output", type=Path,
                        default=PROJECT_DIR / "data" / "demo_traffic.csv")
    parser.add_argument("-d", "--duration", type=float, default=600,
                        help="Simulated seconds (default 600 = 10 minutes).")
    parser.add_argument("--start", type=float, default=1792300000.0,
                        help="Timestamp of the first frame (seconds since epoch).")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rows = generate(args.duration, args.start, random.Random(args.seed))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["timestamp", "can_id", "dlc", "data_hex", "label"])
        for timestamp, can_id, value, counter in rows:
            data_hex = f"{value:04X}{counter:02X}0000000000"
            writer.writerow([f"{timestamp:.6f}", f"0x{can_id:03x}", 8, data_hex, 0])
    print(f"Wrote {len(rows)} synthetic frames to {args.output}")


if __name__ == "__main__":
    main()
