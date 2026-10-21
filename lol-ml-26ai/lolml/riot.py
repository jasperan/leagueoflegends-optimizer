"""Optional: extract your own matches with the Riot Games API (puuid-based, match-v5).

Riot removed SummonerIDs and AccountIDs from API payloads on 2025-07-07. Everything below keys on the
``puuid`` that league-v4 and match-v5 return today. Nothing here is needed for the core workshop path.

Quick reference (see https://developer.riotgames.com/apis):
  league-v4  GET /lol/league/v4/{challenger,grandmaster,master}leagues/by-queue/RANKED_SOLO_5x5   (platform host)
  match-v5   GET /lol/match/v5/matches/by-puuid/{puuid}/ids                                        (regional host)
  match-v5   GET /lol/match/v5/matches/{matchId}                                                   (regional host)

Auth is the ``X-Riot-Token`` header. Development keys expire after 24 hours and allow 20 requests/second and
100 requests/2 minutes; ``RiotClient`` stays under both and honours ``Retry-After`` on HTTP 429.
Set ``RIOT_BASE_URL`` (e.g. ``http://127.0.0.1:8765``) to send every call to a local mock instead of Riot
(see ``scripts/mock_riot.py``).

``InfoDto.gameDuration`` is in seconds for every match played after patch 11.20 (milliseconds before that, which
is detected by the absence of ``gameEndTimestamp``). ``queueId`` 420 is Ranked Solo/Duo.
"""
from __future__ import annotations

import os
import sqlite3
import time
from collections import deque
from pathlib import Path

import requests

PLATFORM_TO_REGION = {
    "na1": "americas", "br1": "americas", "la1": "americas", "la2": "americas",
    "euw1": "europe", "eun1": "europe", "tr1": "europe", "ru": "europe", "me1": "europe",
    "kr": "asia", "jp1": "asia",
    "oc1": "sea", "ph2": "sea", "sg2": "sea", "th2": "sea", "tw2": "sea", "vn2": "sea",
}

# ParticipantDto fields we keep: the post-game columns of the workshop dataset. The current schema has 159
# fields (some are dictionaries); an explicit list means a new Riot field can never break an insert.
PERFORMANCE_FIELDS = [
    "assists", "baronKills", "bountyLevel", "champExperience", "champLevel", "championId", "championName",
    "championTransform", "consumablesPurchased", "damageDealtToBuildings", "damageDealtToObjectives",
    "damageDealtToTurrets", "damageSelfMitigated", "deaths", "detectorWardsPlaced", "doubleKills", "dragonKills",
    "firstBloodAssist", "firstBloodKill", "firstTowerAssist", "firstTowerKill", "gameEndedInEarlySurrender",
    "gameEndedInSurrender", "goldEarned", "goldSpent", "individualPosition", "inhibitorKills",
    "inhibitorTakedowns", "inhibitorsLost", "item0", "item1", "item2", "item3", "item4", "item5", "item6",
    "itemsPurchased", "killingSprees", "kills", "lane", "largestCriticalStrike", "largestKillingSpree",
    "largestMultiKill", "longestTimeSpentLiving", "magicDamageDealt", "magicDamageDealtToChampions",
    "magicDamageTaken", "neutralMinionsKilled", "nexusKills", "nexusLost", "nexusTakedowns", "objectivesStolen",
    "objectivesStolenAssists", "participantId", "pentaKills", "physicalDamageDealt",
    "physicalDamageDealtToChampions", "physicalDamageTaken", "quadraKills", "role", "spell1Casts", "spell2Casts",
    "spell3Casts", "spell4Casts", "summoner1Casts", "summoner1Id", "summoner2Casts", "summoner2Id",
    "teamEarlySurrendered", "teamId", "teamPosition", "timeCCingOthers", "timePlayed", "totalDamageDealt",
    "totalDamageDealtToChampions", "totalDamageShieldedOnTeammates", "totalDamageTaken", "totalHeal",
    "totalHealsOnTeammates", "totalMinionsKilled", "totalTimeCCDealt", "totalTimeSpentDead", "totalUnitsHealed",
    "tripleKills", "trueDamageDealt", "trueDamageDealtToChampions", "trueDamageTaken", "turretKills",
    "turretTakedowns", "turretsLost", "visionScore", "visionWardsBoughtInGame", "wardsKilled", "wardsPlaced",
    "win",
]
TEXT_FIELDS = {"championName", "individualPosition", "lane", "role", "teamPosition"}


class RiotAuthError(RuntimeError):
    """The API key was rejected (401/403). Retrying will not help."""


class RiotRateLimitError(RuntimeError):
    """Still HTTP 429 after every back-off attempt."""


RANKED_SOLO = 420


