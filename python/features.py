#!/usr/bin/env python3
"""
features.py - turn raw CAN frames into window features (Member 3, Week 2)

Input CSV (Week 1 logger format):  timestamp, can_id, dlc, data_hex[, label]
Output CSV: one row per fixed-size, non-overlapping time window:

    window_start, <10 features in the contract order>[, label]

Feature order (shared contract - do not change without telling the team):
    total_count, unique_ids,
    count_0x100, count_0x200, count_0x300, count_0x400, count_0x500,
    mean_gap, std_gap, payload_entropy

Usage examples
    python python/features.py data/normal_v2.csv
    python python/features.py data/attack_flood_1.csv data/attack_insert_1.csv
    python python/features.py data/normal_v2.csv --window-ms 100
    python python/features.py data/normal_v2.csv -o data/features_normal_v2.csv
"""
import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_WINDOW_MS = 200
KNOWN_IDS = [0x100, 0x200, 0x300, 0x400, 0x500]

# Fixed order from the Week 2 contract.
FEATURE_COLUMNS = [
    "total_count", "unique_ids",
    "count_0x100", "count_0x200", "count_0x300", "count_0x400", "count_0x500",
    "mean_gap", "std_gap", "payload_entropy",
]


# --------------------------------------------------------------------------
# Reading the CSV
# --------------------------------------------------------------------------
def _parse_one_id(text):
    """'0x100' / '1A3' -> hex.  Plain digits are decided by parse_can_ids()."""
    return int(text, 16)


def parse_can_ids(series):
    """
    Convert the can_id column to integers. The logger may write the ID as
    '0x100', '100' (hex digits) or '256' (decimal). We handle all three:
      - a 0x prefix or any letter a-f means hex
      - plain digits: pick whichever reading (hex or decimal) matches our
        known IDs 0x100..0x500 more often
    """
    s = series.astype(str).str.strip()
    if s.str.contains(r"^0[xX]|[a-fA-F]", regex=True).any():
        return s.apply(_parse_one_id).astype(int)
    as_dec = s.astype(int)
    as_hex = s.apply(_parse_one_id).astype(int)
    if as_hex.isin(KNOWN_IDS).sum() > as_dec.isin(KNOWN_IDS).sum():
        return as_hex
    return as_dec


def parse_payload(text):
    """'00 1F 2A ...' or '001F2A...' or '0x001F..' -> bytes (empty if missing)."""
    if not isinstance(text, str):
        return b""
    clean = re.sub(r"0[xX]", "", text)
    clean = re.sub(r"[^0-9a-fA-F]", "", clean)
    if len(clean) % 2:
        clean = "0" + clean
    return bytes.fromhex(clean)


def load_frames(path):
    """Read a logger CSV into a clean, time-sorted DataFrame."""
    raw = pd.read_csv(path, dtype={"can_id": str, "data_hex": str})
    missing = {"timestamp", "can_id", "data_hex"} - set(raw.columns)
    if missing:
        raise ValueError(f"{path}: missing column(s) {sorted(missing)}")

    frames = pd.DataFrame({
        "timestamp": raw["timestamp"].astype(float),
        "can_id": parse_can_ids(raw["can_id"]),
        "payload": [parse_payload(h) for h in raw["data_hex"]],
    })
    if "label" in raw.columns:
        frames["label"] = raw["label"].fillna(0).astype(int)
    return frames.sort_values("timestamp", kind="stable").reset_index(drop=True)


# --------------------------------------------------------------------------
# Feature maths
# --------------------------------------------------------------------------
def byte_entropy(payload_bytes):
    """Shannon entropy (in bits, 0..8) of the byte values in a payload blob."""
    data = np.frombuffer(payload_bytes, dtype=np.uint8)
    if data.size == 0:
        return 0.0
    counts = np.bincount(data, minlength=256)
    p = counts[counts > 0] / data.size
    return float(-np.sum(p * np.log2(p))) + 0.0      # "+ 0.0" turns -0.0 into 0.0


