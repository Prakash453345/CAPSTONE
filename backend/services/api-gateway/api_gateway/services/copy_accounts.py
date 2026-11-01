"""Copy console accounts from the main database into AUTH_DATABASE_URL, once.

    python -m api_gateway.services.copy_accounts --dry-run
    python -m api_gateway.services.copy_accounts

For moving sign-in to its own (e.g. hosted) Postgres: set AUTH_DATABASE_URL to
the new database and leave DATABASE_URL on the old one, run this, and from then
on the API and the `users` CLI read and write the new one. Password hashes are
copied as they are, so everyone keeps their password.

It is safe to run again: an account whose username (or vehicle) is already in
the new database is left alone and reported as skipped, never overwritten.
Lockouts, pending reset codes and session versions are copied too, so a move
doesn't sign anyone out or unlock anyone early.
"""

from __future__ import annotations

import argparse
import os
import sys

import psycopg

from api_gateway.services import auth

# Every column but `id`, which the new database assigns.
_COLUMNS = (
    "username, display_name, password_hash, is_active, failed_attempts, locked_until,"
    " session_version, created_at, last_login_at, email, reset_code_hash, reset_expires_at,"
    " reset_attempts, reset_sent_at, role, unit_id, unit_kind"
)
_INSERT = (
    f"INSERT INTO app_user ({_COLUMNS})"
    f" VALUES ({', '.join(['%s'] * len(_COLUMNS.split(',')))})"
    " ON CONFLICT DO NOTHING"
)


def copy(source, target, dry_run: bool = False) -> list[str]:
    """Copy every `app_user` row from `source` into `target` (open connections)."""
    rows = source.execute(f"SELECT {_COLUMNS} FROM app_user ORDER BY id").fetchall()
    out = []
    for row in rows:
        username = row[0]
        if dry_run:
            taken = target.execute(
                "SELECT 1 FROM app_user WHERE username = %s OR unit_id = %s",
                (username, row[15]),
            ).fetchone()
            out.append(f"{'skipped' if taken else 'copied '}  {username}")
            continue
        cur = target.execute(_INSERT, row)
        out.append(f"{'copied ' if cur.rowcount else 'skipped'}  {username}")
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dry-run", action="store_true", help="say what would be copied")
    args = parser.parse_args(argv)

    src_url = os.environ.get("DATABASE_URL", "postgresql://itms:itms@localhost:5432/itms")
    dst_url = os.environ.get("AUTH_DATABASE_URL", "")
    if not dst_url:
        raise SystemExit("error: set AUTH_DATABASE_URL to the database to copy accounts into")
    if dst_url == src_url:
        raise SystemExit("error: AUTH_DATABASE_URL and DATABASE_URL are the same database")

    def connect(url: str):
        try:
            return psycopg.connect(url, connect_timeout=10, client_encoding="utf8")
        except psycopg.OperationalError as exc:
            where = auth.redact_url(url)
            raise SystemExit(f"error: cannot reach the database ({where}): {exc}") from None

    with connect(src_url) as source, connect(dst_url) as target:
        source.execute(auth.SCHEMA_SQL)  # an old volume may predate some columns
        target.execute("SELECT pg_advisory_xact_lock(727401)")
        target.execute(auth.SCHEMA_SQL)
        lines = copy(source, target, dry_run=args.dry_run)
        for line in lines:
            print(("(dry run) " if args.dry_run else "") + line)
        if not lines:
            print("no accounts in the main database")
        if args.dry_run:
            target.rollback()
        source.rollback()  # read-only here: leave the old database exactly as it was


if __name__ == "__main__":
    main(sys.argv[1:])
