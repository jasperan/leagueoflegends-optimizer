"""Oracle AI Database 26ai helpers: connect (thin mode), run the numbered SQL scripts, shared column maps.

Works with the Oracle AI Database 26ai Free container *and* an Autonomous AI Database. Only python-oracledb in
THIN mode is used, so no Oracle Client / Instant Client install is needed.

Environment variables
---------------------
LOLML_DB_USER, LOLML_DB_PASSWORD, LOLML_DB_DSN
    The application user (``LOLML``). The DSN is either
    * ``host:port/service`` for the container (``localhost:1521/FREEPDB1``), or
    * the full TLS connect string from the Autonomous console (Database connection > TLS authentication), or
    * a tnsnames.ora alias such as ``lolml26ai_high`` together with the wallet variables below (mTLS).
LOLML_DB_WALLET_DIR, LOLML_DB_WALLET_PASSWORD
    Optional. Unzipped Autonomous wallet directory (mTLS) and the password you chose when downloading it.
LOLML_ADMIN_USER, LOLML_ADMIN_PASSWORD, LOLML_ADMIN_DSN
    Only for ``scripts/db_setup.py`` (creates the LOLML user). Default user ``ADMIN``; the DSN defaults to
    ``LOLML_DB_DSN``. On the container use ``SYSTEM`` and the ORACLE_PASSWORD you started it with.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from . import paths

SQL_DIR = paths.ROOT / "sql"

REQUIRED = ("LOLML_DB_USER", "LOLML_DB_PASSWORD", "LOLML_DB_DSN")
ADMIN_REQUIRED = ("LOLML_ADMIN_PASSWORD",)


class DbConfigError(RuntimeError):
    """The environment is not set up for a database connection."""


def _oracledb():
    try:
        import oracledb
    except ImportError as e:  # pragma: no cover
        raise DbConfigError("python-oracledb is not installed. Run: pip install oracledb") from e
    return oracledb


def _require(names: tuple[str, ...], hint: str) -> dict[str, str]:
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        raise DbConfigError(
            f"Missing environment variable(s): {', '.join(missing)}.\n{hint}")
    return {n: os.environ[n] for n in names}


_HINT = (
    "Set them before running, for example (Oracle AI Database 26ai Free container):\n"
    "  export LOLML_DB_USER=LOLML\n"
    "  export LOLML_DB_PASSWORD='<the password you chose in db_setup>'\n"
    "  export LOLML_DB_DSN=localhost:1521/FREEPDB1\n"
    "For an Autonomous AI Database paste the connect string from the console (and, for mTLS, also set\n"
    "LOLML_DB_WALLET_DIR and LOLML_DB_WALLET_PASSWORD). See docker/README.md and the workshop guide."
)


def connect(admin: bool = False, **extra):
    """Open a thin-mode connection. ``admin=True`` uses the LOLML_ADMIN_* variables (user creation only)."""
    oracledb = _oracledb()
    oracledb.defaults.fetch_lobs = False  # CLOB -> str, BLOB -> bytes (for example DBMS_CLOUD_AI.GENERATE returns a CLOB)
    if admin:
        _require(ADMIN_REQUIRED, "Set LOLML_ADMIN_PASSWORD (and LOLML_ADMIN_USER, default ADMIN; "
                 "use SYSTEM on the container) to run db_setup.py.")
        user = os.environ.get("LOLML_ADMIN_USER", "ADMIN")
        password = os.environ["LOLML_ADMIN_PASSWORD"]
        dsn = os.environ.get("LOLML_ADMIN_DSN") or _require(("LOLML_DB_DSN",), _HINT)["LOLML_DB_DSN"]
    else:
        cfg = _require(REQUIRED, _HINT)
        user, password, dsn = cfg["LOLML_DB_USER"], cfg["LOLML_DB_PASSWORD"], cfg["LOLML_DB_DSN"]

    kwargs = dict(user=user, password=password, dsn=dsn)
    wallet = os.environ.get("LOLML_DB_WALLET_DIR")
    if wallet:
        if not Path(wallet).is_dir():
            raise DbConfigError(f"LOLML_DB_WALLET_DIR={wallet} is not a directory (unzip the wallet first).")
        # config_dir finds tnsnames.ora (service aliases); wallet_location finds ewallet.pem (mTLS certificate).
        kwargs.update(config_dir=wallet, wallet_location=wallet)
        if os.environ.get("LOLML_DB_WALLET_PASSWORD"):
            kwargs["wallet_password"] = os.environ["LOLML_DB_WALLET_PASSWORD"]
    kwargs.update(extra)
    try:
        return oracledb.connect(**kwargs)
    except oracledb.Error as e:
        raise DbConfigError(f"Could not connect as {user} to {dsn.split('?')[0][:80]}: {e}") from e


def banner(conn) -> str:
    with conn.cursor() as cur:
        cur.execute("select banner_full from v$version")
        return cur.fetchone()[0].replace("\n", " ")


def query_df(conn, sql: str, params: dict | list | None = None):
    """Run a SELECT and return a pandas DataFrame with lower-case column names."""
    import pandas as pd
    with conn.cursor() as cur:
        cur.execute(sql, params or {})
        cols = [d[0].lower() for d in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=cols)


# ---------------------------------------------------------------------------------------------------------------
# Tiny script runner so the same .sql files work from Python, SQLcl, SQL*Plus and the Autonomous SQL worksheet.
# Convention: plain SQL ends with ';', PL/SQL blocks (BEGIN/DECLARE/CREATE ... PROCEDURE) end with a line '/'.
# ---------------------------------------------------------------------------------------------------------------
_PLSQL_START = re.compile(r"^\s*(begin|declare|create\s+(or\s+replace\s+)?(editionable\s+|noneditionable\s+)?"
                          r"(procedure|function|package|type|trigger))\b", re.I)
_SQLPLUS_CMD = re.compile(r"^\s*(set|prompt|define|whenever|exit|spool|column|timing|show|accept|undefine)\b", re.I)


def _strip_trailing_comment(line: str) -> str:
    """'DROP TABLE t;  -- why' -> 'DROP TABLE t;'. A '--' inside a string literal is left alone."""
    i = line.find("--")
    while i != -1:
        if line[:i].count("'") % 2 == 0:
            return line[:i].rstrip()
        i = line.find("--", i + 2)
    return line.rstrip()


def split_script(text: str) -> list[str]:
    """Split a SQL*Plus-style script into executable statements (comments kept inside PL/SQL, dropped outside)."""
    stmts, buf, in_plsql, in_block_comment = [], [], False, False
    for line in text.splitlines():
        s = line.strip()
        if in_block_comment:
            in_block_comment = "*/" not in s
            continue
        if not buf:
            if not s or s.startswith("--") or s.lower().startswith("rem "):
                continue
            if s.startswith("/*") and "*/" not in s:
                in_block_comment = True
                continue
            if _SQLPLUS_CMD.match(line):
                continue
            in_plsql = bool(_PLSQL_START.match(line))
        if s == "/":
            if buf:
                stmts.append("\n".join(buf).strip())
            buf, in_plsql = [], False
            continue
        buf.append(line)
        code = _strip_trailing_comment(s)
        if not in_plsql and code.endswith(";") and not s.startswith("--"):
            stmts.append("\n".join(buf[:-1] + [_strip_trailing_comment(line).rstrip()]).strip().rstrip(";"))
            buf = []
    if "\n".join(buf).strip():
        stmts.append("\n".join(buf).strip().rstrip(";"))
    return stmts


def substitute(text: str, defines: dict[str, str]) -> str:
    """Replace SQL*Plus style &NAME / &&NAME substitution variables; error if one is not defined."""
    defs = {k.upper(): v for k, v in defines.items()}

    def repl(m):
        name = m.group(2).upper()
        env_key = name if name.startswith("LOLML_") else f"LOLML_{name}"
        if name in defs:
            return defs[name]
        if os.environ.get(env_key):
            return os.environ[env_key]
        raise DbConfigError(f"SQL script needs a value for &{name}. Pass --define {name}=value "
                            f"(or set the environment variable {env_key}).")
    return re.sub(r"&(&?)([A-Za-z_][A-Za-z0-9_]*)\.?", repl, text)


def run_script(conn, path: str | Path, defines: dict[str, str] | None = None, echo: bool = False) -> list[str]:
    """Execute a script. Returns the lines printed with DBMS_OUTPUT plus the rows of any SELECT (first 20).

    Stops at the first error and names the failing statement (scripts are written to be re-runnable)."""
    oracledb = _oracledb()
    path = Path(path)
    if not path.is_absolute() and not path.exists():
        path = SQL_DIR / path
    out: list[str] = []
    with conn.cursor() as cur:
        cur.callproc("dbms_output.enable", [1_000_000])
        # Split first, substitute per statement: error messages and echo show the text WITHOUT passwords or API keys.
        for raw in split_script(path.read_text()):
            stmt = substitute(raw, defines or {}) if "&" in raw else raw
            head = " ".join(raw.split())[:110]
            if echo:
                print(f"  > {head}")
            try:
                cur.execute(stmt)
                if cur.description:
                    rows = cur.fetchmany(20)
                    out.append(" | ".join(d[0] for d in cur.description))
                    out.extend(" | ".join("" if v is None else str(v) for v in r) for r in rows)
            except oracledb.Error as e:
                raise DbConfigError(f"{path.name}: statement failed: {head}\n  {e}") from e
            out.extend(_drain_output(conn))
    conn.commit()
    return out


def _drain_output(conn) -> list[str]:
    lines: list[str] = []
    with conn.cursor() as cur:
        line_var = cur.var(str)
        status_var = cur.var(int)
        while True:
            cur.callproc("dbms_output.get_line", [line_var, status_var])
            if status_var.getvalue() != 0:
                break
            lines.append(line_var.getvalue() or "")
    return lines


# ---------------------------------------------------------------------------------------------------------------
# Column maps shared by the loader, the vector builder and the ONNX scripts.
# ---------------------------------------------------------------------------------------------------------------
def camel_to_snake(name: str) -> str:
    """championName -> CHAMPION_NAME, totalDamageDealtToChampions -> TOTAL_DAMAGE_DEALT_TO_CHAMPIONS."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).upper()


