#!/usr/bin/env python3
"""Make models/iforest_scale.json = lowest and highest anomaly score on NORMAL windows.
Run from the repo root:  python3 compute_scale.py
"""
import json, sys
from pathlib import Path
import joblib, pandas as pd

MODEL = Path("models/iforest.joblib")
DATA = Path(sys.argv[1] if len(sys.argv) > 1 else "data/features_normal_v2.csv")
OUT = Path("models/iforest_scale.json")

bundle = joblib.load(MODEL)
cols = bundle["feature_columns"]
df = pd.read_csv(DATA)
x = df[cols].apply(pd.to_numeric)
anomaly = -bundle["pipeline"].score_samples(x)      # higher = more anomalous
lo, hi = float(anomaly.min()), float(anomaly.max())
OUT.write_text(json.dumps({"min": lo, "max": hi}))
print(f"windows used : {len(x)}")
print(f"min anomaly  : {lo:.4f}")
print(f"max anomaly  : {hi:.4f}")
print(f"saved        : {OUT}")
