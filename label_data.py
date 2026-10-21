#!/usr/bin/env python3
"""
label_data.py — frame-level labelling for CAN-Sentinel recordings.

Usage:
    # one file
    python3 label_data.py --log data/attack_log.csv data/attack_insert_1.csv

    # several files, written next to the originals as *_labeled.csv
    python3 label_data.py --log data/attack_log.csv \\
        data/attack_flood_1.csv data/attack_flood_2.csv data/attack_flood_3.csv \\
        data/attack_insert_1.csv data/attack_insert_2.csv data/attack_insert_3.csv

    # glob + explicit output directory
    python3 label_data.py --log data/attack_log.csv --out-dir data/labeled \\
        data/attack_flood_*.csv data/attack_insert_*.csv

    # in place (overwrite the input files instead of writing *_labeled.csv)
    python3 label_data.py --log data/attack_log.csv --in-place data/attack_insert_1.csv

A recording with no attack overlapping it at all (e.g. data/normal_v2.csv)
is still accepted: every frame simply gets label=0.
"""
import argparse
import bisect
import csv
import glob
import os
import sys

REQUIRED_RECORDING_COLUMNS = ["timestamp", "can_id", "dlc", "data_hex"]
ATTACK_LOG_COLUMNS = ["start_ts", "end_ts", "mode", "target_id"]


def load_attack_intervals(log_path):
    """Read attack_log.csv and return a sorted list of (start_ts, end_ts)
    tuples. Lines starting with '#' are skipped (synthetic-data headers
    use this convention elsewhere in the project)."""
    intervals = []
    with open(log_path, newline="") as f:
        lines = (line for line in f if not line.lstrip().startswith("#"))
        reader = csv.DictReader(lines)
        missing = [c for c in ("start_ts", "end_ts") if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(
                f"{log_path}: missing required column(s) {missing}; "
                f"found {reader.fieldnames}"
            )
        for row in reader:
            start_ts = float(row["start_ts"])
            end_ts = float(row["end_ts"])
            if end_ts < start_ts:
                raise ValueError(
                    f"{log_path}: row has end_ts < start_ts "
                    f"({row['start_ts']} -> {row['end_ts']})"
                )
            intervals.append((start_ts, end_ts))
    intervals.sort()
    return intervals


def make_labeler(intervals):
    """Return a function timestamp -> 0/1, using the contract's rule:
    label=1 if start_ts <= timestamp <= end_ts for ANY attack_log.csv row.

    Implemented with binary search over interval start times so labelling
    a multi-hundred-thousand-row recording against a handful of attack
    runs stays O(n log m) instead of O(n*m).
    """
    starts = [iv[0] for iv in intervals]

    def label(timestamp):
        # last interval whose start_ts <= timestamp
        i = bisect.bisect_right(starts, timestamp) - 1
        while i >= 0:
            start_ts, end_ts = intervals[i]
            if start_ts <= timestamp <= end_ts:
                return 1
            # Intervals can overlap in principle (e.g. overlapping runs),
            # so keep walking backwards while start_ts <= timestamp but
            # stop once we're clearly past any interval that could still
            # contain this timestamp.
            if start_ts <= timestamp and end_ts < timestamp:
                i -= 1
                continue
            break
        return 0

    return label


def label_recording(in_path, out_path, label_fn):
    with open(in_path, newline="") as fin:
        lines = [line for line in fin if not line.lstrip().startswith("#")]
    reader = csv.DictReader(lines)
    fieldnames = reader.fieldnames or []
    missing = [c for c in REQUIRED_RECORDING_COLUMNS if c not in fieldnames]
    if missing:
        raise ValueError(f"{in_path}: missing required column(s) {missing}; found {fieldnames}")

    out_fields = [c for c in fieldnames if c != "label"] + ["label"]

    n_total = 0
    n_attack = 0
    with open(out_path, "w", newline="") as fout:
        writer = csv.DictWriter(fout, fieldnames=out_fields)
        writer.writeheader()
        for row in reader:
            ts = float(row["timestamp"])
            lbl = label_fn(ts)
            row["label"] = lbl
            writer.writerow({k: row.get(k, "") for k in out_fields})
            n_total += 1
            n_attack += lbl

    return n_total, n_attack


def resolve_output_path(in_path, out_dir, in_place, suffix):
    if in_place:
        return in_path
    base = os.path.basename(in_path)
    name, ext = os.path.splitext(base)
    out_name = f"{name}{suffix}{ext}"
    if out_dir:
        return os.path.join(out_dir, out_name)
    return os.path.join(os.path.dirname(in_path) or ".", out_name)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Add a frame-level 'label' column to CAN recordings, "
                     "per docs/contract.md section 15.",
    )
    parser.add_argument(
        "--log", required=True,
        help="Path to attack_log.csv (start_ts,end_ts,mode,target_id).",
    )
    parser.add_argument(
        "recordings", nargs="+",
        help="Recording CSV path(s) to label. Shell globs are expanded by "
             "your shell; quoted globs (e.g. 'data/attack_*.csv') are also "
             "expanded here.",
    )
    parser.add_argument(
        "--out-dir", default=None,
        help="Write labeled files here instead of next to the input files.",
    )
    parser.add_argument(
        "--suffix", default="_labeled",
        help="Suffix inserted before the extension of each output file "
             "(default: _labeled). Ignored with --in-place.",
    )
    parser.add_argument(
        "--in-place", action="store_true",
        help="Overwrite each input recording with its labeled version "
             "instead of writing a new file.",
    )
    args = parser.parse_args(argv)

    expanded = []
    for pattern in args.recordings:
        matches = glob.glob(pattern)
        expanded.extend(matches if matches else [pattern])
    if not expanded:
        print("No recording files matched.", file=sys.stderr)
        return 1

    try:
        intervals = load_attack_intervals(args.log)
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    label_fn = make_labeler(intervals)

    if args.out_dir:
        os.makedirs(args.out_dir, exist_ok=True)

    exit_code = 0
    for path in expanded:
        out_path = resolve_output_path(path, args.out_dir, args.in_place, args.suffix)
        try:
            n_total, n_attack = label_recording(path, out_path, label_fn)
        except (OSError, ValueError) as e:
            print(f"error: {path}: {e}", file=sys.stderr)
            exit_code = 1
            continue
        pct = (100.0 * n_attack / n_total) if n_total else 0.0
        print(f"{path} -> {out_path}: {n_total} frames, "
              f"{n_attack} labeled attack ({pct:.2f}%)")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
