#!/usr/bin/env python
"""OPTIONAL: download your own ranked matches from the Riot API into SQLite (puuid-based match-v5).

    export RIOT_API_KEY=RGAPI-...                 # development key, valid 24 hours
    python scripts/check_riot.py                  # is the key good?
    python scripts/extract_live.py --platform euw1 --tier challenger --players 5 --matches 10
    python scripts/export_extract.py              # -> $LOLML_HOME/data/my_matches.parquet

Development keys allow 20 requests/second and 100 requests/2 minutes; this script stays under both, so about
100 matches take a few minutes. Exit code is non-zero on an auth error or when no rows were written.
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lolml import riot  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--platform", default="euw1", choices=sorted(riot.PLATFORM_TO_REGION))
    ap.add_argument("--tier", default="challenger", choices=["challenger", "grandmaster", "master"])
    ap.add_argument("--players", type=int, default=5, help="top N players of the tier (default 5)")
    ap.add_argument("--matches", type=int, default=10, help="recent ranked-solo matches per player, 1-100 (default 10)")
    ap.add_argument("--db", default="riot_extract.db", help="SQLite file (default riot_extract.db)")
    a = ap.parse_args(argv)

    key = os.environ.get("RIOT_API_KEY", "").strip()
    if not key:
        print("FAIL: RIOT_API_KEY is not set. Get a development key at https://developer.riotgames.com.")
        return 2
    con = riot.open_db(a.db)
    try:
        client = riot.RiotClient(key, a.platform)
        res = riot.extract(client, con, a.players, a.matches, a.tier)
    except riot.RiotAuthError as e:
        print(f"FAIL (auth): {e}")
        return 1
    except (riot.RiotRateLimitError, OSError, RuntimeError) as e:  # requests errors are OSErrors
        print(f"FAIL: {type(e).__name__}: {e}")
        return 1
    total = con.execute("SELECT COUNT(*) FROM performance").fetchone()[0]
    n_matches = con.execute("SELECT COUNT(*) FROM matches WHERE fetched = 1").fetchone()[0]
    print(f"players {res['players']}  matches downloaded this run {res['matches']} (skipped {res['skipped']})  "
          f"new performance rows {res['rows']}  API calls {res['api_calls']}  429s {res['rate_limited']}")
    print(f"{a.db} now holds {n_matches} matches and {total} performance rows")
    if res["rows"] == 0:
        print("FAIL: no new rows were written. (Re-running with a bigger --matches/--players fetches more; "
              "already stored matches are skipped.)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
