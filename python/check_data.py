
#!/usr/bin/env python3

import csv
import math
import re
import statistics
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
CSV_FILE = PROJECT_DIR / "data" / "normal_traffic.csv"

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


def main():
    if not CSV_FILE.exists():
        print(f"ERROR: CSV file not found: {CSV_FILE}")
        return

    timestamps = {can_id: [] for can_id in EXPECTED_PERIODS}
    errors = []
    warnings = []
    row_count = 0

    with CSV_FILE.open(
        "r", newline="", encoding="utf-8"
    ) as file:
        reader = csv.DictReader(file)

        if reader.fieldnames is None:
            print("ERROR: CSV file is empty.")
            return

        missing = [
            col for col in REQUIRED_COLUMNS
            if col not in reader.fieldnames
        ]

        if missing:
            print("ERROR: Missing columns:", missing)
            return

        for line, row in enumerate(reader, start=2):
            row_count += 1

            try:
                timestamp = float(row["timestamp"])
                can_id_value = int(row["can_id"], 16)
                can_id = f"0x{can_id_value:03x}"
                dlc = int(row["dlc"])
                data_hex = row["data_hex"].strip()
                label = int(row["label"])
            except (ValueError, TypeError, KeyError):
                errors.append(f"Row {line}: invalid field value")
                continue

            if not math.isfinite(timestamp):
                errors.append(f"Row {line}: invalid timestamp")
            elif can_id in timestamps:
                timestamps[can_id].append(timestamp)
            else:
                errors.append(
                    f"Row {line}: unexpected CAN ID {can_id}"
                )

            if dlc != 8:
                errors.append(f"Row {line}: DLC must be 8")

            if not re.fullmatch(r"[0-9A-Fa-f]{16}", data_hex):
                errors.append(
                    f"Row {line}: data_hex must have 16 hex characters"
                )

            if label not in (0, 1):
                errors.append(f"Row {line}: label must be 0 or 1")

    print(f"Dataset: {CSV_FILE}")
    print(f"Total frames: {row_count}")

    print("\nMessage counts:")
    for can_id, values in timestamps.items():
        print(f"{can_id}: {len(values)} frames")

    print("\nTiming checks:")

    for can_id, expected in EXPECTED_PERIODS.items():
        values = timestamps[can_id]

        if len(values) < 2:
            warnings.append(
                f"{can_id}: need at least 2 frames to check timing"
            )
            print(f"{can_id}: INSUFFICIENT DATA")
            continue

        gaps = [
            later - earlier
            for earlier, later in zip(values, values[1:])
        ]

        if any(gap <= 0 for gap in gaps):
            errors.append(
                f"{can_id}: timestamps are not increasing"
            )
            print(f"{can_id}: INVALID TIMING")
            continue

        average_gap = statistics.mean(gaps)
        deviation = abs(average_gap - expected) / expected * 100

        status = "PASS" if deviation <= 10 else "CHECK"
        print(
            f"{can_id}: average gap={average_gap * 1000:.2f} ms, "
            f"deviation={deviation:.2f}% -> {status}"
        )

        if deviation > 10:
            warnings.append(
                f"{can_id}: average interval differs by more than 10%"
            )

    print("\nData format:")
    if errors:
        print("FAIL")
        for error in errors:
            print(" -", error)
    else:
        print("PASS: No format errors found.")

    if warnings:
        print("\nWarnings:")
        for warning in warnings:
            print(" -", warning)

    if not errors and not warnings:
        print("\nRESULT: All checks passed.")
    elif not errors:
        print("\nRESULT: Format checks passed; more testing is needed.")


if __name__ == "__main__":
    main()
