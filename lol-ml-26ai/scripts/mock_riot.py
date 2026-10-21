#!/usr/bin/env python
"""MOCK of the Riot Games API - NOT Riot, NOT real data sources beyond the committed workshop sample.

A local HTTP server (stdlib only) that imitates the endpoints ``lolml.riot`` calls, so the optional live-extraction
path can be developed and tested without a Riot key:

  GET /lol/status/v4/platform-data
  GET /lol/league/v4/{challenger,grandmaster,master}leagues/by-queue/RANKED_SOLO_5x5   -> entries carry ``puuid``
  GET /lol/match/v5/matches/by-puuid/{puuid}/ids?queue=420&start=0&count=N
  GET /lol/match/v5/matches/{matchId}                                                    -> 10 participants

What is faked and what is not:
  * The 95 post-game stat fields of every participant are REAL rows copied from
    ``data/sample/performance.parquet`` (one sampled match per mock match; mock match id = ``EUW1_<real gameId>``).
  * All other ParticipantDto fields (the 64 absent from the dataset, per Riot's OpenAPI: pings, augments,
    ``challenges``/``missions``/``perks``/``PlayerBehavior`` dictionaries, identity fields) are made up; puuids are
    random-looking hashes of a fixed seed string. 159 fields in total, like the live schema.
  * ``X-Riot-Token`` is enforced: missing -> 401, anything but the configured key -> 403 (this is how Riot answers).
  * ``--rate-limit-once`` makes the first match-detail request answer 429 + ``Retry-After: 1``.
  * No real rate limit is simulated and no timing resembles Riot's.

    python scripts/mock_riot.py --port 8765 --key MOCK-KEY
    RIOT_BASE_URL=http://127.0.0.1:8765 RIOT_API_KEY=MOCK-KEY python scripts/extract_live.py --db /tmp/x.db
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd  # noqa: E402

from lolml import paths  # noqa: E402

DEFAULT_KEY = "RGAPI-MOCK-0000"
PLATFORM_ID = "EUW1"
GAME_VERSION = "15.14.123.4567"

# ParticipantDto fields outside the dataset (Riot OpenAPI, 2025): name -> kind
_EXTRA_INT = [
    "allInPings", "assistMePings", "commandPings", "enemyMissingPings", "enemyVisionPings", "holdPings",
    "getBackPings", "needVisionPings", "onMyWayPings", "placement", "playerAugment1", "playerAugment2",
    "playerAugment3", "playerAugment4", "playerSubteamId", "pushPings", "profileIcon", "sightWardsBoughtInGame",
    "subteamPlacement", "summonerLevel", "totalAllyJungleMinionsKilled", "totalEnemyJungleMinionsKilled",
    "unrealKills", "visionClearedPings", "baitPings", "dangerPings", "basicPings", "playerAugment5",
    "playerAugment6", "retreatPings", "championSkinId", "damageDealtToEpicMonsters", "roleBoundItem",
]
_EXTRA_BOOL = [
    "eligibleForProgression", "causedGameEndFromIGNBSurrender", "gameEndedInIGNBSurrender", "teamIGNBSurrendered",
    "wasPremadeWithIGNBGameEndCauser", "wasPremadeWithSevereTransgressor", "wasSevereTransgressor",
]
# A representative subset of ChallengesDto (the real one has 147 keys, ints/floats and one array).
_CHALLENGES = {
    "12AssistStreakCount": 0, "abilityUses": 112, "acesBefore15Minutes": 0, "alliedJungleMonsterKills": 4.0,
    "baronTakedowns": 1, "blastConeOppositeOpponentCount": 0, "bountyGold": 300.0, "buffsStolen": 0,
    "controlWardTimeCoverageInRiverOrEnemyHalf": 0.31, "damagePerMinute": 812.5, "earliestBaron": 1480.2,
    "goldPerMinute": 402.7, "kda": 3.2, "killParticipation": 0.55, "laneMinionsFirst10Minutes": 71,
    "legendaryItemUsed": [3031, 6672], "visionScorePerMinute": 1.1,
}
_PERKS = {
    "statPerks": {"defense": 5001, "flex": 5008, "offense": 5005},
    "styles": [
        {"description": "primaryStyle", "style": 8000,
         "selections": [{"perk": 8010, "var1": 1, "var2": 2, "var3": 3}, {"perk": 9111, "var1": 4, "var2": 5, "var3": 6}]},
        {"description": "subStyle", "style": 8100,
         "selections": [{"perk": 8126, "var1": 7, "var2": 8, "var3": 9}]},
    ],
}


def _fake_hash(*parts, n: int = 78) -> str:
    h = hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()
    return (h + hashlib.sha256(h.encode()).hexdigest())[:n]


def _clean(v):
    """numpy -> JSON: integral floats become ints (like the real API), NaN is dropped by the caller."""
    if isinstance(v, float) and v == int(v):
        return int(v)
    return v


class MockRiot:
    """In-process mock. ``start()`` returns ``self``; ``url`` is the base URL; ``stop()`` shuts it down."""

    def __init__(self, key: str = DEFAULT_KEY, port: int = 0, n_players: int = 300, n_matches: int = 400,
                 overlap: int = 0, rate_limit_once: bool = False, sample: Path | None = None):
        self.key, self.port, self.overlap, self.rate_limit_once = key, port, overlap, rate_limit_once
        df = pd.read_parquet(sample or paths.SAMPLE / "performance.parquet")
        df = df[df.groupby("match_id")["match_id"].transform("size") == 10]
        ids = list(dict.fromkeys(df["match_id"]))[:n_matches]
        self.rows = {int(m): g.sort_values("participantId") for m, g in df[df["match_id"].isin(ids)].groupby("match_id")}
        self.match_order = [f"{PLATFORM_ID}_{m}" for m in self.rows]
        self.puuids = [_fake_hash("player", i) for i in range(n_players)]
        # league points deliberately NOT sorted, so clients must sort themselves
        self.points = {p: 1000 + (i * 7919) % 1500 for i, p in enumerate(self.puuids)}
        self.log: list[tuple[str, int]] = []  # (path, status)
        self.n_429 = 0
        self._lock = threading.Lock()
        self._limited = False
        self.httpd: ThreadingHTTPServer | None = None

    # --- data -------------------------------------------------------------------------------------------
    def ranked_players(self, n: int | None = None) -> list[str]:
        """puuids in the order a correct client picks them (best league points first)."""
        ordered = sorted(self.puuids, key=lambda p: self.points[p], reverse=True)
        return ordered[:n] if n else ordered

    def ids_for(self, puuid: str, count: int, start: int = 0) -> list[str]:
        if puuid not in self.points:
            return []
        rank = self.ranked_players().index(puuid)
        step = max(count - self.overlap, 1)
        first = rank * step  # consecutive players share `overlap` matches
        n = len(self.match_order)
        return [self.match_order[(first + start + k) % n] for k in range(count)]

    def league(self, tier: str) -> dict:
        offset = {"challenger": 0, "grandmaster": -300, "master": -600}[tier]
        entries = [{"puuid": p, "leaguePoints": self.points[p] + offset, "rank": "I", "wins": 100 + i % 50,
                    "losses": 90 + i % 40, "veteran": False, "inactive": False, "freshBlood": False,
                    "hotStreak": bool(i % 5 == 0)} for i, p in enumerate(self.puuids)]
        return {"tier": tier.upper(), "leagueId": _fake_hash("league", tier, n=36), "queue": "RANKED_SOLO_5x5",
                "name": "Mock League", "entries": entries}

    def match(self, match_id: str) -> dict | None:
        try:
            gid = int(match_id.split("_", 1)[1])
        except (IndexError, ValueError):
            return None
        g = self.rows.get(gid)
        if g is None or match_id.split("_")[0] != PLATFORM_ID:
            return None
        parts, puuids = [], []
        for _, r in g.iterrows():
            p = {k: _clean(v) for k, v in r.items() if k not in ("match_id", "duration", "calculated_player_performance")
                 and not (isinstance(v, float) and math.isnan(v))}
            for k in ("championName", "individualPosition", "lane", "role", "teamPosition"):
                p[k] = r[k] if isinstance(r[k], str) else ""  # the live API sends "" where the CSV has NaN
            p["win"] = bool(r["win"])
            for k in ("firstBloodAssist", "firstBloodKill", "firstTowerAssist", "firstTowerKill",
                      "gameEndedInEarlySurrender", "gameEndedInSurrender", "teamEarlySurrendered"):
                if k in p:
                    p[k] = bool(p[k])
            pu = _fake_hash("participant", gid, int(r["participantId"]))
            puuids.append(pu)
            p.update({k: 0 for k in _EXTRA_INT})
            p.update({k: False for k in _EXTRA_BOOL})
            p.update(puuid=pu, summonerId=_fake_hash("sid", gid, int(r["participantId"]), n=47),
                     summonerName="", riotIdName="", riotIdGameName=f"Mock{int(r['participantId'])}", riotIdTagline="EUW",
                     summonerLevel=250, profileIcon=29, positionAssignedByMatchmaking="", selectedRolePreferences="",
                     challenges=dict(_CHALLENGES), perks=json.loads(json.dumps(_PERKS)),
                     missions={f"playerScore{i}": 0 for i in range(12)},
                     PlayerBehavior={"PlayerBehavior_IsHeroInCombat": 0})
            p.update({f"playerScore{i}": 0.0 for i in range(12)})
            parts.append(p)
        dur = int(g["timePlayed"].max())
        start = 1_760_000_000_000 + (gid % 100_000) * 60_000
        return {
            "metadata": {"dataVersion": "2", "matchId": match_id, "participants": puuids},
            "info": {
                "endOfGameResult": "GameComplete", "gameCreation": start - 40_000, "gameDuration": dur,
                "gameEndTimestamp": start + dur * 1000, "gameId": gid, "gameMode": "CLASSIC",
                "gameName": f"teambuilder-match-{gid}", "gameStartTimestamp": start, "gameType": "MATCHED_GAME",
                "gameVersion": GAME_VERSION, "mapId": 11, "participants": parts, "platformId": PLATFORM_ID,
                "queueId": 420, "tournamentCode": "",
                "teams": [{"teamId": t, "win": bool(g[g["teamId"] == t]["win"].iloc[0]), "bans": [],
                           "objectives": {}} for t in (100, 200)],
            },
        }

    # --- http -------------------------------------------------------------------------------------------
    def _route(self, path: str, query: dict) -> tuple[int, dict | list | None, dict]:
        if path == "/lol/status/v4/platform-data":
            return 200, {"id": PLATFORM_ID, "name": "Mock EUW", "locales": ["en_GB"], "maintenances": [], "incidents": []}, {}
        parts = path.strip("/").split("/")
        if len(parts) == 6 and parts[:3] == ["lol", "league", "v4"] and parts[4] == "by-queue":
            tier = parts[3].removesuffix("leagues")
            if tier in ("challenger", "grandmaster", "master") and parts[5] == "RANKED_SOLO_5x5":
                return 200, self.league(tier), {}
        if len(parts) == 7 and parts[:4] == ["lol", "match", "v5", "matches"] and parts[4] == "by-puuid" and parts[6] == "ids":
            count = int(query.get("count", ["20"])[0])
            if not 0 < count <= 100 or query.get("queue", ["420"])[0] != "420":
                return 400, {"status": {"message": "Bad Request - bad count/queue", "status_code": 400}}, {}
            return 200, self.ids_for(parts[5], count, int(query.get("start", ["0"])[0])), {}
        if len(parts) == 5 and parts[:4] == ["lol", "match", "v5", "matches"]:
            with self._lock:
                if self.rate_limit_once and not self._limited:
                    self._limited = True
                    self.n_429 += 1
                    return 429, {"status": {"message": "Rate limit exceeded", "status_code": 429}}, {"Retry-After": "1"}
            m = self.match(parts[4])
            if m is not None:
                return 200, m, {}
        return 404, {"status": {"message": "Data not found", "status_code": 404}}, {}

    def start(self) -> "MockRiot":
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                u = urlparse(self.path)
                tok = self.headers.get("X-Riot-Token")
                if not tok:
                    status, body, hdr = 401, {"status": {"message": "Unauthorized", "status_code": 401}}, {}
                elif tok != outer.key:
                    status, body, hdr = 403, {"status": {"message": "Forbidden", "status_code": 403}}, {}
                else:
                    status, body, hdr = outer._route(u.path, parse_qs(u.query))
                with outer._lock:
                    outer.log.append((u.path, status))
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                for k, v in hdr.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), H)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--key", default=DEFAULT_KEY, help=f"token the server accepts (default {DEFAULT_KEY})")
    ap.add_argument("--matches", type=int, default=400, help="size of the match pool (max = matches in the sample)")
    ap.add_argument("--overlap", type=int, default=0, help="matches shared by consecutive players (tests de-duplication)")
    ap.add_argument("--rate-limit-once", action="store_true", help="answer the first match request with 429 + Retry-After")
    a = ap.parse_args()
    srv = MockRiot(a.key, a.port, n_matches=a.matches, overlap=a.overlap, rate_limit_once=a.rate_limit_once).start()
    print(f"MOCK Riot API on {srv.url}  (accepts X-Riot-Token: {a.key}; {len(srv.match_order)} matches; Ctrl+C to stop)")
    print(f"  RIOT_BASE_URL={srv.url} RIOT_API_KEY={a.key} python scripts/extract_live.py")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.stop()


if __name__ == "__main__":
    main()
