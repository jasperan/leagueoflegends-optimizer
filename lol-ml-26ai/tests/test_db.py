"""Tests for lolml.db. Run from lol-ml-26ai/:   python -m unittest tests.test_db -v   (or: pytest tests/test_db.py)

The unit tests need no database. The integration tests at the bottom run only when LOLML_DB_USER, LOLML_DB_PASSWORD
and LOLML_DB_DSN are set (a loaded LOLML schema: db_setup.py, db_load.py, db_vectors.py).
"""
from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from lolml import data, db, paths  # noqa: E402


def ddl_columns(table: str) -> list[str]:
    """Column names of CREATE TABLE <table> in sql/02_tables.sql."""
    text = (ROOT / "sql" / "02_tables.sql").read_text()
    body = re.search(rf"CREATE TABLE IF NOT EXISTS {table} \((.*?)\n\);", text, re.S | re.I).group(1)
    return [m.group(1).upper() for m in re.finditer(r"^\s{2}([a-z_0-9]+)\s+(?:NUMBER|VARCHAR2)", body, re.M | re.I)]


class ScriptRunnerTests(unittest.TestCase):
    def test_split_plain_and_plsql(self):
        text = """
-- a comment
SET SERVEROUTPUT ON
CREATE TABLE t (a NUMBER);
COMMENT ON TABLE t IS 'x; y';

DECLARE
  n NUMBER;
BEGIN
  n := 1;
  NULL;
END;
/
SELECT * FROM t;
"""
        stmts = db.split_script(text)
        self.assertEqual(len(stmts), 4)
        self.assertTrue(stmts[0].startswith("CREATE TABLE t"))
        self.assertFalse(stmts[0].endswith(";"))
        self.assertIn("n := 1;", stmts[2])
        self.assertTrue(stmts[2].rstrip().endswith("END;"))

    def test_split_real_scripts_have_no_empty_statements(self):
        defines = {"LOLML_PASSWORD": "x", "GENAI_REGION": "r", "GENAI_MODEL": "m", "GENAI_KEY": "k"}
        for p in sorted((ROOT / "sql").glob("*.sql")):
            stmts = [db.substitute(s, defines) if "&" in s else s for s in db.split_script(p.read_text())]
            self.assertTrue(stmts, p.name)
            self.assertTrue(all(s.strip() for s in stmts), p.name)

    def test_split_trailing_comment_after_semicolon(self):
        stmts = db.split_script("DROP TABLE a PURGE;   -- gone\nSELECT '--x' FROM dual;  -- keep the literal\n")
        self.assertEqual(stmts, ["DROP TABLE a PURGE", "SELECT '--x' FROM dual"])

    def test_substitute(self):
        self.assertEqual(db.substitute("a '&X' b &&Y.", {"x": "1", "Y": "2"}), "a '1' b 2")
        with self.assertRaises(db.DbConfigError):
            db.substitute("&NOT_DEFINED_ANYWHERE", {})

    def test_sql_files_only_use_known_substitution_variables(self):
        known = {"LOLML_PASSWORD", "GENAI_REGION", "GENAI_MODEL", "GENAI_KEY"}
        for p in (ROOT / "sql").glob("*.sql"):
            used = set(re.findall(r"&&?([A-Za-z_][A-Za-z0-9_]*)", p.read_text()))
            self.assertLessEqual({u.upper() for u in used}, known, p.name)

    def test_no_secrets_in_repo_files(self):
        for p in list((ROOT / "sql").glob("*")) + list((ROOT / "docker").rglob("*")) + [ROOT / "lolml" / "db.py"]:
            if p.is_file():
                text = p.read_text()
                self.assertIsNone(re.search(r"ocid1\.[a-z]+\.oc1\.\.[a-z0-9]{20,}", text), p.name)
                self.assertNotIn("BEGIN PRIVATE KEY", text, p.name)


class ConfigTests(unittest.TestCase):
    def test_missing_env_is_explained(self):
        saved = {k: os.environ.pop(k, None) for k in db.REQUIRED}
        try:
            with self.assertRaises(db.DbConfigError) as cm:
                db.connect()
            for name in db.REQUIRED:
                self.assertIn(name, str(cm.exception))
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v

    def test_bad_wallet_dir(self):
        saved = {k: os.environ.get(k) for k in (*db.REQUIRED, "LOLML_DB_WALLET_DIR")}
        os.environ.update(LOLML_DB_USER="u", LOLML_DB_PASSWORD="p", LOLML_DB_DSN="d", LOLML_DB_WALLET_DIR="/nonexistent/wallet")
        try:
            with self.assertRaises(db.DbConfigError) as cm:
                db.connect()
            self.assertIn("LOLML_DB_WALLET_DIR", str(cm.exception))
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