# parquet column -> PLAYER_MATCH column, where the generic camel->SNAKE rule does not apply.
PERFORMANCE_RENAMES = {"match_id": "MATCH_ID", "win": "WIN", "duration": "DURATION_MIN"}

# by_minute parquet column -> BY_MINUTE_SNAPSHOT column (readable names; Select AI sends them to the LLM).
BYMIN_COLUMNS = {
    "match_id": "MATCH_ID", "slot": "SLOT", "winner": "WINNER", "minute": "GAME_MINUTE", "timestamp": "TIMESTAMP_MS",
    "magicresist": "MAGIC_RESIST", "healthregenrate": "HEALTH_REGEN_RATE", "spellvamp": "SPELL_VAMP",
    "bonusarmorpenetrationpercent": "BONUS_ARMOR_PEN_PERCENT", "bonusmagicpenetrationpercent": "BONUS_MAGIC_PEN_PERCENT",
    "maxhealth": "MAX_HEALTH", "movespeed": "MOVE_SPEED", "attackdamage": "ATTACK_DAMAGE",
    "armorpenetrationpercent": "ARMOR_PEN_PERCENT", "lifesteal": "LIFE_STEAL", "abilitypower": "ABILITY_POWER",
    "cooldownreduction": "COOLDOWN_REDUCTION", "resourcevalue": "RESOURCE_VALUE",
    "magicpenetrationflat": "MAGIC_PEN_FLAT", "attackspeed": "ATTACK_SPEED", "currenthealth": "CURRENT_HEALTH",
    "armor": "ARMOR", "magicpenetrationpercent": "MAGIC_PEN_PERCENT", "armorpenetrationflat": "ARMOR_PEN_FLAT",
    "resourcemax": "RESOURCE_MAX", "resourceregenrate": "RESOURCE_REGEN_RATE",
}


