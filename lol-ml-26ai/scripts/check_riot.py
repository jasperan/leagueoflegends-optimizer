#!/usr/bin/env python
"""Check that RIOT_API_KEY works, with one cheap request (lol-status-v4). The key is never printed.

    export RIOT_API_KEY=RGAPI-...        # development key from https://developer.riotgames.com (valid 24 hours)
    python scripts/check_riot.py [--platform euw1]

Prints PASS, or FAIL plus the reason (missing key / 401 / 403 expired / 429 / unreachable). Exit code 0 only on PASS.
``RIOT_BASE_URL`` redirects the call (used with scripts/mock_riot.py).
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lolml.riot import PLATFORM_TO_REGION, RiotClient  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--platform", default="euw1", choices=sorted(PLATFORM_TO_REGION))
    a = ap.parse_args(argv)
    key = os.environ.get("RIOT_API_KEY", "").strip()
    if not key:
        print("FAIL: RIOT_API_KEY is not set. Get a development key at https://developer.riotgames.com "
              "and run: export RIOT_API_KEY=RGAPI-...")
        return 2
    ok, why = RiotClient(key, a.platform).check()
    print("PASS: Riot API key accepted" if ok else f"FAIL: {why}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
