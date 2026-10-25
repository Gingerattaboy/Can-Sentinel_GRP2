#!/usr/bin/env python3
"""Evaluate a trained Isolation Forest on held-out normal and labelled attack windows."""

import argparse
import csv
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)

DEFAULT_FEATURES = [
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


def read_features(path, feature_columns):
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"Feature file not found: {path}")

    df = pd.read_csv(path)
    required = feature_columns + ["label"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"{path}: missing columns {missing}")

    for col in required:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    if df[required].isna().any().any():
        raise ValueError(f"{path}: missing or non-numeric feature/label values")

    if not df["label"].isin([0, 1]).all():
        raise ValueError(f"{path}: label must contain only 0 (normal) or 1 (attack)")

    return df


def anomaly_scores(pipeline, df, feature_columns):
    # Larger scores mean more anomalous.
    return -pipeline.decision_function(df[feature_columns])


def tune_threshold(pipeline, validation_df, feature_columns):
    labels = validation_df["label"].astype(int).to_numpy()
    if len(np.unique(labels)) < 2:
        raise ValueError(
            "The validation run must contain both normal (0) and attack (1) windows."
        )

    scores = anomaly_scores(pipeline, validation_df, feature_columns)
    precision, recall, thresholds = precision_recall_curve(labels, scores)

    if len(thresholds) == 0:
        raise ValueError("Could not calculate a threshold from the validation run.")

    denominator = precision[:-1] + recall[:-1]
    f1_values = np.divide(
        2 * precision[:-1] * recall[:-1],
        denominator,
        out=np.zeros_like(denominator),
        where=denominator != 0,
    )
    best = int(np.argmax(f1_values))
    return float(thresholds[best]), float(f1_values[best])


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate the CAN-Sentinel Isolation Forest model."
    )
    parser.add_argument("--model", default="models/iforest.joblib")
    parser.add_argument(
        "--normal-features", default="data/features_normal_v2.csv",
        help="Same full normal feature CSV used to train the model",
    )
    parser.add_argument(
        "--attack-features", nargs="*", default=[],
        help="One or more labelled attack feature CSVs reserved for final evaluation",
    )
    parser.add_argument(
        "--tune-threshold-on",
        help="ONE labelled validation attack feature CSV; do not use it for final testing",
    )
    parser.add_argument(
        "--threshold-file", help="Load a previously tuned threshold JSON file"
    )
    parser.add_argument(
        "--output-csv", default="reports/evaluation_results.csv"
    )
    args = parser.parse_args()

    if args.tune_threshold_on and args.threshold_file:
        parser.error("Use --tune-threshold-on OR --threshold-file, not both.")

    bundle = joblib.load(args.model)
    if not isinstance(bundle, dict) or "pipeline" not in bundle:
        parser.error(
            "Model bundle format not recognized. Expected the bundle created by train_model.py."
        )

    pipeline = bundle["pipeline"]
    feature_columns = bundle.get("feature_columns", DEFAULT_FEATURES)
    window_ms = int(bundle.get("window_ms", 200))
    train_rows = int(bundle["train_rows"])

    normal_df = read_features(args.normal_features, feature_columns)
    if "window_start" not in normal_df.columns:
        parser.error("Normal feature CSV must contain window_start.")

    normal_df = normal_df.sort_values("window_start", kind="stable").reset_index(drop=True)

    if not (normal_df["label"] == 0).all():
        parser.error("Normal feature CSV must contain only label 0.")
    if train_rows < 1 or train_rows >= len(normal_df):
        parser.error(
            "Training row count does not fit this normal dataset. "
            "Use the same feature dataset that was used to train this model."
        )

    # Use only the final chronological portion, which was held out during training.
    normal_test = normal_df.iloc[train_rows:].copy()
    normal_scores = anomaly_scores(pipeline, normal_test, feature_columns)

    # The default threshold 0 is equivalent to the fitted model's predict() cutoff.
    threshold = 0.0
    threshold_source = "model default"

    if args.threshold_file:
        with open(args.threshold_file) as f:
            saved = json.load(f)
        if int(saved.get("window_ms", window_ms)) != window_ms:
            parser.error("Threshold window size does not match the selected model.")
        threshold = float(saved["threshold"])
        threshold_source = f"loaded from {args.threshold_file}"

    if args.tune_threshold_on:
        validation_path = Path(args.tune_threshold_on).resolve()
        test_paths = {Path(p).resolve() for p in args.attack_features}
        if validation_path in test_paths:
            parser.error(
                "Keep the threshold-tuning run separate from final attack evaluation."
            )

        validation_df = read_features(validation_path, feature_columns)
        threshold, validation_f1 = tune_threshold(
            pipeline, validation_df, feature_columns
        )
        threshold_source = f"tuned on {validation_path}"

        threshold_path = Path("models") / f"threshold_{window_ms}ms.json"
        threshold_path.parent.mkdir(parents=True, exist_ok=True)
        with open(threshold_path, "w") as f:
            json.dump(
                {
                    "threshold": threshold,
                    "window_ms": window_ms,
                    "validation_file": str(validation_path),
                    "validation_windows": len(validation_df),
                    "validation_f1": validation_f1,
                },
                f,
                indent=2,
            )

        print(f"Validation windows: {len(validation_df)}")
        print(f"Best validation F1: {validation_f1:.4f}")
        print(f"Tuned threshold: {threshold:.8f}")
        print(f"Saved threshold: {threshold_path}")

    print(f"\nModel: {args.model}")
    print(f"Window size: {window_ms} ms")
    print(f"Normal training windows excluded from evaluation: {train_rows}")
    print(f"Held-out normal windows: {len(normal_test)}")
    print(f"Threshold: {threshold:.8f} ({threshold_source})")

    normal_predictions = (normal_scores >= threshold).astype(int)
    normal_fp_rate = float(normal_predictions.mean())
    print(f"Held-out normal false-positive rate: {normal_fp_rate:.2%}")

    if not args.attack_features:
        print(
            "\nNormal-only check completed. No attack metrics were calculated. "
            "Supply valid labelled attack feature CSVs for final evaluation."
        )
        return

    all_labels = [np.zeros(len(normal_test), dtype=int)]
    all_scores = [np.asarray(normal_scores)]
    attack_windows = 0

    for attack_path in args.attack_features:
        attack_path = Path(attack_path).resolve()
        if args.tune_threshold_on and attack_path == Path(args.tune_threshold_on).resolve():
            parser.error("The validation run cannot also be used as a final test run.")

        attack_df = read_features(attack_path, feature_columns)
        labels = attack_df["label"].astype(int).to_numpy()
        scores = anomaly_scores(pipeline, attack_df, feature_columns)

        all_labels.append(labels)
        all_scores.append(np.asarray(scores))
        attack_windows += len(attack_df)

        print(
            f"Attack evaluation file: {attack_path} "
            f"({len(attack_df)} windows; label counts: "
            f"{dict(zip(*np.unique(labels, return_counts=True)))})"
        )

    y_true = np.concatenate(all_labels)
    scores = np.concatenate(all_scores)
    y_pred = (scores >= threshold).astype(int)

    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    precision = precision_score(y_true, y_pred, zero_division=0)
    recall = recall_score(y_true, y_pred, zero_division=0)
    f1 = f1_score(y_true, y_pred, zero_division=0)
    auc = roc_auc_score(y_true, scores) if len(np.unique(y_true)) == 2 else float("nan")

    print("\n========== FINAL EVALUATION ==========")
    print(f"Normal holdout windows: {len(normal_test)}")
    print(f"Attack-run windows: {attack_windows}")
    print(f"TN={tn}, FP={fp}, FN={fn}, TP={tp}")
    print(f"Precision: {precision:.4f}")
    print(f"Recall:    {recall:.4f}")
    print(f"F1-score:  {f1:.4f}")
    print(f"ROC-AUC:   {auc:.4f}" if np.isfinite(auc) else "ROC-AUC: unavailable")
    print("Confusion matrix (rows=true [normal, attack], columns=predicted [normal, attack]):")
    print(np.array([[tn, fp], [fn, tp]]))

    output_path = Path(args.output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "window_ms", "threshold", "normal_holdout_windows",
                "attack_windows", "tn", "fp", "fn", "tp",
                "precision", "recall", "f1", "roc_auc",
                "normal_false_positive_rate",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "window_ms": window_ms,
                "threshold": threshold,
                "normal_holdout_windows": len(normal_test),
                "attack_windows": attack_windows,
                "tn": tn,
                "fp": fp,
                "fn": fn,
                "tp": tp,
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "roc_auc": auc,
                "normal_false_positive_rate": normal_fp_rate,
            }
        )

    print(f"\nSaved results table: {output_path}")


if __name__ == "__main__":
    main()