def performance_column(parquet_col: str) -> str:
    return PERFORMANCE_RENAMES.get(parquet_col) or camel_to_snake(parquet_col)


# ---- "games like this" embedding ------------------------------------------------------------------------------
# Per-minute rates, so a 20 minute stomp and a 45 minute slog of the same player style land close together.
# (name, numerator parquet column(s)). Divided by duration in minutes, then z-scored with stored mean/std.
VECTOR_FEATURES = [
    ("KILLS_PM", ["kills"]),
    ("DEATHS_PM", ["deaths"]),
    ("ASSISTS_PM", ["assists"]),
    ("GOLD_PM", ["goldEarned"]),
    ("DAMAGE_PM", ["totalDamageDealtToChampions"]),
    ("DAMAGE_TAKEN_PM", ["totalDamageTaken"]),
    ("CS_PM", ["totalMinionsKilled", "neutralMinionsKilled"]),
    ("VISION_PM", ["visionScore"]),
    ("OBJECTIVE_DAMAGE_PM", ["damageDealtToObjectives"]),
    ("TURRET_DAMAGE_PM", ["damageDealtToTurrets"]),
    ("CC_TIME_PM", ["timeCCingOthers"]),
    ("HEAL_SHIELD_PM", ["totalHealsOnTeammates", "totalDamageShieldedOnTeammates"]),
]
VECTOR_DIM = len(VECTOR_FEATURES)


def is_holdout(match_ids):
    """Deterministic 5% of matches that are NEVER put into PLAYER_GAME_VECTOR. Used as 'new games' to search with.

    Works on a pandas Series / numpy array of numeric match ids."""
    import numpy as np
    return (np.asarray(match_ids).astype("int64") % 20) == 7


