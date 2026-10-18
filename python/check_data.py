#!/usr/bin/env python3
"""
check_data.py - check a CAN-Sentinel CSV file for format errors and wrong message rates.

Usage (from the repo root):
    python python/check_data.py                      # checks data/normal_traffic.csv
    python python/check_data.py data/other.csv       # checks another file

Exit code: 0 = all checks passed
           1 = file problem or format errors
           2 = format OK, but a rate is off or there is too little data
"""

import argparse
import csv
import math
import re
import statistics
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CSV = PROJECT_DIR / "data" / "normal_traffic.csv"

# Expected message period in seconds
EXPECTED_PERIODS = {
    "0x100": 0.010,  # RPM: 10 ms
    "0x200": 0.020,  # Speed: 20 ms
    "0x300": 0.050,  # Steering: 50 ms
    "0x400": 0.100,  # Temperature: 100 ms
}

REQUIRED_COLUMNS = [
    "timestamp",
    "can_id",
    "dlc",
    "data_hex",
    "label",
]

TOLERANCE_PERCENT = 10   # allowed difference from the expected period
MAX_ERRORS_SHOWN = 20    # do not flood the screen on a badly broken file


def parse_args():
    parser = argparse.ArgumentParser(
        description="Check a CAN-Sentinel CSV file for format errors and wrong rates."
    )
    parser.add_argument(
        "csv_file",
        nargs="?",
        type=Path,
        default=DEFAULT_CSV,
        help=f"CSV file to check (default: {DEFAULT_CSV}).",
    )
    return parser.parse_args()


def main():
    csv_file = parse_args().csv_file

    if not csv_file.exists():
        print(f"ERROR: CSV file not found: {csv_file}")
        return 1

    timestamps = {can_id: [] for can_id in EXPECTED_PERIODS}
    errors = []
    warnings = []
    row_count = 0

    with csv_file.open("r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        if reader.fieldnames is None:
            print("ERROR: CSV file is empty.")
            return 1

        missing = [col for col in REQUIRED_COLUMNS if col not in reader.fieldnames]
        if missing:
            print("ERROR: Missing columns:", missing)
            return 1

        for line, row in enumerate(reader, start=2):
            row_count += 1

            try:
                timestamp = float(row["timestamp"])
                can_id_value = int(row["can_id"], 16)
                can_id = f"0x{can_id_value:03x}"
                dlc = int(row["dlc"])
                data_hex = row["data_hex"].strip()
                label = int(row["label"])
            except (ValueError, TypeError, KeyError, AttributeError):
                errors.append(f"Row {line}: invalid field value")
                continue

            if not math.isfinite(timestamp):
                errors.append(f"Row {line}: invalid timestamp")
            elif can_id in timestamps:
                timestamps[can_id].append(timestamp)
            else:
                errors.append(f"Row {line}: unexpected CAN ID {can_id}")

            if dlc != 8:
                errors.append(f"Row {line}: DLC must be 8")

            if not re.fullmatch(r"[0-9A-Fa-f]{16}", data_hex):
                errors.append(f"Row {line}: data_hex must have 16 hex characters")

            if label not in (0, 1):
                errors.append(f"Row {line}: label must be 0 or 1")

    print(f"Dataset: {csv_file}")
    print(f"Total frames: {row_count}")

    print("\nMessage counts:")
    for can_id, values in timestamps.items():
        print(f"{can_id}: {len(values)} frames")

    print("\nTiming checks:")
    for can_id, expected in EXPECTED_PERIODS.items():
        values = timestamps[can_id]

        if len(values) < 2:
            warnings.append(f"{can_id}: need at least 2 frames to check timing")
            print(f"{can_id}: INSUFFICIENT DATA")
            continue

        gaps = [later - earlier for earlier, later in zip(values, values[1:])]

        if any(gap <= 0 for gap in gaps):
            errors.append(f"{can_id}: timestamps are not increasing")
            print(f"{can_id}: INVALID TIMING")
            continue

        average_gap = statistics.mean(gaps)
        deviation = abs(average_gap - expected) / expected * 100
        status = "PASS" if deviation <= TOLERANCE_PERCENT else "CHECK"

        print(
            f"{can_id}: average gap={average_gap * 1000:.2f} ms, "
            f"deviation={deviation:.2f}% -> {status}"
        )

        if deviation > TOLERANCE_PERCENT:
            warnings.append(
                f"{can_id}: average interval differs by more than {TOLERANCE_PERCENT}%"
            )

    print("\nData format:")
    if errors:
        print(f"FAIL ({len(errors)} problems)")
        for error in errors[:MAX_ERRORS_SHOWN]:
            print(" -", error)
        hidden = len(errors) - MAX_ERRORS_SHOWN
        if hidden > 0:
            print(f" ... and {hidden} more")
    else:
        print("PASS: No format errors found.")

    if warnings:
        print("\nWarnings:")
        for warning in warnings:
            print(" -", warning)

    if errors:
        print("\nRESULT: Format errors found.")
        return 1
    if warnings:
        print("\nRESULT: Format checks passed; more testing is needed.")
        return 2

    print("\nRESULT: All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
