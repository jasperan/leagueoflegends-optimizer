"""Create the LOLML user (01) and the tables (02), or run any other numbered script from sql/.

    python scripts/db_setup.py                      # 01 as admin, then 02 as LOLML
    python scripts/db_setup.py 05c                  # one script (05 = 05a, 05b, 05c), as LOLML
    LOLML_GENAI_KEY=sk-... LOLML_GENAI_REGION=us-chicago-1 LOLML_GENAI_MODEL=<model> python scripts/db_setup.py 03   # Autonomous only

Scripts 01 (creates the user), 03a (network access for Select AI) and 07a/07b (undo both) run as the administrator (LOLML_ADMIN_USER,
default ADMIN; use SYSTEM on the Free container). Every other script runs as LOLML (LOLML_DB_USER / LOLML_DB_PASSWORD). The .sql files are plain
SQL*Plus-style scripts; you can also paste them into SQL Worksheet / SQLcl.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lolml import db  # noqa: E402


ADMIN_SCRIPTS = ("01_", "03a_", "07")   # these run as the administrator, everything else as LOLML


def find(prefix: str) -> list[Path]:
    """'05' -> 05a_*.sql, 05b_*.sql, 05c_*.sql;  '05b' -> just that one."""
    hits = sorted(db.SQL_DIR.glob(f"{prefix}*.sql"))
    if not hits:
        raise SystemExit(f"no sql/{prefix}*.sql")
    return hits


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scripts", nargs="*", default=["01", "02"], help="script numbers, e.g. 01 02 (default: 01 02)")
    ap.add_argument("--define", action="append", default=[], metavar="NAME=VALUE", help="value for &NAME in the script")
    ap.add_argument("-v", "--verbose", action="store_true", help="print every statement as it runs")
    args = ap.parse_args()

    defines = dict(d.split("=", 1) for d in args.define)
    if os.environ.get("LOLML_DB_PASSWORD"):
        defines.setdefault("LOLML_PASSWORD", os.environ["LOLML_DB_PASSWORD"])

    conns: dict[bool, object] = {}
    try:
        for num in args.scripts:
            for path in find(num if len(num) > 2 else num.zfill(2)):
                admin = path.name.startswith(ADMIN_SCRIPTS)
                if admin not in conns:
                    conns[admin] = db.connect(admin=admin)
                    print(f"connected as {'admin' if admin else 'LOLML'}: {db.banner(conns[admin])[:80]}")
                print(f"== {path.name}")
                for line in db.run_script(conns[admin], path, defines, echo=args.verbose):
                    print("  |", line)
    except db.DbConfigError as e:
        raise SystemExit(f"error: {e}")
    finally:
        for c in conns.values():
            c.close()


if __name__ == "__main__":
    main()
