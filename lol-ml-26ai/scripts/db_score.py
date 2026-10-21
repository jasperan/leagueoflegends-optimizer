"""Import an ONNX model into the database, score rows with SQL, and prove it matches onnxruntime in Python.

    python scripts/export_onnx.py                 # once: train + export (writes $LOLML_HOME/models/lol_win_postgame.onnx)
    python scripts/db_score.py                    # stage + import + SQL scoring + parity check
    python scripts/db_score.py --model live       # the live-safe model on BY_MINUTE_SNAPSHOT

Steps: 05a creates ONNX_MODEL_STAGE, this script uploads the .onnx file (BLOB) and its import metadata, 05b runs
DBMS_DATA_MINING.IMPORT_ONNX_MODEL, then PREDICTION_PROBABILITY is evaluated in SQL on hold-out rows and compared with
onnxruntime run on the very same numbers fetched from the table. If the database does not support ONNX import, the
exact ORA- error is printed and the script exits non-zero (nothing is faked).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lolml import db, paths  # noqa: E402


def stage_and_import(conn, kind: str) -> dict:
    name, table, label = db.ONNX_MODELS[kind]
    onnx_path = paths.MODELS / f"{name.lower()}.onnx"
    side = onnx_path.with_suffix(".json")
    if not onnx_path.exists():
        raise SystemExit(f"{onnx_path} not found. Run: python scripts/export_onnx.py"
                         + ("" if kind == "postgame" else " --model live"))
    sidecar = json.loads(side.read_text())
    for line in db.run_script(conn, "05a_onnx_stage.sql"):
        print("  |", line)
    with conn.cursor() as cur:
        cur.execute("delete from onnx_model_stage where model_name = :n", n=name)
        cur.execute("insert into onnx_model_stage (model_name, onnx_model, metadata) values (:n, :b, json(:m))",
                    n=name, b=onnx_path.read_bytes(), m=json.dumps(sidecar["import_metadata"]))
    conn.commit()
    t0 = time.time()
    # Import only this model: the stage table may hold others.
    with conn.cursor() as cur:
        try:
            cur.execute("""
              begin
                begin dbms_data_mining.drop_model(:n, force => true); exception when others then null; end;
                for s in (select onnx_model, metadata from onnx_model_stage where model_name = :n) loop
                  dbms_data_mining.import_onnx_model(:n, s.onnx_model, s.metadata);
                end loop;
              end;""", n=name)
        except Exception as e:  # report the real database error
            raise SystemExit(f"IMPORT_ONNX_MODEL failed on this database: {e}")
    print(f"imported {name} in {time.time() - t0:.2f}s")
    return sidecar


def parity(conn, kind: str, sidecar: dict, limit: int) -> None:
    import onnxruntime as ort
    name, table, label = db.ONNX_MODELS[kind]
    cols = db.onnx_feature_columns(kind)[1]
    key = "player_match_id" if kind == "postgame" else "snapshot_id"
    holdout = ("mod(match_id, 20) = 7" if kind == "postgame"
               else "mod(to_number(substr(match_id, instr(match_id, '_') + 1)), 20) = 7")
    sql = (f"select {key}, {', '.join(cols)}, {label}, "
           f"prediction({name} using *) as label_db, prediction_probability({name}, 1 using *) as p_db "
           f"from {table} where {holdout} order by {key} fetch first {int(limit)} rows only")
    t0 = time.time()
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = np.array(cur.fetchall(), dtype="float64")
    t_db = time.time() - t0
    X = rows[:, 1:1 + len(cols)].astype("float32")
    y, lab_db, p_db = rows[:, -3], rows[:, -2], rows[:, -1]

    sess = ort.InferenceSession(str(paths.MODELS / f"{name.lower()}.onnx"), providers=["CPUExecutionProvider"])
    t0 = time.time()
    p_py = sess.run(["probabilities"], {"float_input": X})[0][:, 1].astype("float64")
    t_py = time.time() - t0

    diff = np.abs(p_db - p_py)
    print(f"\nparity on {len(rows):,} hold-out rows of {table}:")
    print(f"  SQL PREDICTION_PROBABILITY vs onnxruntime: max |diff| = {diff.max():.2e}, mean {diff.mean():.2e}")
    print(f"  predicted labels identical: {(lab_db == (p_py > 0.5)).mean():.2%}")
    print(f"  accuracy in SQL {(lab_db == y).mean():.4f}   in Python {((p_py > 0.5) == y).mean():.4f}"
          f"   (sklearn hold-out accuracy recorded at export: {sidecar['holdout_accuracy']})")
    print(f"  time: SQL fetch+score {t_db:.2f}s, onnxruntime {t_py:.3f}s")
    if diff.max() > 1e-4:
        raise SystemExit("PARITY FAILED: database and onnxruntime disagree")
    print("  parity OK")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", choices=list(db.ONNX_MODELS), default="postgame")
    ap.add_argument("--rows", type=int, default=20_000, help="hold-out rows for the parity check")
    args = ap.parse_args()
    try:
        conn = db.connect()
    except db.DbConfigError as e:
        raise SystemExit(f"error: {e}")
    print(f"connected: {db.banner(conn)[:80]}")
    with conn:
        sidecar = stage_and_import(conn, args.model)
        name = db.ONNX_MODELS[args.model][0]
        print(db.query_df(conn, "select model_name, mining_function, algorithm from user_mining_models "
                                "where model_name = :n", {"n": name}).to_string(index=False))
        parity(conn, args.model, sidecar, args.rows)


if __name__ == "__main__":
    main()
