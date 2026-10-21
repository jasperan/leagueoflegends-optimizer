"""Download, sample and load the two workshop datasets.

* ``performance`` - one row per player per finished match (post-game stats, about 100 columns).
  Source: Kaggle ``jasperan/league-of-legends-optimizer-dataset`` / ``sqlite_report_performance.csv``.
  We keep every 6th match (chosen by a hash of the match id, so the sample is reproducible) and drop
  every column that identifies a player.
* ``by_minute`` - one row per player per snapshot during a match (18 in-game stats, what the Live Client
  API shows). Source: Kaggle ``jasperan/league-of-legends-1v1-matchups-results`` / ``matchups_livelabs.csv``.

Both files are public and are fetched anonymously (no Kaggle login). The downloaded bytes are verified with
the ZIP CRC-32 and with the SHA-256 pinned in ``data/checksums.json``.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import paths
from .remote import open_remote_zip

CHECKSUMS = paths.ROOT / "data" / "checksums.json"

SOURCES = {
    "performance": dict(
        owner="jasperan", dataset="league-of-legends-optimizer-dataset",
        member="sqlite_report_performance.csv", out="performance.parquet",
    ),
    "by_minute": dict(
        owner="jasperan", dataset="league-of-legends-1v1-matchups-results",
        member="matchups_livelabs.csv", out="by_minute.parquet",
    ),
}

# Columns that identify a person, or carry no information. They never reach the sample.
PII_COLUMNS = ["puuid", "summonerId", "summonerName", "riotIdName", "riotIdTagline", "profileIcon", "summonerLevel"]
DROP_COLUMNS = ["Unnamed: 0", "sightWardsBoughtInGame", "unrealKills"]

KEEP_EVERY = 6  # 1 match in 6


class _Sha256Reader:
    """File-like wrapper that hashes everything read through it."""

    def __init__(self, fh):
        self.fh, self.h, self.n = fh, hashlib.sha256(), 0

    def read(self, size: int = -1) -> bytes:
        b = self.fh.read(size)
        self.h.update(b)
        self.n += len(b)
        return b

    def readable(self) -> bool:
        return True


def _pins() -> dict:
    return json.loads(CHECKSUMS.read_text()) if CHECKSUMS.exists() else {}


def _hash_ids(ids: np.ndarray) -> np.ndarray:
    """splitmix64 finaliser: spreads sequential match ids evenly."""
    x = ids.astype(np.uint64) + np.uint64(0x9E3779B97F4A7C15)
    x = (x ^ (x >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
    x = (x ^ (x >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
    return x ^ (x >> np.uint64(31))


def _clean_performance(chunk: pd.DataFrame) -> pd.DataFrame:
    chunk = chunk.rename(columns={"match_identifier": "match_id"})
    chunk = chunk[(_hash_ids(chunk["match_id"].to_numpy()) % np.uint64(KEEP_EVERY)) == 0]
    return chunk.drop(columns=PII_COLUMNS + DROP_COLUMNS, errors="ignore")


def _finalise_performance(df: pd.DataFrame) -> pd.DataFrame:
    """Keep complete matches only (10 players, 5 winners) and fix the minutes column."""
    df = df.copy()
    df["match_id"] = df["match_id"].astype("int64")
    df["duration"] = df["timePlayed"] / 60.0  # the original column mixes ms and minutes across patches
    g = df.groupby("match_id")["win"]
    ok = (g.transform("size") == 10) & (g.transform("sum") == 5) & (df["timePlayed"] >= 300)  # no remakes
    return df[ok].drop(columns=["f1", "f2", "f3", "f4", "f5"]).reset_index(drop=True)


def _clean_by_minute(df: pd.DataFrame) -> pd.DataFrame:
    df = df.drop(columns=[c for c in df.columns if c.startswith("Unnamed")])
    df.columns = [c.lower() for c in df.columns]
    parts = df["identifier"].str.rsplit("_", n=1)
    df.insert(0, "match_id", parts.str[0])
    df.insert(1, "slot", parts.str[1].astype(int))  # 1-5 blue side, 6-10 red side
    df["minute"] = df["timestamp"] / 60000.0
    return df.drop(columns=["identifier"])


def fetch(name: str, verify: bool = True) -> dict:
    """Download one dataset (about 0.4 GB for ``performance``, 23 MB for ``by_minute``) and write a parquet file."""
    spec, pins = SOURCES[name], _pins().get(name, {})
    paths.ensure_dirs()
    out = paths.DATA / spec["out"]
    print(f"[{name}] opening Kaggle zip {spec['owner']}/{spec['dataset']} ...", flush=True)
    z = open_remote_zip(spec["owner"], spec["dataset"])
    info = z.getinfo(spec["member"])
    print(f"[{name}] streaming {spec['member']} ({info.compress_size / 1e6:.0f} MB compressed)", flush=True)
    with z.open(spec["member"]) as fh:
        rd = _Sha256Reader(fh)
        if name == "performance":
            parts = [_clean_performance(c) for c in pd.read_csv(rd, chunksize=200_000, low_memory=False)]
            df = _finalise_performance(pd.concat(parts, ignore_index=True))
        else:
            df = _clean_by_minute(pd.read_csv(rd, low_memory=False))
        while rd.read(1 << 20):  # drain so the CRC-32 and the hash cover the whole member
            pass
    sha = rd.h.hexdigest()
    print(f"[{name}] source sha256 {sha}  ({rd.n:,} bytes, CRC-32 checked by zipfile)")
    if verify and pins.get("source_sha256") and pins["source_sha256"] != sha:
        sys.exit(f"[{name}] CHECKSUM MISMATCH: expected {pins['source_sha256']}\nThe public file changed. "
                 "Re-run with --no-verify only if you accept the new data.")
    if verify and pins.get("rows") and pins["rows"] != len(df):
        sys.exit(f"[{name}] expected {pins['rows']:,} rows, got {len(df):,}")
    df.to_parquet(out, index=False)
    print(f"[{name}] wrote {out} ({len(df):,} rows, {df.shape[1]} columns)")
    return {"source_sha256": sha, "source_bytes": rd.n, "rows": len(df), "columns": df.shape[1]}


def path_for(name: str, smoke: bool = False) -> Path:
    """Where a dataset lives. LOLML_PERFORMANCE_FILE points the post-game data at your own parquet file
    (for example the one scripts/export_extract.py wrote from your Riot API extraction)."""
    import os
    if name == "performance" and os.environ.get("LOLML_PERFORMANCE_FILE"):
        return Path(os.environ["LOLML_PERFORMANCE_FILE"])
    spec = SOURCES[name]
    if smoke:
        return paths.SAMPLE / spec["out"]
    return paths.DATA / spec["out"]


def load(name: str, smoke: bool | None = None) -> pd.DataFrame:
    """Load a dataset. ``smoke=None`` uses the full file if it was downloaded, else the small committed sample."""
    import os
    if smoke is None:
        smoke = (bool(os.environ.get("LOLML_SMOKE")) or not path_for(name).exists()) and not (
            name == "performance" and os.environ.get("LOLML_PERFORMANCE_FILE"))
    p = path_for(name, smoke)
    if not p.exists():
        raise FileNotFoundError(f"{p} not found. Run: python scripts/fetch_data.py")
    print(f"loading {p.relative_to(paths.ROOT) if p.is_relative_to(paths.ROOT) else p}"
          f"{'  [small committed sample]' if smoke else ''}")
    df = pd.read_parquet(p)
    if name == "performance":
        df["match_id"] = df["match_id"].astype("int64")
    return df