def compute_features(frames, window_ms=DEFAULT_WINDOW_MS):
    """
    Cut the frames into non-overlapping windows of window_ms and compute the
    contract features for each one.

    Rules (also written in docs/features.md):
      * windows start at the first frame's timestamp
      * the last, incomplete window is dropped (it would look like a dip)
      * a window with no frames is kept, with every feature = 0
      * gaps are between consecutive frames (any ID) inside one window, in ms
      * std_gap is the population standard deviation (ddof = 0)
      * window label = 1 if any frame in it has label 1
    """
    out_cols = ["window_start"] + FEATURE_COLUMNS
    has_label = "label" in frames.columns
    if has_label:
        out_cols.append("label")
    if frames.empty:
        return pd.DataFrame(columns=out_cols)

    window_ns = int(round(window_ms * 1e6))
    t0 = float(frames["timestamp"].iloc[0])
    # integer nanoseconds avoid floating-point edge cases at window borders
    rel_ns = np.rint((frames["timestamp"].to_numpy() - t0) * 1e9).astype(np.int64)
    win_idx = rel_ns // window_ns
    n_windows = int(win_idx[-1])             # last index = partial window -> dropped

    ts_ms = rel_ns / 1e6
    ids = frames["can_id"].to_numpy()
    payloads = frames["payload"].tolist()
    labels = frames["label"].to_numpy() if has_label else None

    bounds = np.searchsorted(win_idx, np.arange(n_windows + 1))   # slice edges
    rows = []
    for k in range(n_windows):
        s, e = bounds[k], bounds[k + 1]
        row = {"window_start": t0 + k * window_ms / 1000.0}
        if e == s:                                    # empty window
            row.update({c: 0 for c in FEATURE_COLUMNS})
            row["payload_entropy"] = 0.0
        else:
            w_ids = ids[s:e]
            gaps = np.diff(ts_ms[s:e])
            row["total_count"] = int(e - s)
            row["unique_ids"] = int(len(np.unique(w_ids)))
            for cid in KNOWN_IDS:
                row[f"count_0x{cid:X}"] = int(np.sum(w_ids == cid))
            row["mean_gap"] = float(gaps.mean()) if gaps.size else 0.0
            row["std_gap"] = float(gaps.std()) if gaps.size else 0.0
            row["payload_entropy"] = byte_entropy(b"".join(payloads[s:e]))
        if has_label:
            row["label"] = int(labels[s:e].max()) if e > s else 0
        rows.append(row)

    return pd.DataFrame(rows, columns=out_cols)


# --------------------------------------------------------------------------
# Batch mode
# --------------------------------------------------------------------------
def output_name(input_path, window_ms):
    """data/attack_flood_1.csv -> features_attack_flood_1.csv
    (non-default window sizes get a suffix, e.g. features_..._w100.csv)"""
    suffix = "" if window_ms == DEFAULT_WINDOW_MS else f"_w{window_ms}"
    return f"features_{Path(input_path).stem}{suffix}.csv"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Turn CAN frame CSVs into window features.")
    ap.add_argument("inputs", nargs="+", help="one or more logger CSV files")
    ap.add_argument("--window-ms", type=int, default=DEFAULT_WINDOW_MS,
                    help="window length in milliseconds (default 200)")
    ap.add_argument("--out-dir", default="data",
                    help="where to write features_*.csv (default data/)")
    ap.add_argument("-o", "--output",
                    help="output file name (only when there is one input)")
    args = ap.parse_args(argv)

    if args.window_ms <= 0:
        ap.error("--window-ms must be positive")
    if args.output and len(args.inputs) != 1:
        ap.error("-o/--output works with exactly one input file")

    for path in args.inputs:
        frames = load_frames(path)
        feats = compute_features(frames, args.window_ms)
        out = Path(args.output) if args.output else Path(args.out_dir) / output_name(path, args.window_ms)
        out.parent.mkdir(parents=True, exist_ok=True)
        feats.to_csv(out, index=False)

        msg = f"{path}: {len(frames)} frames -> {len(feats)} windows ({args.window_ms} ms) -> {out}"
        if "label" in feats.columns:
            msg += f"  [attack windows: {int(feats['label'].sum())}]"
        print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
