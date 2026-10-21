#!/usr/bin/env python
"""Pretend to be the League of Legends Live Client Data API, so the serving lab works without the game.

    python scripts/mock_liveclient.py                  # the one recorded payload, game clock advancing
    python scripts/mock_liveclient.py --replay         # replay a recorded match (from the dataset) at 30x speed
    python scripts/mock_liveclient.py --replay --tls   # https like the real client (needs the openssl command)
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lolml import data, liveclient  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--replay", action="store_true", help="replay a recorded match instead of one static payload")
ap.add_argument("--match-id", help="which recorded match (default: the first in the dataset)")
ap.add_argument("--slot", type=int, default=1, help="which of the 10 players you 'are' (1-5 blue, 6-10 red)")
ap.add_argument("--speed", type=float, default=30.0, help="replay speed multiplier (default 30x)")
ap.add_argument("--port", type=int, default=2999)
ap.add_argument("--tls", action="store_true")
a = ap.parse_args()

frames, team = None, "ORDER"
if a.replay:
    mid, frames = liveclient.recorded_match(data.load("by_minute"), a.match_id, a.slot)
    team = "ORDER" if a.slot <= 5 else "CHAOS"
    print(f"replaying match {mid}, player slot {a.slot} ({team}), {len(frames)} snapshots, "
          f"{frames['minute'].iloc[-1]:.1f} game minutes, at {a.speed:g}x")
srv = liveclient.MockLiveClient(frames, team, a.speed, a.port, a.tls).start()
print(f"mock Live Client on {'https' if a.tls else 'http'}://127.0.0.1:{a.port}/liveclientdata/allgamedata  (Ctrl+C to stop)")
try:
    while True:
        time.sleep(3600)
except KeyboardInterrupt:
    srv.stop()
