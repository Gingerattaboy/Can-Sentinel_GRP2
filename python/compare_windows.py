from pathlib import Path

import joblib
import matplotlib.pyplot as plt
import pandas as pd

CONFIGS = [
    (
        200,
        "models/iforest.joblib",
        "data/features_normal_v2.csv",
    ),
    (
        100,
        "models/iforest_100ms.joblib",
        "data/features_normal_v2_w100.csv",
    ),
]

results = []

for expected_window, model_path, feature_path in CONFIGS:
    bundle = joblib.load(model_path)
    df = pd.read_csv(feature_path)

    if int(bundle["window_ms"]) != expected_window:
        raise ValueError(f"Window size mismatch in {model_path}")

    if not (df["label"] == 0).all():
        raise ValueError(f"{feature_path} contains non-normal labels")

    df = df.sort_values("window_start", kind="stable").reset_index(drop=True)

    train_rows = int(bundle["train_rows"])
    holdout = df.iloc[train_rows:]
    features = bundle["feature_columns"]

    if holdout.empty:
        raise ValueError(f"No held-out windows in {feature_path}")

    predictions = bundle["pipeline"].predict(holdout[features])
    false_positives = int((predictions == -1).sum())
    false_positive_rate = false_positives / len(holdout)

    results.append({
        "window_ms": expected_window,
        "total_windows": len(df),
        "training_windows": train_rows,
        "heldout_normal_windows": len(holdout),
        "false_positives": false_positives,
        "false_positive_rate_pct": round(false_positive_rate * 100, 4),
        "contamination": bundle["contamination"],
        "random_state": bundle["random_state"],
    })

report = pd.DataFrame(results).sort_values("window_ms")

output_dir = Path("reports")
output_dir.mkdir(parents=True, exist_ok=True)

csv_path = output_dir / "window_comparison_normal_only.csv"
chart_path = output_dir / "window_comparison_normal_only.png"

report.to_csv(csv_path, index=False)

plt.figure(figsize=(8, 5))
plt.bar(
    report["window_ms"].astype(str) + " ms",
    report["false_positive_rate_pct"],
)
plt.xlabel("Feature window size")
plt.ylabel("False-positive rate (%)")
plt.title("CAN-Sentinel: Normal-Traffic Evaluation")
plt.tight_layout()
plt.savefig(chart_path, dpi=200)
plt.close()

print("\nNormal-only window comparison:")
print(report.to_string(index=False))
print(f"\nSaved table: {csv_path}")
print(f"Saved chart: {chart_path}")
print("\nIMPORTANT: Attack-detection performance has not been evaluated.")
