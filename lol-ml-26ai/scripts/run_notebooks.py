#!/usr/bin/env python
"""Execute notebooks headless with the current Python interpreter (no Jupyter kernel registration needed).

    python scripts/run_notebooks.py                      # core notebooks (01-04, 07), full data
    LOLML_SMOKE=1 python scripts/run_notebooks.py        # small committed sample, short budgets (about 3 minutes)
    python scripts/run_notebooks.py 01 03                # only notebooks whose file name starts with 01 or 03

Executed copies (with outputs) go to $LOLML_HOME/outputs/executed/; the notebooks in the repo stay clean.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import nbformat
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lolml import paths  # noqa: E402

CORE = ["01", "02", "03", "04", "07"]
wanted = sys.argv[1:] or CORE

# A throw-away kernelspec that launches THIS interpreter. Using our own kernel name avoids picking up an
# unrelated "python3" kernel registered in your home directory.
kdir = Path(tempfile.mkdtemp()) / "kernels" / "lolml-run"
kdir.mkdir(parents=True)
(kdir / "kernel.json").write_text(json.dumps({
    "argv": [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
    "display_name": "lolml-run", "language": "python"}))
os.environ["JUPYTER_PATH"] = str(kdir.parent.parent)

out_dir = paths.OUT / "executed"
out_dir.mkdir(parents=True, exist_ok=True)
failed = []
for nb_path in sorted((ROOT / "notebooks").glob("*.ipynb")):
    if not any(nb_path.name.startswith(w) for w in wanted):
        continue
    t0 = time.time()
    nb = nbformat.read(nb_path, as_version=4)
    client = NotebookClient(nb, kernel_name="lolml-run", timeout=3600, resources={"metadata": {"path": str(nb_path.parent)}})
    try:
        client.execute()
        status = "PASS"
    except Exception as e:  # noqa: BLE001
        status = f"FAIL: {type(e).__name__}: {str(e).splitlines()[-1] if str(e) else ''}"
        failed.append(nb_path.name)
    nbformat.write(nb, out_dir / nb_path.name)
    print(f"{status:<8} {nb_path.name}  ({time.time() - t0:.0f}s)", flush=True)
sys.exit(1 if failed else 0)
