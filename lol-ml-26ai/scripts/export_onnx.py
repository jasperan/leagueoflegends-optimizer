"""Train a scikit-learn win classifier and export it to ONNX so Oracle AI Database can score rows in SQL.

    python scripts/export_onnx.py                       # post-game model on the PLAYER_MATCH columns
    python scripts/export_onnx.py --model live          # live model on the BY_MINUTE_SNAPSHOT columns
    python scripts/export_onnx.py --algo logreg         # faster, simpler model
    LOLML_SMOKE=1 python scripts/export_onnx.py         # small sample (quick)

Writes $LOLML_HOME/models/lol_win_<kind>.onnx and a .json sidecar (features, in-database column names, the import
metadata, hold-out accuracy). scripts/db_score.py imports it into the database and checks parity.

What the database accepts (checked on Oracle AI Database 26ai Free 23.26.3): ONE float32 input tensor of shape
[batch, n_features] (initial type FloatTensorType), a classifier with ZipMap switched OFF so that the second output
is a plain [batch, 2] probabilities tensor, and `labels` in the import metadata so PREDICTION_PROBABILITY(model, 1 ...)
means P(win = 1). HistGradientBoostingClassifier is NOT used: skl2onnx 1.20 fails to convert it with onnx 1.23
("TypeError: Field onnx.AttributeProto.ints: Expected an int, got a boolean").
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lolml import data, db, features as F, paths  # noqa: E402


def training_frame(kind: str) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """(feature frame with database-column names, label, is_holdout mask). Hold-out matches never train the model."""
    src, cols = db.onnx_feature_columns(kind)
    if kind == "postgame":
        df = data.load("performance")
        honest = set(F.post_game_numeric(df))
        leaked = [c for c in src if c not in honest]
        if leaked:
            raise SystemExit(f"features not in post_game_numeric (leaks or non-numeric): {leaked}")
        X = df[src].copy()
        X["duration"] = X["duration"].round(2)  # the database column is NUMBER(6,2): train on what the database holds
        y = df[F.TARGET].to_numpy().astype(int)
        hold = db.is_holdout(df[F.GROUP])
    else:
        df = data.load("by_minute")
        X = df[src].copy()
        y = df["winner"].to_numpy().astype(int)
        ids = df["match_id"].str.split("_").str[1].astype("int64")
        hold = db.is_holdout(ids)
    X.columns = cols
    return X, y, hold


def build_model(algo: str):
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    if algo == "logreg":
        return make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)), "logistic regression"
    return GradientBoostingClassifier(n_estimators=100, max_depth=3, random_state=42), "gradient boosting (100 trees, depth 3)"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", choices=list(db.ONNX_MODELS), default="postgame")
    ap.add_argument("--algo", choices=["gb", "logreg"], default="gb")
    ap.add_argument("--max-train-rows", type=int, default=250_000, help="subsample very large training sets")
    args = ap.parse_args()

    from skl2onnx import convert_sklearn
    from skl2onnx.common.data_types import FloatTensorType
    from sklearn.metrics import accuracy_score, roc_auc_score
    import onnxruntime as ort

    paths.ensure_dirs()
    kind = args.model
    X, y, hold = training_frame(kind)
    tr = np.flatnonzero(~hold)
    if len(tr) > args.max_train_rows:
        tr = np.random.default_rng(42).choice(tr, args.max_train_rows, replace=False)
    te = np.flatnonzero(hold)
    Xtr, Xte = X.iloc[tr].to_numpy("float32"), X.iloc[te].to_numpy("float32")
    model, algo_desc = build_model(args.algo)
    t0 = time.time()
    model.fit(Xtr, y[tr])
    print(f"trained {algo_desc} on {len(tr):,} rows x {X.shape[1]} features in {time.time() - t0:.1f}s")
    proba = model.predict_proba(Xte)[:, 1]
    acc, auc = accuracy_score(y[te], proba > 0.5), roc_auc_score(y[te], proba)
    print(f"hold-out ({len(te):,} rows of matches never used for training): accuracy {acc:.4f}  AUC {auc:.4f}")

    final = model.steps[-1][1] if hasattr(model, "steps") else model
    onx = convert_sklearn(model, initial_types=[("float_input", FloatTensorType([None, X.shape[1]]))],
                          options={id(final): {"zipmap": False}})
    blob = onx.SerializeToString()

    sess = ort.InferenceSession(blob, providers=["CPUExecutionProvider"])
    ort_p = sess.run(["probabilities"], {"float_input": Xte})[0][:, 1]
    diff = float(np.abs(ort_p - proba).max())
    print(f"onnxruntime vs scikit-learn on the hold-out: max |difference| = {diff:.2e}")
    if diff > 1e-4:
        raise SystemExit("ONNX export does not reproduce scikit-learn: refusing to write the model")

    name = db.ONNX_MODELS[kind][0].lower()
    out = paths.MODELS / f"{name}.onnx"
    out.write_bytes(blob)
    sidecar = {
        "kind": kind, "model_name": db.ONNX_MODELS[kind][0], "table": db.ONNX_MODELS[kind][1],
        "label_column": db.ONNX_MODELS[kind][2], "algo": algo_desc, "n_train": int(len(tr)), "n_holdout": int(len(te)),
        "holdout_accuracy": round(float(acc), 4), "holdout_auc": round(float(auc), 4),
        "sklearn_vs_onnx_max_diff": diff, "sha256": hashlib.sha256(blob).hexdigest(),
        "features": db.onnx_feature_columns(kind)[0], "import_metadata": db.onnx_metadata(kind),
        "outputs": [(o.name, o.type) for o in sess.get_outputs()],
    }
    out.with_suffix(".json").write_text(json.dumps(sidecar, indent=2))
    print(f"wrote {out} ({len(blob) / 1024:.0f} KB) and {out.with_suffix('.json').name}")
    print("next: python scripts/db_score.py" + ("" if kind == "postgame" else " --model live"))


if __name__ == "__main__":
    main()
