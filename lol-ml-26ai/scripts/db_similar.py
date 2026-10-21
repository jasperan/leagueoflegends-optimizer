"""'Games like this': take a game the database has never seen, embed it, and list the 5 most similar stored games.

    python scripts/db_similar.py                      # a random held-out game
    python scripts/db_similar.py --seed 3 -k 10
    python scripts/db_similar.py --player-match-id 1234   # any row of the dataset (it must be a held-out one to be 'new')

Needs scripts/db_load.py and scripts/db_vectors.py to have run. The query game is embedded in Python with the mean/std
stored in VECTOR_NORM (lolml.db.embed), then the database does the nearest-neighbour search with VECTOR_DISTANCE.
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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=0, help="which random held-out game (default 0)")
    ap.add_argument("--player-match-id", type=int, help="use this PLAYER_MATCH_ID (1 = first row of the dataset)")
    ap.add_argument("-k", type=int, default=5, help="neighbours to return (default 5)")
    args = ap.parse_args()

    try:
        conn = db.connect()
    except db.DbConfigError as e:
        raise SystemExit(f"error: {e}")
    pd.set_option("display.width", 160)
    with conn:
        df = data.load("performance")
        if args.player_match_id:
            row_pos = args.player_match_id - 1
        else:
            hold = np.flatnonzero(db.is_holdout(df["match_id"]))
            row_pos = int(np.random.default_rng(args.seed).choice(hold))
        game = df.iloc[[row_pos]]
        g = game.iloc[0]
        print(f"query game: PLAYER_MATCH_ID={row_pos + 1}  {g['championName']} {g['teamPosition']}  "
              f"{int(g['kills'])}/{int(g['deaths'])}/{int(g['assists'])}  win={int(g['win'])}  "
              f"{g['duration']:.1f} min  (held out: {bool(db.is_holdout(game['match_id'])[0])})")

        mean, std = db.load_norm(conn)
        vec = db.embed(game, mean, std)[0]
        print("embedding:", [round(float(x), 2) for x in vec])

        db.games_like(conn, vec, args.k)  # warm-up: the first call also loads the index into memory
        t0 = time.time()
        approx = db.games_like(conn, vec, args.k)
        t_a = time.time() - t0
        t0 = time.time()
        exact = db.games_like(conn, vec, args.k, exact=True)
        t_e = time.time() - t0
        print(f"\nnearest {args.k} games (vector index, {t_a * 1000:.0f} ms):")
        print(approx.drop(columns="player_match_id").to_string(index=False))
        overlap = len(set(approx.player_match_id) & set(exact.player_match_id))
        print(f"\nexact scan: {t_e * 1000:.0f} ms, index result overlaps the exact top-{args.k} in {overlap}/{args.k} rows")
        print(f"win rate of these {args.k} similar games: {approx['win'].mean():.0%}")


if __name__ == "__main__":
    main()
