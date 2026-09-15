"""Copy a portal database from the old SQLite file into PostgreSQL.

    .venv\\Scripts\\python.exe scripts\\migrate_sqlite_to_postgres.py
    .venv\\Scripts\\python.exe scripts\\migrate_sqlite_to_postgres.py data\\portal.db --replace

Reads every table from the SQLite file (default ``data/portal.db``) and
inserts the rows into the database at DATABASE_URL, creating the schema
first. Ids are kept, so links between tables survive. The target must be
empty unless ``--replace`` is given, which wipes it first. Old sign-in
sessions are not copied: everyone signs in again and gets a JWT.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings  # noqa: E402
from src.portal.db import TABLES, connect, init_db, scalar  # noqa: E402

# Parents before children, so foreign keys are satisfied as rows arrive.
ORDER = ("doctors", "students", "tasks", "videos", "item_progress", "attempts",
         "deep_state", "task_results", "video_views")
BOOLEAN_COLUMNS = {("students", "invite_email_sent")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sqlite_path", nargs="?", default=str(settings.data_dir / "portal.db"))
    ap.add_argument("--replace", action="store_true", help="empty the PostgreSQL tables first")
    args = ap.parse_args()

    src_path = Path(args.sqlite_path)
    if not src_path.is_file():
        print(f"No SQLite file at {src_path}", file=sys.stderr)
        return 2
    src = sqlite3.connect(str(src_path))
    src.row_factory = sqlite3.Row
    have = {r["name"] for r in src.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    init_db()
    copied: dict[str, int] = {}
    with connect() as dst:
        if args.replace:
            dst.execute("TRUNCATE " + ", ".join(TABLES) + " RESTART IDENTITY CASCADE")
        elif any(scalar(dst, f"SELECT COUNT(*) FROM {t}") for t in ORDER):
            print("The PostgreSQL database already has data; pass --replace to overwrite it.", file=sys.stderr)
            return 3
        for table in ORDER:
            if table not in have:
                continue
            rows = src.execute(f"SELECT * FROM {table}").fetchall()
            if not rows:
                continue
            columns = rows[0].keys()
            placeholders = ", ".join(["%s"] * len(columns))
            sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
            for row in rows:
                values = [bool(row[c]) if (table, c) in BOOLEAN_COLUMNS else row[c] for c in columns]
                dst.execute(sql, values)
            copied[table] = len(rows)
            if "id" in columns:
                # SERIAL sequences do not see explicit ids; continue after the highest one.
                dst.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), (SELECT MAX(id) FROM {table}))")
        dst.commit()

    for table, n in copied.items():
        print(f"{table:<14} {n:>6} rows")
    print(f"Done: {sum(copied.values())} rows copied to {settings.database_url.rsplit('@', 1)[-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
