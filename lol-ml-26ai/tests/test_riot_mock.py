"""Tests for the optional live-extraction path, run against scripts/mock_riot.py (a MOCK; no Riot key needed).

    python tests/test_riot_mock.py        # plain script
    python -m pytest tests/test_riot_mock.py   # if pytest is installed
"""
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
os.environ.pop("RIOT_BASE_URL", None)

import export_extract  # noqa: E402
import mock_riot  # noqa: E402
from lolml import paths, riot  # noqa: E402

KEY = "RGAPI-TEST-KEY"
PLAYERS, MATCHES, OVERLAP = 3, 4, 1  # consecutive players share 1 match -> 3*4 - 2 = 10 unique matches
UNIQUE = (PLAYERS - 1) * (MATCHES - OVERLAP) + MATCHES


def _client(srv, key=KEY, **kw):
    kw.setdefault("retry_pad", 0.1)
    return riot.RiotClient(key, "euw1", base_url=srv.url, **kw)


def _run(script, srv, key, *args):
    env = dict(os.environ, RIOT_BASE_URL=srv.url)
    env.pop("RIOT_API_KEY", None)
    if key is not None:
        env["RIOT_API_KEY"] = key
    return subprocess.run([sys.executable, str(ROOT / "scripts" / script), *args], env=env, capture_output=True, text=True)


def test_extract_inserts_ten_rows_per_match_and_dedupes():
    srv = mock_riot.MockRiot(KEY, overlap=OVERLAP).start()
    try:
        con = riot.open_db(":memory:")
        res = riot.extract(_client(srv), con, PLAYERS, MATCHES, log=lambda *_: None)
        assert res["matches"] == UNIQUE, res
        assert res["rows"] == UNIQUE * 10, res
        assert con.execute("SELECT COUNT(*) FROM performance").fetchone()[0] == UNIQUE * 10
        assert con.execute("SELECT COUNT(DISTINCT puuid) FROM performance").fetchone()[0] == UNIQUE * 10
        # the players picked are the best by league points, not the first in the list
        got = {r[0] for r in con.execute("SELECT puuid FROM players")}
        assert got == set(srv.ranked_players(PLAYERS)), "top players by leaguePoints expected"
        # re-running downloads nothing new
        again = riot.extract(_client(srv), con, PLAYERS, MATCHES, log=lambda *_: None)
        assert again["rows"] == 0 and again["matches"] == 0, again
        # paths hit: only the documented puuid-based endpoints
        paths_hit = {"/".join(p.split("/")[1:4]) for p, _ in srv.log}
        assert paths_hit == {"lol/league/v4", "lol/match/v5"}, paths_hit
        assert all("by-puuid" in p or "leagues/by-queue" in p or "/matches/EUW1_" in p for p, _ in srv.log)
    finally:
        srv.stop()


def test_participant_has_159_fields_with_dicts_and_flatten_is_exact():
    srv = mock_riot.MockRiot(KEY).start()
    try:
        c = _client(srv)
        # matches from old patches lack a few fields (as in the real data); recent ones carry all 159
        full = next(m for m in srv.match_order if len(srv.match(m)["info"]["participants"][0]) == 159)
        m = c.match(full)
        p = m["info"]["participants"][0]
        assert len(p) == 159, len(p)
        assert all(isinstance(p[k], dict) for k in ("challenges", "missions", "perks", "PlayerBehavior"))
        rows = riot.flatten_match(m)
        assert len(rows) == 10 and all(r["puuid"] for r in rows)
        src = srv.rows[int(full.split("_")[1])]
        assert abs(rows[0]["duration"] - src["timePlayed"].max() / 60) < 1e-9  # seconds -> minutes
        assert rows[0]["kills"] == src.iloc[0]["kills"] and rows[0]["win"] in (0.0, 1.0)
    finally:
        srv.stop()


def test_export_schema_equals_dataset_schema_and_values_roundtrip():
    srv = mock_riot.MockRiot(KEY, overlap=OVERLAP).start()
    try:
        with tempfile.TemporaryDirectory() as d:
            dbp, out = str(Path(d) / "x.db"), Path(d) / "my_matches.parquet"
            r = _run("extract_live.py", srv, KEY, "--players", str(PLAYERS), "--matches", str(MATCHES), "--db", dbp)
            assert r.returncode == 0, r.stdout + r.stderr
            df = export_extract.export(dbp, out)
            ref = pd.read_parquet(paths.SAMPLE / "performance.parquet")
            assert list(df.columns) == list(ref.columns)
            assert df.dtypes.to_dict() == ref.dtypes.to_dict()
            assert "puuid" not in df.columns and len(df) == UNIQUE * 10 and df["match_id"].nunique() == UNIQUE
            back = pd.read_parquet(out)
            assert list(back.columns) == list(ref.columns) and back.dtypes.to_dict() == ref.dtypes.to_dict()
            # the mock serves real sample rows, so every stat must survive extract -> SQLite -> export unchanged
            both = df.merge(ref, on=["match_id", "participantId"], suffixes=("", "_ref"))
            assert len(both) == len(df)
            for c in ref.columns:
                if c in ("match_id", "participantId", "duration", "calculated_player_performance"):
                    continue
                a, b = both[c], both[c + "_ref"]
                same = (a == b) | (a.isna() & b.isna())
                assert same.all(), f"column {c} differs after round trip"
            assert (both["duration"] - both["duration_ref"]).abs().max() < 1e-9
            cp = both["calculated_player_performance"] - both["calculated_player_performance_ref"]
            assert cp.abs().median() < 0.05, cp.abs().median()
    finally:
        srv.stop()


