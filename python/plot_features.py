#!/usr/bin/env python3
"""
plot_features.py - normal vs attack feature plots for the review slide (Member 3)

Makes two images in docs/:
  features_normal_vs_attack.png  histograms of key features, normal vs attack windows
  attack_timeline.png            frames-per-window over time with attack windows shaded

Usage:
    python python/plot_features.py \
        --normal data/features_normal_v2.csv \
        --attack data/features_attack_flood_1.csv data/features_attack_insert_1.csv \
        --out-dir docs
"""
import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")                       # no display needed
import matplotlib.pyplot as plt
import pandas as pd

PLOT_FEATURES = [
    ("total_count",     "Frames per window"),
    ("count_0x500",     "Brake (0x500) frames"),
    ("count_0x100",     "RPM (0x100) frames"),
    ("mean_gap",        "Mean gap between frames (ms)"),
    ("std_gap",         "Std of gap (ms)"),
    ("payload_entropy", "Payload entropy (bits)"),
]
NORMAL_COLOR, ATTACK_COLOR = "#2a7ab9", "#d9453d"


def attack_name(path):
    return Path(path).stem.replace("features_", "").replace("_", " ")


def histogram_figure(normal, attacks, out_path):
    fig, axes = plt.subplots(2, 3, figsize=(14, 7))
    for ax, (col, title) in zip(axes.flat, PLOT_FEATURES):
        pools = [normal[col]] + [a.loc[a["label"] == 1, col] for _, a in attacks]
        lo, hi = min(p.min() for p in pools), max(p.max() for p in pools)
        bins = 30 if hi > lo else 1
        rng = (lo, hi) if hi > lo else (lo - 0.5, lo + 0.5)
        ax.hist(normal[col], bins=bins, range=rng, color=NORMAL_COLOR, alpha=0.65,
                density=True, label="normal")
        for i, (name, a) in enumerate(attacks):
            ax.hist(a.loc[a["label"] == 1, col], bins=bins, range=rng, alpha=0.5,
                    density=True, label=f"attack: {name}",
                    color=ATTACK_COLOR if i == 0 else "#e8a33d")
        ax.set_title(title)
        ax.set_ylabel("density")
    axes.flat[0].legend(fontsize=8)
    fig.suptitle("Normal vs attack windows: the attack changes frequency, timing and entropy")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def timeline_figure(name, attack, out_path):
    t = attack["window_start"] - attack["window_start"].iloc[0]
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(t, attack["total_count"], color=NORMAL_COLOR, lw=1.2, label="frames per window")
    under = attack["label"] == 1
    ax.fill_between(t, 0, attack["total_count"].max() * 1.05, where=under,
                    color=ATTACK_COLOR, alpha=0.25, label="attack window")
    ax.set_xlabel("time since start of recording (s)")
    ax.set_ylabel("frames per window")
    ax.set_title(f"Traffic volume during attack: {name}")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Plot normal vs attack window features.")
    ap.add_argument("--normal", required=True, help="features CSV of normal traffic")
    ap.add_argument("--attack", nargs="+", required=True,
                    help="one or more features CSVs that contain a label column")
    ap.add_argument("--out-dir", default="docs")
    args = ap.parse_args(argv)

    normal = pd.read_csv(args.normal)
    attacks = []
    for p in args.attack:
        a = pd.read_csv(p)
        if "label" not in a.columns or a["label"].sum() == 0:
            sys.exit(f"{p}: needs a label column with at least one attack window")
        attacks.append((attack_name(p), a))

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    histogram_figure(normal, attacks, out / "features_normal_vs_attack.png")
    timeline_figure(attacks[0][0], attacks[0][1], out / "attack_timeline.png")
    print(f"saved plots to {out}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
