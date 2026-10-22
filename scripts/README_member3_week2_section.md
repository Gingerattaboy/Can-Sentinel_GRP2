## Feature Extraction (Week 2)

Install the Python packages once: `pip install pandas numpy matplotlib pytest`

```bash
# turn recordings into window features (writes data/features_<name>.csv)
python python/features.py data/normal_v2.csv data/attack_flood_1.csv data/attack_insert_1.csv

# different window size for the comparison table (writes ..._w100.csv)
python python/features.py data/normal_v2.csv --window-ms 100

# run the unit tests
python -m pytest tests/ -v

# plots for the review slide (writes two PNG files to docs/)
python python/plot_features.py --normal data/features_normal_v2.csv \
    --attack data/features_attack_flood_1.csv data/features_attack_insert_1.csv --out-dir docs
```

Feature definitions: see [docs/features.md](docs/features.md).
