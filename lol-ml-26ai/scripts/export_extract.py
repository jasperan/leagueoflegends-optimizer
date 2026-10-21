#!/usr/bin/env python
"""Turn the SQLite file written by extract_live.py into a parquet file with the SAME columns, order and dtypes as
``lolml.data.load('performance')``, so the notebooks can use your own matches instead of the downloaded dataset.

    python scripts/export_extract.py [--db riot_extract.db] [--out $LOLML_HOME/data/my_matches.parquet]

What changes on the way:
  * ``match_id`` 'EUW1_7234567890' -> 7234567890 (the numeric game id, as in the dataset); ``puuid`` and
    ``game_version`` are dropped (no player identifiers in the output);
  * ``duration`` = timePlayed / 60 (minutes, same as the dataset);
  * ``calculated_player_performance`` is recomputed with the formula of the original src/process_performance.py:
        100 * (0.336 - 1.437 deaths/min + 0.000117 gold/min + 0.443 (kills+assists)/min + 0.264 level/min
               + 0.000013 damage/min)
    The original divided by Riot's ``gameDuration``; here timePlayed/60 is used. On the 226,910-row dataset this
    reproduces the stored column with R^2 = 0.9887 (99.0 % of rows within 2 points, R^2 = 0.99997 on those);
  * only complete matches are kept (10 players, 5 winners, at least 5 minutes), like the dataset;
  * empty strings (the API sends '' for an unassigned position) become missing values, like the CSV.
"""
import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lolml import paths  # noqa: E402
from lolml.riot import TEXT_FIELDS  # noqa: E402

TARGET_PARQUET = "my_matches.parquet"


def calculated_performance(df: pd.DataFrame) -> pd.Series:
    m = df["duration"]
    score = (0.336 - 1.437 * df["deaths"] / m + 0.000117 * df["goldEarned"] / m
             + 0.443 * (df["kills"] + df["assists"]) / m + 0.264 * df["champLevel"] / m
             + 0.000013 * df["totalDamageDealt"] / m)
    return (score * 100).round(2)


def dataset_schema() -> pd.Series:
    """column -> dtype of the workshop dataset (the committed sample has exactly the same schema as the full file)."""
    return pd.read_parquet(paths.SAMPLE / "performance.parquet").dtypes


def to_dataset_frame(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    df["match_id"] = df["match_id"].str.rsplit("_", n=1).str[1].astype("int64")
    df = df.drop(columns=["puuid", "game_version"])
    df["duration"] = df["timePlayed"] / 60.0
    g = df.groupby("match_id")["win"]
    df = df[(g.transform("size") == 10) & (g.transform("sum") == 5) & (df["timePlayed"] >= 300)].copy()
    for c in TEXT_FIELDS:
        df[c] = df[c].where(df[c] != "", np.nan)
    df["calculated_player_performance"] = calculated_performance(df)
    schema = dataset_schema()
    missing = set(schema.index) - set(df.columns)
    extra = set(df.columns) - set(schema.index)
    if missing or extra:
        raise SystemExit(f"schema mismatch: missing {sorted(missing)}, unexpected {sorted(extra)}")
    return df[list(schema.index)].astype(schema.to_dict()).reset_index(drop=True)


def export(db: str, out: Path) -> pd.DataFrame:
    con = sqlite3.connect(db)
    try:
        raw = pd.read_sql_query("SELECT * FROM performance", con)
    finally:
        con.close()
    if raw.empty:
        raise SystemExit(f"{db} has no performance rows. Run scripts/extract_live.py first.")
    df = to_dataset_frame(raw)
    if df.empty:
        raise SystemExit("no complete matches left after cleaning (need 10 players, 5 winners, >= 5 minutes)")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return df


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", default="riot_extract.db")
    ap.add_argument("--out", type=Path, default=paths.DATA / TARGET_PARQUET)
    a = ap.parse_args(argv)
    df = export(a.db, a.out)
    print(f"wrote {a.out}: {len(df):,} rows, {df['match_id'].nunique():,} matches, {df.shape[1]} columns "
          f"(same schema as lolml.data.load('performance'))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