class ColumnMapTests(unittest.TestCase):
    def test_camel_to_snake(self):
        self.assertEqual(db.camel_to_snake("totalDamageDealtToChampions"), "TOTAL_DAMAGE_DEALT_TO_CHAMPIONS")
        self.assertEqual(db.camel_to_snake("timeCCingOthers"), "TIME_CCING_OTHERS")
        self.assertEqual(db.performance_column("duration"), "DURATION_MIN")

    def test_player_match_columns_exist_in_ddl_and_dataset(self):
        ddl = set(ddl_columns("player_match"))
        df = data.load("performance", smoke=True)
        mapped = {db.performance_column(c) for c in df.columns}
        missing = ddl - mapped - {"PLAYER_MATCH_ID"}
        self.assertFalse(missing, f"DDL columns with no dataframe source: {missing}")

    def test_by_minute_columns_exist_in_ddl_and_dataset(self):
        ddl = set(ddl_columns("by_minute_snapshot"))
        df = data.load("by_minute", smoke=True)
        mapped = {db.BYMIN_COLUMNS[c] for c in df.columns if c in db.BYMIN_COLUMNS}
        self.assertFalse(ddl - mapped - {"SNAPSHOT_ID"})
        self.assertEqual(len(mapped), len(df.columns))  # every parquet column has a home

    def test_onnx_features_are_honest_and_in_the_tables(self):
        from lolml import features as F
        df = data.load("performance", smoke=True)
        self.assertTrue(set(db.ONNX_POSTGAME_FEATURES) <= set(F.post_game_numeric(df)))
        for kind in db.ONNX_MODELS:
            _, cols = db.onnx_feature_columns(kind)
            self.assertTrue(set(cols) <= set(ddl_columns(db.ONNX_MODELS[kind][1].lower())), kind)
        meta = db.onnx_metadata("live")
        self.assertEqual(meta["labels"], [0, 1])
        self.assertEqual(len(meta["input"]["float_input"]), len(F.BYMIN_LIVE_SAFE))


class EmbeddingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = data.load("performance", smoke=True)

    def test_embed_is_standardised_and_float32(self):
        rates = db.rate_features(self.df)
        mean, std = rates.mean(axis=0), rates.std(axis=0)
        emb = db.embed(self.df, mean, std)
        self.assertEqual(emb.shape, (len(self.df), db.VECTOR_DIM))
        self.assertEqual(emb.dtype, np.float32)
        self.assertTrue(np.allclose(emb.mean(axis=0), 0, atol=1e-3))
        self.assertTrue(np.allclose(emb.std(axis=0), 1, atol=1e-3))

    def test_one_game_embeds_like_the_batch(self):
        rates = db.rate_features(self.df)
        mean, std = rates.mean(axis=0), rates.std(axis=0)
        batch = db.embed(self.df, mean, std)
        single = db.embed(self.df.iloc[[7]], mean, std)
        self.assertTrue(np.allclose(batch[7], single[0]))

    def test_vector_dim_matches_ddl(self):
        self.assertIn(f"VECTOR({db.VECTOR_DIM}, FLOAT32)", (ROOT / "sql" / "04_vector.sql").read_text())

    def test_holdout_is_about_five_percent_and_whole_matches(self):
        df = data.load("performance", smoke=True)
        hold = db.is_holdout(df["match_id"])
        self.assertAlmostEqual(hold.mean(), 0.05, delta=0.03)
        by_match = df.assign(h=hold).groupby("match_id")["h"].nunique()
        self.assertTrue((by_match == 1).all())  # a match is never split


@unittest.skipUnless(all(os.environ.get(k) for k in db.REQUIRED), "LOLML_DB_* not set: skipping database tests")
class DatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = db.connect()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def scalar(self, sql, **binds):
        with self.conn.cursor() as cur:
            cur.execute(sql, binds)
            return cur.fetchone()[0]

    def test_banner_is_26ai(self):
        self.assertIn("26ai", db.banner(self.conn))

    def test_vector_type_and_distance(self):
        d = self.scalar("select vector_distance(to_vector('[1,0]'), to_vector('[0,1]'), cosine) from dual")
        self.assertAlmostEqual(d, 1.0, places=6)

    def test_tables_have_data_and_comments(self):
        for t in ("PLAYER_MATCH", "BY_MINUTE_SNAPSHOT"):
            self.assertGreater(self.scalar(f"select count(*) from {t}"), 0, t)
            self.assertTrue(self.scalar("select comments from user_tab_comments where table_name = :t", t=t))
            nulls = self.scalar("select count(*) from user_col_comments where table_name = :t and comments is null", t=t)
            self.assertEqual(nulls, 0, f"{t} has columns without a comment")

    def test_player_match_has_whole_matches(self):
        self.assertEqual(self.scalar("select count(*) from (select match_id from player_match group by match_id "
                                     "having count(*) <> 10)"), 0)

    def test_games_like_returns_k_sorted_neighbours(self):
        if not self.scalar("select count(*) from player_game_vector"):
            self.skipTest("PLAYER_GAME_VECTOR is empty: run scripts/db_vectors.py")
        mean, std = db.load_norm(self.conn)
        df = data.load("performance")
        pos = int(np.flatnonzero(db.is_holdout(df["match_id"]))[0])
        out = db.games_like(self.conn, db.embed(df.iloc[[pos]], mean, std)[0], k=5)
        self.assertEqual(len(out), 5)
        self.assertEqual(out["cosine_distance"].tolist(), sorted(out["cosine_distance"].tolist()))
        self.assertTrue(set(out.columns) >= {"champion_name", "team_position", "win", "kda"})

    def test_onnx_import_is_available(self):
        n = self.scalar("select count(*) from all_arguments where package_name = 'DBMS_DATA_MINING' "
                        "and object_name = 'IMPORT_ONNX_MODEL'")
        self.assertGreater(n, 0)


if __name__ == "__main__":
    unittest.main()
