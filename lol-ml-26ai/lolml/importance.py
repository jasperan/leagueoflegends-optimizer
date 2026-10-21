"""Model-agnostic permutation importance (works for fastai, PyTorch, scikit-learn or anything with a predict function)."""
from __future__ import annotations

from typing import Callable, Sequence

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score


def permutation_importance(predict_win_prob: Callable[[pd.DataFrame], np.ndarray], X: pd.DataFrame, y: Sequence,
                           columns: Sequence[str], n_repeats: int = 3, seed: int = 0) -> pd.DataFrame:
    """Drop in ROC-AUC when one column is shuffled. ``predict_win_prob(df)`` must return P(win) for every row.

    Returns a DataFrame sorted from most to least important. A column the model ignores scores about 0."""
    rng = np.random.default_rng(seed)
    y = np.asarray(y)
    base = roc_auc_score(y, predict_win_prob(X))
    rows = []
    for c in columns:
        drops = []
        for _ in range(n_repeats):
            shuffled = X.copy()
            shuffled[c] = rng.permutation(shuffled[c].to_numpy())
            drops.append(base - roc_auc_score(y, predict_win_prob(shuffled)))
        rows.append((c, float(np.mean(drops)), float(np.std(drops))))
    out = pd.DataFrame(rows, columns=["feature", "importance", "std"]).sort_values("importance", ascending=False)
    out.attrs["baseline_auc"] = base
    return out.reset_index(drop=True)
