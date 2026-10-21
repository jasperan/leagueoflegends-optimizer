"""Run a SQL statement (or a .sql file) as the LOLML user (or, with --admin, the administrator) and print the result. No SQL client needed.

    python scripts/db_sql.py "select count(*) from player_match"
    python scripts/db_sql.py -f sql/05c_onnx_score.sql
    python scripts/db_sql.py --admin "drop user lolml cascade"      # as ADMIN / SYSTEM (LOLML_ADMIN_*)

Uses LOLML_DB_USER / LOLML_DB_PASSWORD / LOLML_DB_DSN. A -f file is run with the same script runner as db_setup.py
(plain SQL ends with ';', PL/SQL blocks end with a '/' line); a statement on the command line needs no ';'.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lolml import db  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sql", nargs="?", help="one SELECT (or other) statement, without a trailing ';'")
    ap.add_argument("-f", "--file", help="run a .sql script instead")
    ap.add_argument("--admin", action="store_true", help="connect as the administrator (LOLML_ADMIN_*) instead of LOLML")
    ap.add_argument("--rows", type=int, default=50, help="maximum rows to print (default 50)")
    args = ap.parse_args()
    if bool(args.sql) == bool(args.file):
        raise SystemExit("give either one SQL statement or -f FILE")
    try:
        conn = db.connect(admin=args.admin)
        with conn:
            if args.file:
                for line in db.run_script(conn, args.file):
                    print(line)
                return
            import pandas as pd
            pd.set_option("display.width", 200)
            pd.set_option("display.max_columns", 50)
            pd.set_option("display.max_colwidth", None)
            with conn.cursor() as cur:
                stmt = args.sql.strip()
                if not stmt.lower().startswith(("begin", "declare")):   # a PL/SQL block needs its final ';'
                    stmt = stmt.rstrip(";")
                cur.execute(stmt)
                if cur.description:
                    cols = [d[0] for d in cur.description]
                    df = pd.DataFrame(cur.fetchmany(args.rows), columns=cols)
                    print(df.to_string(index=False) if len(df) else "(no rows)")
                else:
                    conn.commit()
                    print("statement executed")
    except db.DbConfigError as e:
        raise SystemExit(f"error: {e}")
    except Exception as e:  # database errors: show the ORA- message, not a traceback
        raise SystemExit(f"error: {e}")


if __name__ == "__main__":
    main()
