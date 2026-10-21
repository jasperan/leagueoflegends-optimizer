"""Bulk-load the two datasets into PLAYER_MATCH and BY_MINUTE_SNAPSHOT (python-oracledb executemany, batched).

    python scripts/db_load.py                  # load both tables; a table that already has rows is left alone
    python scripts/db_load.py --truncate       # empty the tables first, then reload (idempotent)
    python scripts/db_load.py --only by_minute --batch 50000
    LOLML_SMOKE=1 python scripts/db_load.py    # the small committed sample (seconds), not the full download

Needs the tables from sql/02_tables.sql (python scripts/db_setup.py) and LOLML_DB_USER / _PASSWORD / _DSN.

The columns are read from the table definition, so adding a column to sql/02_tables.sql is enough: any dataframe
column whose name maps to it (camelCase -> CAMEL_CASE, see lolml.db.performance_column) gets loaded.

Alternative on Autonomous AI Database: skip the Python round trip and load straight from Object Storage with
DBMS_CLOUD.COPY_DATA. Upload the data as CSV (or Parquet, which DBMS_CLOUD reads natively) to a bucket, then:

    BEGIN
      DBMS_CLOUD.COPY_DATA(
        table_name      => 'PLAYER_MATCH',
        credential_name => 'OBJ_STORE_CRED',          -- DBMS_CLOUD.CREATE_CREDENTIAL, or OCI$RESOURCE_PRINCIPAL
        file_uri_list   => 'https://objectstorage.<region>.oraclecloud.com/n/<ns>/b/<bucket>/o/performance.parquet',
        format          => JSON_OBJECT('type' VALUE 'parquet', 'schemaorder' VALUE 'first',
                                       'ignoreblanklines' VALUE 'true'));   -- or 'type' VALUE 'csv', 'skipheaders' VALUE '1'
    END;
    /

COPY_DATA maps columns by name (parquet) or by position (csv), so it needs a staging table or view with the parquet
column names (camelCase) if you use it on the PLAYER_MATCH layout above. That is why the workshop default is this script.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lolml import data, db  # noqa: E402

TABLES = {
    # table -> (dataset name, surrogate key column)
    "PLAYER_MATCH": ("performance", "PLAYER_MATCH_ID"),
    "BY_MINUTE_SNAPSHOT": ("by_minute", "SNAPSHOT_ID"),
}


def column_lists(df: pd.DataFrame, table: str, db_cols: list[str], key_col: str) -> tuple[list[str], list[list]]:
    """Return (columns, python lists) for every table column we can fill from the dataframe."""
    if table == "PLAYER_MATCH":
        mapping = {db.performance_column(c): c for c in df.columns}
    else:
        mapping = {db.BYMIN_COLUMNS[c]: c for c in df.columns if c in db.BYMIN_COLUMNS}
    cols, lists = [], []
    for col in db_cols:
        if col == key_col:
            cols.append(col)
            lists.append(list(range(1, len(df) + 1)))
            continue
        if col not in mapping:
            print(f"  note: {table}.{col} has no matching dataframe column, left NULL")
            continue
        s = df[mapping[col]]
        if pd.api.types.is_numeric_dtype(s):
            arr = s.to_numpy(dtype="float64")
            mask = np.isnan(arr)
            if np.all(arr[~mask] == np.round(arr[~mask])):
                vals = np.where(mask, 0, arr).astype("int64").tolist()
            else:
                vals = np.where(mask, 0.0, np.round(arr, 5)).tolist()
            if mask.any():
                for i in np.flatnonzero(mask):
                    vals[i] = None
        else:
            vals = [None if (v is None or (isinstance(v, float) and v != v)) else v for v in s.tolist()]
        cols.append(col)
        lists.append(vals)
    return cols, lists


def load_table(conn, table: str, batch: int, truncate: bool) -> None:
    dataset, key_col = TABLES[table]
    with conn.cursor() as cur:
        cur.execute(f"select count(*) from {table}")
        existing = cur.fetchone()[0]
        if existing and not truncate:
            print(f"{table}: already has {existing:,} rows, skipping (use --truncate to reload)")
            return
        if truncate and existing:
            cur.execute(f"truncate table {table}")
            print(f"{table}: truncated {existing:,} rows")
            if table == "PLAYER_MATCH":  # embeddings refer to these ids, so they are stale now
                for dep in ("PLAYER_GAME_VECTOR", "VECTOR_NORM"):
                    cur.execute("select count(*) from user_tables where table_name = :t", t=dep)
                    if cur.fetchone()[0]:
                        cur.execute(f"truncate table {dep}")
                        print(f"{dep}: truncated (rebuild with scripts/db_vectors.py)")
        cur.execute("select column_name from user_tab_columns where table_name = :t order by column_id", t=table)
        db_cols = [r[0] for r in cur.fetchall()]
    if not db_cols:
        raise SystemExit(f"table {table} does not exist. Run: python scripts/db_setup.py")

    df = data.load(dataset)
    cols, lists = column_lists(df, table, db_cols, key_col)
    sql = f"insert into {table} ({', '.join(cols)}) values ({', '.join(f':{i + 1}' for i in range(len(cols)))})"
    n, t0 = len(df), time.time()
    print(f"{table}: loading {n:,} rows x {len(cols)} columns from '{dataset}' in batches of {batch:,}")
    with conn.cursor() as cur:
        for start in range(0, n, batch):
            rows = list(zip(*(l[start:start + batch] for l in lists)))
            cur.executemany(sql, rows)
            conn.commit()
            done = min(start + batch, n)
            rate = done / max(time.time() - t0, 1e-9)
            print(f"  {done:>9,} / {n:,}  ({rate:,.0f} rows/s)", end="\r" if sys.stdout.isatty() else "\n", flush=True)
    print(f"{table}: done in {time.time() - t0:.1f}s")
    with conn.cursor() as cur:
        cur.execute(f"select count(*) from {table}")
        got = cur.fetchone()[0]
    if got != n:
        raise SystemExit(f"{table}: expected {n:,} rows, table has {got:,}")
    print(f"{table}: verified {got:,} rows")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--truncate", action="store_true", help="empty the table(s) first, then reload")
    ap.add_argument("--only", choices=["performance", "by_minute"], help="load just one dataset")
    ap.add_argument("--batch", type=int, default=20_000, help="rows per executemany call (default 20000)")
    args = ap.parse_args()

    try:
        conn = db.connect()
    except db.DbConfigError as e:
        raise SystemExit(f"error: {e}")
    print(f"connected: {db.banner(conn)[:80]}")
    with conn:
        for table, (dataset, _) in TABLES.items():
            if args.only and args.only != dataset:
                continue
            load_table(conn, table, args.batch, args.truncate)


if __name__ == "__main__":
    main()
