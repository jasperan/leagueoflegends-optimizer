#!/usr/bin/env python
"""Maintainers: build the small committed samples in data/sample/ from the full parquet files.
The samples let `make smoke` and CI run the whole pipeline without downloading anything."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lolml import data, paths  # noqa: E402

paths.SAMPLE.mkdir(parents=True, exist_ok=True)
for name, n_matches in (("performance", 1500), ("by_minute", 300)):
    df = pd.read_parquet(data.path_for(name))
    ids = np.sort(df["match_id"].unique())
    keep = np.random.default_rng(7).choice(ids, n_matches, replace=False)
    out = df[df["match_id"].isin(keep)].reset_index(drop=True)
    p = data.path_for(name, smoke=True)
    out.to_parquet(p, index=False, compression="zstd")
    print(f"{p.name}: {len(out):,} rows, {out['match_id'].nunique()} matches, {p.stat().st_size / 1e6:.1f} MB")
