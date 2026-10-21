"""Build the "games like this" embeddings in the database (PLAYER_GAME_VECTOR) and the vector index.

    python scripts/db_vectors.py            # (re)build: compute in Python, insert, create the vector index
    LOLML_SMOKE=1 python scripts/db_vectors.py

Run scripts/db_load.py first. 95% of matches are embedded and stored; 5% (lolml.db.is_holdout) are kept out so that
scripts/db_similar.py and notebook 06 can search with games the database has never seen. The z-score mean/std is
computed on the stored games and saved in VECTOR_NORM, so a new game can be embedded exactly the same way.
"""
from __future__ import annotations

import array
import sys
import time
from pathlib import Path

import numpy as np
import oracledb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lolml import data, db  # noqa: E402


def main() -> None:
    try:
        conn = db.connect()
    except db.DbConfigError as e:
        raise SystemExit(f"error: {e}")
    print(f"connected: {db.banner(conn)[:80]}")
    with conn:
        for line in db.run_script(conn, "04_vector.sql"):
            print("  |", line)
        n_pm = conn.cursor().execute("select count(*) from player_match").fetchone()[0]
        df = data.load("performance")
        if n_pm != len(df):
            raise SystemExit(f"PLAYER_MATCH has {n_pm:,} rows but the dataframe has {len(df):,}. "
                             "Run: python scripts/db_load.py --truncate (same LOLML_SMOKE setting)")
        t0 = time.time()
        hold = db.is_holdout(df["match_id"])
        keep = ~hold
        rates = db.rate_features(df)
        mean, std = rates[keep].mean(axis=0), rates[keep].std(axis=0)
        emb = ((rates - mean) / std).astype("float32")
        ids = np.arange(1, len(df) + 1)[keep]
        emb = emb[keep]
        print(f"embedded {keep.sum():,} games ({hold.sum():,} held out) into {db.VECTOR_DIM} dimensions "
              f"in {time.time() - t0:.1f}s")

        with conn.cursor() as cur:
            cur.execute("DROP INDEX IF EXISTS player_game_vec_hnsw")
            cur.execute("DROP INDEX IF EXISTS player_game_vec_ivf")
            cur.execute("truncate table player_game_vector")
            cur.execute("truncate table vector_norm")
            cur.executemany(
                "insert into vector_norm (feature_order, feature_name, mean_value, std_value) values (:1, :2, :3, :4)",
                [(i + 1, name, float(mean[i]), float(std[i])) for i, (name, _) in enumerate(db.VECTOR_FEATURES)])
            cur.setinputsizes(None, oracledb.DB_TYPE_VECTOR)
            t0, batch = time.time(), 20_000
            for s in range(0, len(ids), batch):
                rows = [(int(i), array.array("f", v.tolist())) for i, v in zip(ids[s:s + batch], emb[s:s + batch])]
                cur.executemany("insert into player_game_vector (player_match_id, embedding) values (:1, :2)", rows)
                conn.commit()
            print(f"inserted {len(ids):,} vectors in {time.time() - t0:.1f}s")
        t0 = time.time()
        for line in db.run_script(conn, "04b_vector_index.sql"):
            print("  |", line)
        print(f"vector index step took {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
