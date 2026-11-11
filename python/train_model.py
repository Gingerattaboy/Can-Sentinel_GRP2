#!/usr/bin/env python3

import argparse
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


FEATURE_COLUMNS = [
    "total_count",
    "unique_ids",
    "count_0x100",
    "count_0x200",
    "count_0x300",
    "count_0x400",
    "count_0x500",
    "mean_gap",
    "std_gap",
    "payload_entropy",
]


def main():
    parser = argparse.ArgumentParser(
        description="Train an Isolation Forest on normal CAN traffic features."
    )
    parser.add_argument(
        "--input",
        default="data/features_normal_v2.csv",
        help="CSV file containing normal feature windows",
    )
    parser.add_argument(
        "--output",
        default="models/iforest.joblib",
        help="Output model file",
    )
    parser.add_argument(
        "--train-fraction",
        type=float,
        default=0.70,
        help="Chronological fraction used for training (default: 0.70)",
    )
    parser.add_argument(
        "--contamination",
        default="0.01",
        help='Initial contamination setting, e.g. 0.01 or "auto"',
    )
    parser.add_argument(
        "--window-ms",
        type=int,
        default=200,
        help="Feature window size in milliseconds (default: 200)",
    )
    args = parser.parse_args()

    if not 0 < args.train_fraction < 1:
        parser.error("--train-fraction must be between 0 and 1.")
    if args.window_ms <= 0:
        parser.error("--window-ms must be positive.")

    if args.contamination.lower() == "auto":
        contamination = "auto"
    else:
        try:
            contamination = float(args.contamination)
        except ValueError:
            parser.error('--contamination must be a number or "auto".')
        if not 0 < contamination <= 0.5:
            parser.error("--contamination must be greater than 0 and at most 0.5.")

    input_path = Path(args.input)
    if not input_path.exists():
        parser.error(f"Input file not found: {input_path}")

    df = pd.read_csv(input_path)

    required = ["window_start", "label"] + FEATURE_COLUMNS
    missing = [column for column in required if column not in df.columns]
    if missing:
        parser.error(f"Missing required CSV columns: {missing}")

    if len(df) < 2:
        parser.error("At least two feature windows are required.")

    # Preserve chronological order for the 70/30 split.
    df["window_start"] = pd.to_numeric(
        df["window_start"], errors="coerce"
    )
    if df["window_start"].isna().any():
        parser.error("window_start contains invalid or missing values.")

    df = df.sort_values("window_start", kind="stable").reset_index(drop=True)

    for column in FEATURE_COLUMNS + ["label"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    if df[FEATURE_COLUMNS + ["label"]].isna().any().any():
        parser.error("Features or labels contain missing/non-numeric values.")

    if not (df["label"] == 0).all():
        parser.error(
            "Training input must contain only normal label 0. "
            "Do not use attack recordings for training."
        )

    split_index = int(len(df) * args.train_fraction)
    if split_index < 1 or split_index >= len(df):
        parser.error("The selected split leaves an empty training or holdout set.")

    train_x = df[FEATURE_COLUMNS].iloc[:split_index]
    holdout_x = df[FEATURE_COLUMNS].iloc[split_index:]

    model = Pipeline([
        ("scaler", StandardScaler()),
        (
            "iforest",
            IsolationForest(
                n_estimators=200,
                contamination=contamination,
                random_state=42,
                n_jobs=-1,
            ),
        ),
    ])

    # Fit only on the first chronological portion of normal traffic.
    model.fit(train_x)

    # Preliminary normal-only check. This is NOT attack-detection performance.
    holdout_predictions = model.predict(holdout_x)
    false_positive_rate = (holdout_predictions == -1).mean()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    model_bundle = {
        "pipeline": model,
        "feature_columns": FEATURE_COLUMNS,
        "window_ms": args.window_ms,
        "train_rows": len(train_x),
        "holdout_rows": len(holdout_x),
        "train_fraction": args.train_fraction,
        "contamination": contamination,
        "random_state": 42,
    }
    joblib.dump(model_bundle, output_path)

    print("Training completed successfully.")
    print(f"Input file: {input_path}")
    print(f"Total normal windows: {len(df)}")
    print(f"Training windows (first 70%): {len(train_x)}")
    print(f"Held-out normal windows (last 30%): {len(holdout_x)}")
    print(f"Window size: {args.window_ms} ms")
    print(f"Contamination: {contamination}")
    print(f"Random state: 42")
    print(f"Held-out normal windows flagged as anomalous: "
          f"{(holdout_predictions == -1).sum()}")
    print(f"Preliminary normal false-positive rate: "
          f"{false_positive_rate:.2%}")
    print(f"Saved model: {output_path}")
    print(
        "Note: attack-based precision, recall, F1 and ROC-AUC "
        "must be evaluated separately using valid attack recordings."
    )


if __name__ == "__main__":
    main()
