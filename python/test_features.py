"""
Unit tests for python/features.py (Member 3).
Run from the repo root:   python -m pytest tests/ -v

Every test uses tiny hand-made frames, so the right answer can be worked
out on paper. T0 = 1000.0 s; offsets below are seconds after T0.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))
import features as ft   # noqa: E402

T0 = 1000.0
ZERO8 = "0000000000000000"


def run(tmp_path, rows, window_ms=200, with_label=True):
    """rows = (offset_s, can_id_text, data_hex, label). Goes through the
    real CSV loader so the whole pipeline is tested."""
    df = pd.DataFrame(
        [(T0 + off, cid, 8, hx, lab) for off, cid, hx, lab in rows],
        columns=["timestamp", "can_id", "dlc", "data_hex", "label"],
    )
    if not with_label:
        df = df.drop(columns="label")
    path = tmp_path / "frames.csv"
    df.to_csv(path, index=False)
    return ft.compute_features(ft.load_frames(path), window_ms)


# -- counts ----------------------------------------------------------------
def test_counts_and_unique_ids(tmp_path):
    rows = [
        (0.00, "0x100", ZERO8, 0), (0.05, "0x200", ZERO8, 0),
        (0.10, "0x100", ZERO8, 0), (0.15, "0x500", ZERO8, 0),   # window 0
        (0.20, "0x300", ZERO8, 0), (0.30, "0x400", ZERO8, 0),   # window 1
        (0.40, "0x100", ZERO8, 0),                              # partial -> dropped
    ]
    f = run(tmp_path, rows)
    assert len(f) == 2
    w0, w1 = f.iloc[0], f.iloc[1]
    assert (w0.total_count, w0.unique_ids) == (4, 3)
    assert (w0.count_0x100, w0.count_0x200, w0.count_0x500) == (2, 1, 1)
    assert (w0.count_0x300, w0.count_0x400) == (0, 0)
    assert (w1.total_count, w1.unique_ids) == (2, 2)
    assert (w1.count_0x300, w1.count_0x400) == (1, 1)


def test_column_order_matches_contract(tmp_path):
    f = run(tmp_path, [(0.0, "0x100", ZERO8, 0), (0.5, "0x100", ZERO8, 0)])
    assert list(f.columns) == ["window_start"] + ft.FEATURE_COLUMNS + ["label"]
    assert ft.FEATURE_COLUMNS == [
        "total_count", "unique_ids", "count_0x100", "count_0x200", "count_0x300",
        "count_0x400", "count_0x500", "mean_gap", "std_gap", "payload_entropy"]


# -- timing ----------------------------------------------------------------
def test_gap_mean_and_std(tmp_path):
    rows = [(0.00, "0x100", ZERO8, 0), (0.04, "0x100", ZERO8, 0),
            (0.10, "0x100", ZERO8, 0), (0.25, "0x100", ZERO8, 0)]
    f = run(tmp_path, rows)
    assert len(f) == 1
    assert f.mean_gap[0] == np.float64(50.0)          # gaps 40 ms and 60 ms
    assert abs(f.std_gap[0] - 10.0) < 1e-9


def test_perfectly_regular_traffic_has_zero_std(tmp_path):
    rows = [(i * 0.05, "0x200", ZERO8, 0) for i in range(5)] + [(0.45, "0x200", ZERO8, 0)]
    f = run(tmp_path, rows)
    assert abs(f.mean_gap[0] - 50.0) < 1e-9
    assert abs(f.std_gap[0]) < 1e-9


def test_single_frame_window_has_zero_gap(tmp_path):
    f = run(tmp_path, [(0.05, "0x100", ZERO8, 0), (0.0, "0x100", ZERO8, 0),
                       (0.25, "0x100", ZERO8, 0), (0.45, "0x100", ZERO8, 0)])
    assert f.total_count.tolist() == [2, 1]
    assert f.mean_gap[1] == 0.0 and f.std_gap[1] == 0.0


# -- entropy ---------------------------------------------------------------
def test_entropy_zero_for_constant_payload(tmp_path):
    f = run(tmp_path, [(0.0, "0x100", ZERO8, 0), (0.1, "0x100", ZERO8, 0),
                       (0.3, "0x100", ZERO8, 0)])
    assert f.payload_entropy[0] == 0.0


def test_entropy_one_bit_for_two_equally_likely_bytes(tmp_path):
    rows = [(0.0, "0x100", "0000000000000000", 0),
            (0.1, "0x100", "0101010101010101", 0),
            (0.3, "0x100", ZERO8, 0)]
    assert abs(run(tmp_path, rows).payload_entropy[0] - 1.0) < 1e-9


def test_entropy_two_bits_for_four_equally_likely_bytes(tmp_path):
    rows = [(0.0, "0x100", "0001020300010203", 0),
            (0.1, "0x100", "0001020300010203", 0),
            (0.3, "0x100", ZERO8, 0)]
    assert abs(run(tmp_path, rows).payload_entropy[0] - 2.0) < 1e-9


def test_payload_with_spaces_is_parsed():
    assert ft.parse_payload("00 01 02 03 00 01 02 03") == bytes([0, 1, 2, 3, 0, 1, 2, 3])
    assert abs(ft.byte_entropy(ft.parse_payload("00 01 02 03 00 01 02 03")) - 2.0) < 1e-9


# -- windows ---------------------------------------------------------------
def test_empty_window_is_all_zero(tmp_path):
    f = run(tmp_path, [(0.0, "0x100", ZERO8, 0), (0.5, "0x100", ZERO8, 0)])
    assert len(f) == 2
    empty = f.iloc[1]
    assert all(empty[c] == 0 for c in ft.FEATURE_COLUMNS)
    assert empty.label == 0


def test_window_ms_option_changes_number_of_windows(tmp_path):
    rows = [(i * 0.1, "0x100", ZERO8, 0) for i in range(5)]      # 0.0 .. 0.4
    assert len(run(tmp_path, rows, window_ms=200)) == 2
    assert len(run(tmp_path, rows, window_ms=100)) == 4


def test_window_start_times(tmp_path):
    f = run(tmp_path, [(0.0, "0x100", ZERO8, 0), (0.5, "0x100", ZERO8, 0)])
    assert f.window_start.tolist() == [T0, T0 + 0.2]


# -- labels ----------------------------------------------------------------
def test_window_label_is_one_if_any_frame_is_attack(tmp_path):
    rows = [(0.00, "0x100", ZERO8, 0), (0.10, "0x500", ZERO8, 1),   # window 0 attack
            (0.20, "0x100", ZERO8, 0), (0.30, "0x100", ZERO8, 0),   # window 1 normal
            (0.45, "0x100", ZERO8, 0)]
    assert run(tmp_path, rows).label.tolist() == [1, 0]


def test_no_label_column_when_input_has_none(tmp_path):
    f = run(tmp_path, [(0.0, "0x100", ZERO8, 0), (0.5, "0x100", ZERO8, 0)], with_label=False)
    assert "label" not in f.columns


# -- CAN ID formats --------------------------------------------------------
def test_can_id_formats():
    p = lambda xs: ft.parse_can_ids(pd.Series(xs)).tolist()
    assert p(["0x100", "0x500"]) == [0x100, 0x500]       # 0x prefix
    assert p(["100", "200", "500"]) == [0x100, 0x200, 0x500]   # hex digits, no prefix
    assert p(["256", "512", "1280"]) == [0x100, 0x200, 0x500]  # decimal
    assert p(["1a3"]) == [0x1A3]                          # has a letter -> hex


# -- command line ----------------------------------------------------------
def test_main_writes_features_file(tmp_path):
    src = tmp_path / "normal_v2.csv"
    pd.DataFrame({"timestamp": [T0, T0 + 0.1, T0 + 0.5], "can_id": ["0x100"] * 3,
                  "dlc": [8] * 3, "data_hex": [ZERO8] * 3, "label": [0] * 3}).to_csv(src, index=False)
    assert ft.main([str(src), "--out-dir", str(tmp_path)]) == 0
    out = pd.read_csv(tmp_path / "features_normal_v2.csv")
    assert len(out) == 2 and "label" in out.columns
    ft.main([str(src), "--out-dir", str(tmp_path), "--window-ms", "100"])
    assert (tmp_path / "features_normal_v2_w100.csv").exists()