def rate_features(df):
    """Raw per-minute rate matrix (n, VECTOR_DIM) float64 from a performance DataFrame."""
    import numpy as np
    minutes = df["duration"].to_numpy(dtype="float64")
    cols = [df[nums].fillna(0).sum(axis=1).to_numpy(dtype="float64") / minutes for _, nums in VECTOR_FEATURES]
    return np.column_stack(cols)


def embed(df, mean, std):
    """z-score the rate features with the STORED mean/std (table VECTOR_NORM) -> float32 matrix (n, VECTOR_DIM)."""
    import numpy as np
    return ((rate_features(df) - np.asarray(mean)) / np.asarray(std)).astype("float32")


def load_norm(conn):
    """Read the stored mean/std (in VECTOR_FEATURES order) from VECTOR_NORM."""
    import numpy as np
    with conn.cursor() as cur:
        cur.execute("select feature_name, mean_value, std_value from vector_norm order by feature_order")
        rows = cur.fetchall()
    if not rows:
        raise RuntimeError("VECTOR_NORM is empty. Run: python scripts/db_vectors.py")
    names = [r[0] for r in rows]
    expect = [n for n, _ in VECTOR_FEATURES]
    if names != expect:
        raise RuntimeError(f"VECTOR_NORM features {names} differ from lolml.db.VECTOR_FEATURES {expect}")
    return np.array([r[1] for r in rows]), np.array([r[2] for r in rows])


GAMES_LIKE_SQL = """
SELECT pm.player_match_id, pm.champion_name, pm.team_position, pm.win,
       pm.kills || '/' || pm.deaths || '/' || pm.assists AS kda,
       ROUND(VECTOR_DISTANCE(v.embedding, :q, COSINE), 4) AS cosine_distance
FROM   player_game_vector v
JOIN   player_match pm ON pm.player_match_id = v.player_match_id
ORDER  BY VECTOR_DISTANCE(v.embedding, :q, COSINE)
FETCH {mode} FIRST {k} ROWS ONLY
"""


def games_like(conn, embedding, k: int = 5, exact: bool = False):
    """The k stored player-games closest (cosine) to one embedding. ``exact=False`` lets the vector index answer."""
    import array
    vec = array.array("f", [float(x) for x in embedding])
    return query_df(conn, GAMES_LIKE_SQL.format(mode="EXACT" if exact else "APPROX", k=int(k)), {"q": vec})


# ---- ONNX models scored inside the database ---------------------------------------------------------------------
# Post-game model: the honest post-game stats of lolml.features.post_game_numeric that exist as PLAYER_MATCH columns.
ONNX_POSTGAME_FEATURES = [
    "kills", "deaths", "assists", "champLevel", "goldEarned", "goldSpent", "totalDamageDealtToChampions",
    "totalDamageTaken", "damageDealtToObjectives", "damageDealtToTurrets", "totalMinionsKilled",
    "neutralMinionsKilled", "visionScore", "detectorWardsPlaced", "timeCCingOthers", "totalHealsOnTeammates",
    "totalDamageShieldedOnTeammates", "totalTimeSpentDead", "largestKillingSpree", "largestMultiKill",
    "doubleKills", "firstBloodKill", "dragonKills", "baronKills", "duration",
]
# Live model: lolml.features.BYMIN_LIVE_SAFE, columns of BY_MINUTE_SNAPSHOT.
ONNX_MODELS = {
    # key: (database model name, source table, label column in the table)
    "postgame": ("LOL_WIN_POSTGAME", "PLAYER_MATCH", "WIN"),
    "live": ("LOL_WIN_LIVE", "BY_MINUTE_SNAPSHOT", "WINNER"),
}


def onnx_feature_columns(kind: str) -> tuple[list[str], list[str]]:
    """(parquet feature names, database column names) for the 'postgame' or 'live' model."""
    from . import features as F
    if kind == "postgame":
        src = ONNX_POSTGAME_FEATURES
        return src, [performance_column(c) for c in src]
    src = F.BYMIN_LIVE_SAFE
    return src, [BYMIN_COLUMNS[c] for c in src]


def onnx_metadata(kind: str) -> dict:
    """JSON metadata for DBMS_DATA_MINING.IMPORT_ONNX_MODEL: one input tensor 'float_input' -> named table columns."""
    _, cols = onnx_feature_columns(kind)
    return {"function": "classification", "classificationProbOutput": "probabilities",
            "labels": [0, 1], "input": {"float_input": cols}}
