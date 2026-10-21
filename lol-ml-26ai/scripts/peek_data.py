#!/usr/bin/env python
"""Print what is in the two datasets (Lab 2)."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lolml import data  # noqa: E402

pd.set_option("display.width", 160)
perf = data.load("performance")
print(f"\npost-game: {len(perf):,} rows, {perf['match_id'].nunique():,} matches, {perf.shape[1]} columns, "
      f"rows per match: {[int(n) for n in sorted(perf.groupby('match_id').size().unique())]}, share of wins: {perf['win'].mean():.2f}")
print(f"{perf['championName'].nunique()} champions, game length median {perf['duration'].median():.1f} min "
      f"(min {perf['duration'].min():.1f}, max {perf['duration'].max():.1f})")
print(perf[["match_id", "championName", "teamPosition", "kills", "deaths", "assists", "goldEarned", "duration", "win"]].head(5).to_string())

bym = data.load("by_minute")
per_player = bym.groupby(["match_id", "slot"]).size()
print(f"\nby minute: {len(bym):,} rows, {bym['match_id'].nunique():,} matches, {bym.shape[1]} columns, "
      f"{per_player.mean():.1f} snapshots per player per match")
print(bym[["match_id", "slot", "minute", "maxhealth", "attackdamage", "armor", "winner"]].head(4).to_string())
