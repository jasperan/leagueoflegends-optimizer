#!/usr/bin/env python
"""Train the small serving model, save it (joblib + ONNX) and check that ONNX gives the same answers.

    python scripts/train_serving_model.py            # uses data/by_minute.parquet if downloaded, else the small sample
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lolml import data, serving  # noqa: E402
from lolml.features import BYMIN_LIVE_SAFE  # noqa: E402

meta = serving.train()
print("trained:", meta)
onnx_path = serving.export_onnx()
print("ONNX written:", onnx_path, f"({onnx_path.stat().st_size // 1024} KB)")

df = data.load("by_minute").sample(2000, random_state=0)
a = serving.Scorer().win_probability(df[BYMIN_LIVE_SAFE])
b = serving.Scorer(onnx=True).win_probability(df[BYMIN_LIVE_SAFE])
print(f"joblib vs ONNX on 2000 rows: max |difference| = {np.abs(a - b).max():.2e}")
assert np.abs(a - b).max() < 1e-3, "ONNX output differs from scikit-learn"
