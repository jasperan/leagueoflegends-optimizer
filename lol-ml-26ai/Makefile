# Run `make help`. Needs Python 3.12 (https://docs.astral.sh/uv/ installs it for you).
PY ?= .venv/bin/python

help:
	@echo "make setup    create .venv with Python 3.12 and install the pinned requirements"
	@echo "make data     download the two public datasets (about 0.45 GB, 2-4 minutes)"
	@echo "make smoke    run the whole core path on the small committed sample (about 3 minutes, no download)"
	@echo "make notebooks  run notebooks 01-04 on the full data"
	@echo "make lab      start JupyterLab"
	@echo "make db-up    start a local Oracle AI Database Free container (see docker/README.md)"

setup:
	uv venv --python 3.12 .venv
	uv pip install --python .venv/bin/python -r requirements.txt

data:
	$(PY) scripts/fetch_data.py

smoke:
	PYTHON=$(PY) bash scripts/smoke.sh

notebooks:
	$(PY) scripts/run_notebooks.py

lab:
	$(PY) -m jupyterlab notebooks

db-up:
	docker compose -f docker/compose.yaml up -d

.PHONY: help setup data smoke notebooks lab db-up
