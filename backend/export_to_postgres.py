"""Copy every ReMind sign-up from the local SQLite file into PostgreSQL. One command.

    python backend/export_to_postgres.py "postgresql://USER:PASSWORD@HOST:5432/DBNAME"
    python backend/export_to_postgres.py                    # uses $DATABASE_URL instead
    python backend/export_to_postgres.py --sql remind_export.sql   # no driver needed: a .sql file
                                                                   # to run with: psql "$URL" -f remind_export.sql

What it does, in one transaction:
  1. creates the `registrations` table and indexes if they are missing (schema.postgres.sql)
  2. inserts every SQLite row; a WhatsApp number already in PostgreSQL is updated only if the
     SQLite copy is newer, and keeps its earliest submitted_at
It is safe to run again: re-running never duplicates anyone.
"""

from __future__ import annotations

import os
import pathlib
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from db import COLUMNS, SQLITE_PATH  # noqa: E402

UPSERT_TAIL = (
    " ON CONFLICT (whatsapp_normalized) DO UPDATE SET "
    + ", ".join(f"{c} = EXCLUDED.{c}" for c in COLUMNS if c not in ("whatsapp_normalized", "submitted_at"))
    + ", submitted_at = LEAST(registrations.submitted_at, EXCLUDED.submitted_at)"
    + " WHERE registrations.updated_at < EXCLUDED.updated_at"
)


def sqlite_rows() -> list[dict]:
    if not SQLITE_PATH.exists():
        sys.exit(f"No SQLite database at {SQLITE_PATH} (nobody has signed up locally yet).")
    con = sqlite3.connect(SQLITE_PATH)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(f"SELECT {', '.join(COLUMNS)} FROM registrations ORDER BY id")]
    con.close()
    for r in rows:
        r["consent_community"] = bool(r["consent_community"])
    return rows


def lit(v) -> str:
    """A PostgreSQL literal (standard_conforming_strings on, the default since 9.1)."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    return "'" + str(v).replace("'", "''") + "'"


def write_sql(rows: list[dict], out: pathlib.Path) -> None:
    lines = ["-- ReMind sign-ups exported from SQLite. Run: psql \"$DATABASE_URL\" -f " + out.name,
             "\\set ON_ERROR_STOP on", "SET client_encoding = 'UTF8';", "BEGIN;",
             (HERE / "schema.postgres.sql").read_text(encoding="utf-8")]
    for r in rows:
        vals = ", ".join(lit(r[c]) + ("::timestamptz" if c in ("submitted_at", "updated_at") else "") for c in COLUMNS)
        lines.append(f"INSERT INTO registrations ({', '.join(COLUMNS)}) VALUES ({vals}){UPSERT_TAIL};")
    lines.append("COMMIT;")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} sign-ups to {out}. Load it with:  psql \"$DATABASE_URL\" -f {out}")


def push(rows: list[dict], url: str) -> None:
    try:
        import psycopg
    except ImportError:
        sys.exit('PostgreSQL driver missing. Run:  pip install "psycopg[binary]"   (or use --sql FILE and psql)')
    sql = (f"INSERT INTO registrations ({', '.join(COLUMNS)}) VALUES ({', '.join(f'%({c})s' for c in COLUMNS)})"
           + UPSERT_TAIL + " RETURNING (xmax = 0) AS inserted")
    inserted = updated = 0
    with psycopg.connect(url, connect_timeout=15) as con:   # one transaction: all or nothing
        con.execute((HERE / "schema.postgres.sql").read_text(encoding="utf-8"))
        for r in rows:
            res = con.execute(sql, r).fetchone()
            if res is None:
                continue                      # PostgreSQL already had a newer copy
            inserted += res[0]; updated += not res[0]
        total = con.execute("SELECT COUNT(*) FROM registrations").fetchone()[0]
    print(f"Done. {len(rows)} SQLite sign-ups: {inserted} new, {updated} updated, "
          f"{len(rows) - inserted - updated} already current. PostgreSQL now holds {total}.")


def main(argv: list[str]) -> None:
    if len(argv) >= 2 and argv[0] == "--sql":
        write_sql(sqlite_rows(), pathlib.Path(argv[1]))
        return
    url = argv[0] if argv else os.getenv("DATABASE_URL", "")
    if not url.startswith(("postgres://", "postgresql://")):
        sys.exit(__doc__)
    push(sqlite_rows(), url)


if __name__ == "__main__":
    main(sys.argv[1:])
