"""OCI Data Science Model Deployment entry point (model artifact `score.py`).

A model artifact is a folder (zipped) with this file, ``runtime.yaml`` and the model files. The service calls
``load_model()`` once and ``predict(data, model)`` for every request. The same functions run on a laptop:

    python -c "import score, json; m = score.load_model(); print(score.predict({'instances': [...]}, m))"

Request:  {"instances": [{"magicresist": 40.0, "timestamp": 600000, ...}]}
Response: {"win_probability": [0.55]}
"""
import json
import os

import joblib
import pandas as pd

_HERE = os.path.dirname(os.path.realpath(__file__))


def load_model():
    meta = json.load(open(os.path.join(_HERE, "win_by_minute.json")))
    return {"model": joblib.load(os.path.join(_HERE, "win_by_minute.joblib")), "features": meta["features"]}


def predict(data, model=None):
    model = model or load_model()
    if isinstance(data, str):
        data = json.loads(data)
    df = pd.DataFrame(data["instances"])[model["features"]]
    return {"win_probability": [float(p) for p in model["model"].predict_proba(df)[:, 1]]}