class RiotClient:
    """Minimal Riot API client: header auth, development-key rate limits, 429/5xx back-off, clear auth errors.

    ``retry_pad`` seconds are added to every ``Retry-After`` (Riot's counter is not exact to the millisecond).
    """

    def __init__(self, api_key: str, platform: str = "euw1", base_url: str | None = None,
                 per_second: int = 20, per_two_minutes: int = 100, retry_pad: float = 1.0, max_retries: int = 6):
        if platform not in PLATFORM_TO_REGION:
            raise ValueError(f"unknown platform {platform!r}; choose one of {sorted(PLATFORM_TO_REGION)}")
        if not api_key:
            raise RiotAuthError("no API key: set the RIOT_API_KEY environment variable "
                                "(https://developer.riotgames.com, development keys last 24 hours).")
        self.platform, self.region = platform, PLATFORM_TO_REGION[platform]
        self.base_url = base_url or os.environ.get("RIOT_BASE_URL")
        self.retry_pad, self.max_retries = retry_pad, max_retries
        self.s = requests.Session()
        self.s.headers["X-Riot-Token"] = api_key
        self.limits = [(per_second, 1.0), (per_two_minutes, 120.0)]
        self.stamps: deque[float] = deque(maxlen=max(n for n, _ in self.limits))
        self.calls = 0
        self.rate_limited = 0  # number of HTTP 429 responses seen

    def _host(self, regional: bool) -> str:
        if self.base_url:
            return self.base_url.rstrip("/")
        return f"https://{self.region if regional else self.platform}.api.riotgames.com"

    def _wait(self) -> None:
        now = time.monotonic()
        for n, window in self.limits:
            if len(self.stamps) >= n and now - self.stamps[-n] < window:
                time.sleep(window - (now - self.stamps[-n]) + 0.05)
                now = time.monotonic()
        self.stamps.append(time.monotonic())

    def get(self, path: str, regional: bool = False, params: dict | None = None):
        """GET and decode JSON. 404 -> None. 401/403 -> RiotAuthError. 429/5xx are retried, then raised."""
        url = self._host(regional) + path
        last = ""
        for attempt in range(self.max_retries):
            self._wait()
            self.calls += 1
            r = self.s.get(url, params=params, timeout=30)
            if r.status_code == 429:
                self.rate_limited += 1
                try:
                    delay = float(r.headers.get("Retry-After", "5"))
                except ValueError:
                    delay = 5.0
                last = f"HTTP 429 (Retry-After {delay:g}s)"
                time.sleep(delay + self.retry_pad)
                continue
            if r.status_code >= 500:
                last = f"HTTP {r.status_code}"
                time.sleep(min(2.0 ** attempt, 30.0))
                continue
            if r.status_code == 401:
                raise RiotAuthError(f"HTTP 401 from {path}: the X-Riot-Token header is missing or empty.")
            if r.status_code == 403:
                raise RiotAuthError(f"HTTP 403 from {path}: the key is invalid, expired (development keys last 24 "
                                    "hours; regenerate it on developer.riotgames.com) or not allowed for this API.")
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        raise RiotRateLimitError(f"giving up on {path} after {self.max_retries} attempts; last answer: {last}")

    # --- endpoints -------------------------------------------------------------------------------------
    def status(self) -> dict | None:
        """lol-status-v4 platform data: the cheapest call that needs a valid key (one request)."""
        return self.get("/lol/status/v4/platform-data")

    def check(self) -> tuple[bool, str]:
        """One request, no retries: ``(True, 'ok')`` or ``(False, precise reason)``. Never raises, never shows the key."""
        url = self._host(False) + "/lol/status/v4/platform-data"
        try:
            r = self.s.get(url, timeout=15)
        except requests.RequestException as e:
            return False, f"cannot reach {self._host(False)}: {type(e).__name__}"
        if r.status_code == 200:
            return True, "ok"
        reasons = {
            401: "HTTP 401: no X-Riot-Token was sent (RIOT_API_KEY is empty)",
            403: "HTTP 403: key rejected - invalid or EXPIRED (development keys last 24 hours; regenerate at "
                 "https://developer.riotgames.com) or not allowed for lol-status-v4",
            429: f"HTTP 429: rate limited, retry in {r.headers.get('Retry-After', '?')} s",
        }
        return False, reasons.get(r.status_code, f"HTTP {r.status_code} from lol-status-v4")

    def apex_players(self, tier: str = "challenger", queue: str = "RANKED_SOLO_5x5") -> list[dict]:
        """league-v4 apex entries (LeagueItemDTO + the list's tier), best league points first. Entries carry ``puuid``."""
        if tier not in ("challenger", "grandmaster", "master"):
            raise ValueError("tier must be challenger, grandmaster or master")
        data = self.get(f"/lol/league/v4/{tier}leagues/by-queue/{queue}") or {}
        entries = [dict(e, tier=data.get("tier", tier.upper())) for e in data.get("entries", []) if e.get("puuid")]
        return sorted(entries, key=lambda e: e.get("leaguePoints", 0), reverse=True)

    def match_ids(self, puuid: str, count: int = 20, queue: int = RANKED_SOLO) -> list[str]:
        if not 1 <= count <= 100:
            raise ValueError("match-v5 returns 1-100 ids per call")
        return self.get(f"/lol/match/v5/matches/by-puuid/{puuid}/ids", regional=True,
                        params={"queue": queue, "start": 0, "count": count}) or []

    def match(self, match_id: str) -> dict | None:
        return self.get(f"/lol/match/v5/matches/{match_id}", regional=True)


