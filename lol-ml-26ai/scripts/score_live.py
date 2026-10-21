#!/usr/bin/env python
"""Poll the Live Client API (the game, or scripts/mock_liveclient.py) and print the win probability of your team.

    python scripts/score_live.py                                  # model on disk, http://127.0.0.1:2999
    python scripts/score_live.py --endpoint http://127.0.0.1:8080/predict     # model behind scripts/serve_local.py
    python scripts/score_live.py --base-url https://127.0.0.1:2999 --insecure  # the real client (self-signed certificate)

Private, local use only: read Riot's policy on in-game information before you build anything on top of this.
"""
import argparse
import sys
import time
from collections import deque
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lolml import liveclient  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--base-url", default="http://127.0.0.1:2999")
ap.add_argument("--insecure", action="store_true", help="do not verify the Live Client's self-signed certificate (https)")
ap.add_argument("--endpoint", help="POST features to this /predict URL instead of loading the model from disk")
ap.add_argument("--onnx", action="store_true")
ap.add_argument("--interval", type=float, default=1.0, help="seconds between requests")
ap.add_argument("--window", type=int, default=10, help="smooth over the last N predictions")
ap.add_argument("--max-polls", type=int, default=0, help="stop after N predictions (0 = until Ctrl+C)")
a = ap.parse_args()

if a.insecure:
    import urllib3
    urllib3.disable_warnings()
scorer = None
if not a.endpoint:
    from lolml import serving
    scorer = serving.Scorer(onnx=a.onnx)


def win_probability(feats: dict) -> float:
    if scorer:
        return float(scorer.win_probability(feats)[0])
    r = requests.post(a.endpoint, json={"instances": [feats]}, timeout=10)
    r.raise_for_status()
    return float(r.json()["win_probability"][0])


recent: deque[float] = deque(maxlen=a.window)
n = 0
print(f"polling {a.base_url}  (Ctrl+C to stop)")
try:
    while True:
        try:
            r = requests.get(f"{a.base_url}/liveclientdata/allgamedata", verify=not a.insecure, timeout=5)
            r.raise_for_status()
            payload = r.json()
        except requests.RequestException:
            print("no game found (is a match running, or is scripts/mock_liveclient.py started?) ...")
            time.sleep(max(a.interval, 3))
            continue
        feats = liveclient.features_from_payload(payload)
        p = win_probability(feats)
        recent.append(p)
        team = {"ORDER": "BLUE", "CHAOS": "RED"}.get(liveclient.active_team(payload), "?")
        print(f"minute {feats['timestamp'] / 60000:5.1f}  team {team:<4}  P(win) {p:6.1%}  smoothed({len(recent)}) {sum(recent) / len(recent):6.1%}", flush=True)
        n += 1
        if a.max_polls and n >= a.max_polls:
            break
        time.sleep(a.interval)
except KeyboardInterrupt:
    pass
