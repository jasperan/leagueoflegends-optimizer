"""Where data and models live. Override the root with the LOLML_HOME environment variable."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("LOLML_HOME", ROOT))
DATA = HOME / "data"
SAMPLE = ROOT / "data" / "sample"  # small files committed to git (no download needed)
MODELS = HOME / "models"
OUT = HOME / "outputs"


def ensure_dirs() -> None:
    for p in (DATA, MODELS, OUT):
        p.mkdir(parents=True, exist_ok=True)