def test_wrong_or_missing_key_is_an_auth_error_and_nonzero_exit():
    srv = mock_riot.MockRiot(KEY).start()
    try:
        for bad, code in (("RGAPI-WRONG", 403),):
            try:
                _client(srv, bad).apex_players()
                raise AssertionError("expected RiotAuthError")
            except riot.RiotAuthError as e:
                assert str(code) in str(e) and "RGAPI-WRONG" not in str(e)
        c = _client(srv)
        c.s.headers.pop("X-Riot-Token")
        try:
            c.apex_players()
            raise AssertionError("expected RiotAuthError")
        except riot.RiotAuthError as e:
            assert "401" in str(e)
        with tempfile.TemporaryDirectory() as d:
            r = _run("extract_live.py", srv, "RGAPI-WRONG", "--db", str(Path(d) / "x.db"))
            assert r.returncode != 0 and "FAIL (auth)" in r.stdout and "RGAPI-WRONG" not in r.stdout + r.stderr, r.stdout
            assert not sqlite3.connect(str(Path(d) / "x.db")).execute("SELECT COUNT(*) FROM performance").fetchone()[0]
            r = _run("extract_live.py", srv, None, "--db", str(Path(d) / "y.db"))
            assert r.returncode != 0 and "RIOT_API_KEY is not set" in r.stdout
        # check_riot.py
        r = _run("check_riot.py", srv, KEY)
        assert r.returncode == 0 and r.stdout.startswith("PASS"), r.stdout
        r = _run("check_riot.py", srv, "RGAPI-WRONG")
        assert r.returncode != 0 and "403" in r.stdout and "EXPIRED" in r.stdout and "RGAPI-WRONG" not in r.stdout
        r = _run("check_riot.py", srv, None)
        assert r.returncode != 0 and "not set" in r.stdout
    finally:
        srv.stop()
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_riot.py")], capture_output=True, text=True,
                       env=dict(os.environ, RIOT_API_KEY="x", RIOT_BASE_URL="http://127.0.0.1:1"))
    assert r.returncode != 0 and r.stdout.startswith("FAIL: cannot reach"), r.stdout  # nothing listening


def test_429_with_retry_after_is_waited_out_and_succeeds():
    srv = mock_riot.MockRiot(KEY, overlap=OVERLAP, rate_limit_once=True).start()
    try:
        con = riot.open_db(":memory:")
        c = _client(srv)
        t0 = time.monotonic()
        res = riot.extract(c, con, 2, 3, log=lambda *_: None)
        waited = time.monotonic() - t0
        assert srv.n_429 == 1 and c.rate_limited == 1
        assert waited >= 1.0, f"Retry-After: 1 must be honoured, only waited {waited:.2f}s"
        assert res["rows"] == res["matches"] * 10 and res["matches"] > 0
        assert [s for p, s in srv.log if s == 429] == [429]
    finally:
        srv.stop()


def test_gives_up_with_rate_limit_error_when_429_never_stops():
    srv = mock_riot.MockRiot(KEY).start()
    try:
        srv.rate_limit_once = True
        orig = srv._route

        def always_429(path, query):
            return (429, {}, {"Retry-After": "0"}) if "/matches/EUW1_" in path else orig(path, query)
        srv._route = always_429
        try:
            _client(srv, max_retries=3, retry_pad=0.0).match(srv.match_order[0])
            raise AssertionError("expected RiotRateLimitError")
        except riot.RiotRateLimitError as e:
            assert "3 attempts" in str(e)
    finally:
        srv.stop()


def test_interrupted_run_is_resumed():
    srv = mock_riot.MockRiot(KEY).start()
    try:
        con = riot.open_db(":memory:")
        ids = srv.ids_for(srv.ranked_players(1)[0], 3)
        riot.insert_rows(con, "matches", [{"match_id": m} for m in ids])  # ids known, nothing downloaded yet
        res = riot.extract(_client(srv), con, 1, 3, log=lambda *_: None)
        assert res["rows"] == 30, res
    finally:
        srv.stop()


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        t0 = time.monotonic()
        try:
            fn()
            print(f"PASS {name} ({time.monotonic() - t0:.1f}s)")
        except Exception as e:  # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e!r}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
