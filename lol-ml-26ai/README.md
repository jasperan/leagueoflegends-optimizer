# Can AI Win League of Legends? Machine Learning with OCI and Oracle AI Database 26ai

Code, notebooks and scripts for the LiveLabs workshop of the same name. It replaces three earlier labs (data extraction, model building with scikit-learn and AutoGluon, introduction to neural networks).

The core path needs **no Riot API key, no Kaggle account and no cloud account**. It runs on Python 3.12 on macOS (arm64) and Linux (x86_64).

## Quick start

```bash
cd lol-ml-26ai
uv venv --python 3.12 .venv && source .venv/bin/activate     # Windows: .venv\Scripts\Activate.ps1
uv pip install -r requirements.txt
bash scripts/smoke.sh          # about 3 minutes on the small committed sample, no download
python scripts/fetch_data.py   # the two public datasets (about 0.45 GB), checksum verified
python scripts/run_notebooks.py          # notebooks 01-04 and 07 on the full data (about 12 minutes)
```

Set `LOLML_SMOKE=1` to force the small sample, and `LOLML_HOME=/some/dir` to put data, models and outputs elsewhere.

## What is where

| Path | What |
| --- | --- |
| `notebooks/01_explore_and_baseline.ipynb` | scikit-learn baselines: draft, post-game, by minute |
| `notebooks/02_autogluon.ipynb` | AutoGluon with a validation set split by match |
| `notebooks/03_neural_network.ipynb` | hand-written PyTorch loop, fastai, fixed permutation importance, correct class order |
| `notebooks/04_leakage_and_splits.ipynb` | leakage ladder, formula target, row split versus match split |
| `notebooks/06_database_26ai.ipynb` | Oracle AI Database 26ai: load, SQL, vector search, ONNX scoring (needs a database) |
| `notebooks/07_genai_coach.ipynb` | post-game AI coach (calls OCI Generative AI only if `LOLML_GENAI_KEY` is set) |
| `lolml/` | shared code: data download, features, splits, Live Client conversion and mock, serving, database helpers, Riot client |
| `scripts/` | `fetch_data.py`, `train_serving_model.py`, `serve_local.py`, `mock_liveclient.py`, `score_live.py`, `db_*.py`, `extract_live.py`, `smoke.sh`, ... |
| `sql/`, `docker/` | database scripts and a local Oracle AI Database Free container |
| `model_deployment/score.py` | entry point for an OCI Data Science Model Deployment |
| `data/sample/` | small committed sample of both datasets and one recorded Live Client payload |

## Data

Downloaded anonymously from public Kaggle files by `scripts/fetch_data.py`, verified against `data/checksums.json`:

* `jasperan/league-of-legends-optimizer-dataset`, file `sqlite_report_performance.csv` (post-game rows; every sixth match is kept, player identifiers are dropped)
* `jasperan/league-of-legends-1v1-matchups-results`, file `matchups_livelabs.csv` (by-minute snapshots)

## Tests

```bash
python tests/test_liveclient.py    # Live Client conversion, replay and mock server
python tests/test_riot_mock.py     # Riot extraction against a local mock of the Riot API
python tests/test_coach.py         # percentiles, prompt, request shape (stub server)
python -m unittest tests.test_db   # database tests; skipped unless LOLML_DB_* variables are set
```

## Riot Games

This project is not endorsed by Riot Games. The optional extraction (`scripts/extract_live.py`) uses your own development key and the current puuid-based API. Read [Riot's developer policies](https://developer.riotgames.com/policies/general) before you build anything on top of live game data.
