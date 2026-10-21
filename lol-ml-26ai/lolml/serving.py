"""Train, save and load the small win-probability model that the serving lab uses.

Why LightGBM (scikit-learn API) and not the AutoGluon or fastai model from the earlier labs? The serving model must be small,
start fast, and load on a laptop, in a container or in an OCI Data Science Model Deployment without matching a big
framework version. A gradient-boosting model is small and exports cleanly to ONNX (scikit-learn's own HistGradientBoosting does not convert with skl2onnx 1.20).
"""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.metrics import accuracy_score, roc_auc_score

from . import data, paths
from .features import BYMIN_LIVE_SAFE, group_split

MODEL_NAME = "win_by_minute"


def train(smoke: bool | None = None, seed: int = 42) -> dict:
    """Fit on 80 % of the matches, report on the other 20 %, then save joblib + metadata next to it."""
    import sklearn
    df = data.load("by_minute", smoke)
    tr, te = group_split(df, 0.2, seed)
    a, b = df.iloc[tr], df.iloc[te]
    model = LGBMClassifier(n_estimators=100 if len(df) < 200_000 else 300, learning_rate=0.1, random_state=seed, verbose=-1)
    model.fit(a[BYMIN_LIVE_SAFE], a["winner"])
    p = model.predict_proba(b[BYMIN_LIVE_SAFE])[:, 1]
    meta = {
        "features": BYMIN_LIVE_SAFE, "target": "P(the player's team wins)", "scikit_learn": sklearn.__version__,
        "train_rows": len(a), "test_rows": len(b), "test_matches": int(b["match_id"].nunique()),
        "test_accuracy": round(float(accuracy_score(b["winner"], p > 0.5)), 4),
        "test_auc": round(float(roc_auc_score(b["winner"], p)), 4),
    }
    paths.MODELS.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, paths.MODELS / f"{MODEL_NAME}.joblib")
    (paths.MODELS / f"{MODEL_NAME}.json").write_text(json.dumps(meta, indent=2))
    return meta


def export_onnx(path: Path | None = None) -> Path:
    """Convert the saved model to ONNX (float32 inputs, probabilities as a plain tensor)."""
    from onnxmltools import convert_lightgbm
    from onnxmltools.convert.common.data_types import FloatTensorType
    model = joblib.load(paths.MODELS / f"{MODEL_NAME}.joblib")
    onx = convert_lightgbm(model, initial_types=[("input", FloatTensorType([None, len(BYMIN_LIVE_SAFE)]))],
                           zipmap=False, target_opset=15)
    out = path or paths.MODELS / f"{MODEL_NAME}.onnx"
    out.write_bytes(onx.SerializeToString())
    return out


class Scorer:
    """Load the joblib model (default) or the ONNX model and return P(win) for dict / DataFrame input."""

    def __init__(self, model_dir: Path | None = None, onnx: bool = False):
        d = Path(model_dir) if model_dir else paths.MODELS
        self.meta = json.loads((d / f"{MODEL_NAME}.json").read_text())
        self.features = self.meta["features"]
        self.onnx = onnx
        if onnx:
            import onnxruntime as ort
            self.sess = ort.InferenceSession(str(d / f"{MODEL_NAME}.onnx"), providers=["CPUExecutionProvider"])
        else:
            self.model = joblib.load(d / f"{MODEL_NAME}.joblib")

    def win_probability(self, rows: pd.DataFrame | dict | list[dict]) -> np.ndarray:
        df = pd.DataFrame([rows] if isinstance(rows, dict) else rows)[self.features]
        if self.onnx:
            out = self.sess.run(None, {self.sess.get_inputs()[0].name: df.to_numpy(np.float32)})
            return np.asarray(out[1])[:, 1]
        return self.model.predict_proba(df)[:, 1]
