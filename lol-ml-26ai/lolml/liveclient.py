"""Live Client Data API <-> model features, a recorded-match replayer and a mock of the local game server.

The real API (https://developer.riotgames.com/docs/lol#game-client-api) listens on https://127.0.0.1:2999 while a
game is running and needs no API key. Its ``activePlayer.championStats`` use different units from the match
timeline that the training data came from. We only use stats where the units agree:

  * magicResist, armor, maxHealth, currentHealth, moveSpeed, attackDamage, abilityPower, resourceMax,
    resourceValue are plain numbers in both sources;
  * gameTime is in seconds, the training ``timestamp`` is in milliseconds (x 1000).

Not used on purpose: attackSpeed (live: attacks per second, training: percent of base), healthRegenRate and
resourceRegenRate (per second vs per 5 seconds, different scaling) and the penetration/lifesteal stats (live:
multipliers such as 1.0, training: percent such as 0). Those need a conversion nobody has validated against a
live game, so the model does not see them.
"""
from __future__ import annotations

import copy
import json
import ssl
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pandas as pd

from . import paths
from .features import BYMIN_LIVE_SAFE

# training feature -> championStats key
_STAT_KEYS = {
    "magicresist": "magicResist", "maxhealth": "maxHealth", "movespeed": "moveSpeed", "attackdamage": "attackDamage",
    "abilitypower": "abilityPower", "currenthealth": "currentHealth", "armor": "armor",
    "resourcemax": "resourceMax", "resourcevalue": "resourceValue",
}
EXAMPLE = paths.ROOT / "data" / "sample" / "live_client_example.json"


def features_from_payload(payload: dict) -> dict[str, float]:
    """Turn one ``/liveclientdata/allgamedata`` response into the model's feature dict."""
    stats = payload["activePlayer"]["championStats"]
    row = {f: float(stats[k]) for f, k in _STAT_KEYS.items()}
    row["timestamp"] = float(payload["gameData"]["gameTime"]) * 1000.0
    return {f: row[f] for f in BYMIN_LIVE_SAFE}


def active_team(payload: dict) -> str | None:
    """'ORDER' (blue) or 'CHAOS' (red) for the local player. Matches activePlayer.riotId (or summonerName)."""
    ap = payload["activePlayer"]
    me = ap.get("riotId") or ap.get("summonerName")
    for p in payload.get("allPlayers", []):
        if me in (p.get("riotId"), p.get("summonerName")):
            return p.get("team")
    return None


def payload_from_row(row: pd.Series, template: dict | None = None, team: str = "ORDER") -> dict:
    """Build a Live Client-shaped payload from one by-minute row (for replaying a recorded match)."""
    d = copy.deepcopy(template or json.loads(EXAMPLE.read_text()))
    stats = d["activePlayer"]["championStats"]
    for f, k in _STAT_KEYS.items():
        stats[k] = float(row[f])
    d["gameData"]["gameTime"] = float(row["timestamp"]) / 1000.0
    for p in d["allPlayers"]:
        if p["summonerName"] == d["activePlayer"]["summonerName"]:
            p["team"] = team
    return d


def recorded_match(by_minute: pd.DataFrame, match_id: str | None = None, slot: int = 1) -> tuple[str, pd.DataFrame]:
    """One player's snapshots from a recorded match, oldest first. Defaults to the first match in the frame."""
    match_id = match_id or by_minute["match_id"].iloc[0]
    m = by_minute[(by_minute["match_id"] == match_id) & (by_minute["slot"] == slot)].sort_values("timestamp")
    if m.empty:
        raise KeyError(f"no rows for match {match_id} slot {slot}")
    return match_id, m.reset_index(drop=True)


class MockLiveClient:
    """Serves /liveclientdata/allgamedata like the game does. Either the single recorded payload (sample mode) or a
    recorded match replayed at ``speed`` x real time (replay mode). ``tls=True`` uses a throw-away self-signed
    certificate (the real client is https with a Riot-signed certificate; clients are told to skip verification)."""

    def __init__(self, frames: pd.DataFrame | None = None, team: str = "ORDER", speed: float = 30.0,
                 port: int = 2999, tls: bool = False):
        self.frames, self.team, self.speed, self.port, self.tls = frames, team, speed, port, tls
        self.template = json.loads(EXAMPLE.read_text())
        self.t0 = time.monotonic()
        self.httpd: ThreadingHTTPServer | None = None

    def payload(self) -> dict:
        elapsed = time.monotonic() - self.t0
        if self.frames is None:
            d = copy.deepcopy(self.template)
            d["gameData"]["gameTime"] = float(d["gameData"]["gameTime"]) + elapsed
            return d
        game_ms = self.frames["timestamp"].iloc[0] + elapsed * self.speed * 1000
        idx = min(int(self.frames["timestamp"].searchsorted(game_ms, side="right")) - 1, len(self.frames) - 1)
        return payload_from_row(self.frames.iloc[max(idx, 0)], self.template, self.team)

    def start(self) -> "MockLiveClient":
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                if self.path != "/liveclientdata/allgamedata":
                    self.send_response(404)
                    self.end_headers()
                    return
                body = json.dumps(outer.payload()).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), H)
        if self.tls:
            tmp = Path(tempfile.mkdtemp())
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=127.0.0.1",
                            "-keyout", str(tmp / "k.pem"), "-out", str(tmp / "c.pem")], check=True, capture_output=True)
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(tmp / "c.pem", tmp / "k.pem")
            self.httpd.socket = ctx.wrap_socket(self.httpd.socket, server_side=True)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