# --- flattening and storage ----------------------------------------------------------------------------
def flatten_match(m: dict) -> list[dict]:
    """One dict per participant, restricted to PERFORMANCE_FIELDS (+ ids). Dict-valued API fields are ignored."""
    info = m["info"]
    duration_s = info.get("gameDuration", 0)
    if info.get("gameEndTimestamp") is None:  # games before patch 11.20 report milliseconds
        duration_s /= 1000
    mid = m["metadata"]["matchId"]
    rows = []
    for p in info["participants"]:
        row = {"match_id": mid, "puuid": p.get("puuid"), "game_version": info.get("gameVersion"),
               "duration": duration_s / 60.0}
        for f in PERFORMANCE_FIELDS:
            v = p.get(f)
            row[f] = (v if v is None else str(v)) if f in TEXT_FIELDS else (None if v is None else float(v))
        rows.append(row)
    return rows


SCHEMA = [
    "CREATE TABLE IF NOT EXISTS players (puuid TEXT PRIMARY KEY, tier TEXT, rank TEXT, league_points INTEGER,"
    " wins INTEGER, losses INTEGER, platform TEXT)",
    "CREATE TABLE IF NOT EXISTS matches (match_id TEXT PRIMARY KEY, fetched INTEGER DEFAULT 0)",
    "CREATE TABLE IF NOT EXISTS performance (match_id TEXT, puuid TEXT, game_version TEXT, duration REAL, "
    + ", ".join(f"{f} {'TEXT' if f in TEXT_FIELDS else 'REAL'}" for f in PERFORMANCE_FIELDS)
    + ", PRIMARY KEY (match_id, participantId))",
]


def open_db(path: str | Path = "riot_extract.db") -> sqlite3.Connection:
    con = sqlite3.connect(path)
    for stmt in SCHEMA:
        con.execute(stmt)
    return con


def insert_rows(con: sqlite3.Connection, table: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    cols = list(rows[0])
    cur = con.executemany(
        f"INSERT OR IGNORE INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        [tuple(r[c] for c in cols) for r in rows])
    return cur.rowcount


def extract(client: RiotClient, con: sqlite3.Connection, players: int = 5, matches_per_player: int = 10,
            tier: str = "challenger", log=print) -> dict:
    """player list -> match ids -> match details -> performance rows. Failures raise; nothing is swallowed.

    Resumable: ids stored in ``matches`` with ``fetched = 0`` (an interrupted earlier run) are fetched too.
    Returns counts; ``rows`` is the number of NEW performance rows written.
    """
    entries = client.apex_players(tier)[:players]
    insert_rows(con, "players", [dict(puuid=e["puuid"], tier=e["tier"], rank=e.get("rank"),
                                      league_points=e.get("leaguePoints"), wins=e.get("wins"),
                                      losses=e.get("losses"), platform=client.platform) for e in entries])
    log(f"{len(entries)} {tier} players")
    known = {r[0] for r in con.execute("SELECT match_id FROM matches")}
    new_ids: list[str] = []
    for e in entries:
        for mid in client.match_ids(e["puuid"], matches_per_player):
            if mid not in known:
                known.add(mid)
                new_ids.append(mid)
    insert_rows(con, "matches", [{"match_id": m} for m in new_ids])
    con.commit()
    todo = [r[0] for r in con.execute("SELECT match_id FROM matches WHERE fetched = 0 ORDER BY rowid")]
    log(f"{len(new_ids)} new match ids ({len(todo)} to download)")
    n_rows = n_skipped = 0
    for i, mid in enumerate(todo, 1):
        m = client.match(mid)
        if m is None:
            log(f"[skip] {mid}: 404")
            n_skipped += 1
            continue
        if m["info"].get("queueId") != RANKED_SOLO:
            log(f"[skip] {mid}: queueId {m['info'].get('queueId')}")
            n_skipped += 1
        else:
            n_rows += insert_rows(con, "performance", flatten_match(m))
        con.execute("UPDATE matches SET fetched = 1 WHERE match_id = ?", (mid,))
        con.commit()
        if i % 10 == 0 or i == len(todo):
            log(f"  {i}/{len(todo)} matches, {n_rows} performance rows")
    return {"players": len(entries), "matches": len(todo) - n_skipped, "skipped": n_skipped, "rows": n_rows,
            "api_calls": client.calls, "rate_limited": client.rate_limited}
