"""Plain-script tests (pytest also works): Live Client payload conversion, team detection, replay + mock server.
Run:  python tests/test_liveclient.py"""
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lolml import data, liveclient  # noqa: E402
from lolml.features import BYMIN_LIVE_SAFE  # noqa: E402


def test_example_payload_to_features():
    payload = json.loads(liveclient.EXAMPLE.read_text())
    f = liveclient.features_from_payload(payload)
    assert list(f) == BYMIN_LIVE_SAFE
    assert f["timestamp"] == payload["gameData"]["gameTime"] * 1000  # seconds -> milliseconds
    assert f["maxhealth"] == payload["activePlayer"]["championStats"]["maxHealth"]


def test_round_trip_through_payload():
    mid, frames = liveclient.recorded_match(data.load("by_minute"))
    for _, row in frames.iloc[::7].iterrows():
        back = liveclient.features_from_payload(liveclient.payload_from_row(row))
        for k in BYMIN_LIVE_SAFE:
            assert abs(back[k] - float(row[k])) < 1e-6, k


def test_team_comes_from_the_active_player_not_the_first_player():
    payload = liveclient.payload_from_row(data.load("by_minute").iloc[0], team="CHAOS")
    assert liveclient.active_team(payload) == "CHAOS"
    payload["allPlayers"].insert(0, {"summonerName": "Someone", "riotId": "Someone#1", "team": "ORDER", "isBot": False})
    assert liveclient.active_team(payload) == "CHAOS"


def test_mock_server_replays_a_recorded_match():
    _, frames = liveclient.recorded_match(data.load("by_minute"))
    srv = liveclient.MockLiveClient(frames, "ORDER", speed=1000.0, port=29991).start()
    try:
        r = requests.get("http://127.0.0.1:29991/liveclientdata/allgamedata", timeout=5)
        assert r.status_code == 200 and "championStats" in r.json()["activePlayer"]
        assert requests.get("http://127.0.0.1:29991/nope", timeout=5).status_code == 404
    finally:
        srv.stop()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
