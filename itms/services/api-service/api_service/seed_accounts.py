"""Create or update console accounts from a CSV file, in one go.

    python -m api_service.seed_accounts .local/accounts.csv
    python -m api_service.seed_accounts .local/accounts.csv --dry-run

The file has a header row and these columns (extra columns are ignored):

    username,password,email,role,unit_kind,unit_id,display_name

- role: operator (the console) or responder (a crew: the crew page only)
- unit_kind: ambulance, police or fire_truck (responders only; blank for operators)
- unit_id: the vehicle a responder drives, e.g. AMB-03 (blank for operators)
- email: where forgot-password codes go; blank for none

It is safe to run again: an existing account is updated to match the row
(name, email, role, vehicle), and its password is changed only when the file's
password is not already its password -- which also signs that account out.
The file holds passwords, so keep it out of git (`.local/` is ignored).

Reads DATABASE_URL, like the API. On a server: run it inside the api
container (deploy/README.md).
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import psycopg

from api_service import auth
from api_service.users import _email, _unit, _username

FIELDS = ("username", "password", "email", "role", "unit_kind", "unit_id", "display_name")
ROLES = ("operator", "responder")


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        have = reader.fieldnames or []
        missing = [f for f in ("username", "password", "role") if f not in have]
        if missing:
            raise SystemExit(f"error: {path} has no column {', '.join(missing)}")
        return [
            {k: (row.get(k) or "").strip() for k in FIELDS}
            for row in reader
            if (row.get("username") or "").strip() and not row["username"].lstrip().startswith("#")
        ]


def _check(row: dict[str, str]) -> dict:
    """The row as database values, or SystemExit naming the problem."""
    name = row["username"]
    username = _username(name)
    problem = auth.validate_password(row["password"])
    if problem:
        raise SystemExit(f"error: {name}: {problem}")
    role = row["role"] or "operator"
    if role not in ROLES:
        raise SystemExit(f"error: {name}: role must be operator or responder, not {role!r}")
    kind = row["unit_kind"] or None
    unit = _unit(row["unit_id"]) if row["unit_id"] else None
    if role == "responder":
        if kind not in auth.UNIT_KINDS:
            kinds = ", ".join(auth.UNIT_KINDS)
            raise SystemExit(f"error: {name}: unit_kind must be one of {kinds}")
        if not unit:
            raise SystemExit(f"error: {name}: a responder needs a unit_id (its vehicle)")
    elif kind or unit:
        raise SystemExit(f"error: {name}: unit_kind and unit_id are for responders only")
    return {
        "username": username,
        "password": row["password"],
        "email": _email(row["email"]) if row["email"] else None,
        "role": role,
        "unit_kind": kind,
        "unit_id": unit,
        "display_name": row["display_name"] or username,
    }


def seed(rows: list[dict], conn: psycopg.Connection, *, dry_run: bool = False) -> list[str]:
    """Apply the rows; return one line per account saying what happened."""
    out: list[str] = []
    units = [r["unit_id"] for r in rows if r["unit_id"]]
    dupes = sorted({u for u in units if units.count(u) > 1})
    if dupes:
        raise SystemExit(f"error: two accounts drive the same vehicle: {', '.join(dupes)}")
    for r in rows:
        found = conn.execute(
            "SELECT password_hash FROM app_user WHERE username = %s", (r["username"],)
        ).fetchone()
        if found is None:
            if not dry_run:
                conn.execute(
                    "INSERT INTO app_user (username, display_name, password_hash, email, role,"
                    " unit_id, unit_kind) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (r["username"], r["display_name"], auth.hash_password(r["password"]),
                     r["email"], r["role"], r["unit_id"], r["unit_kind"]),
                )
            out.append(f"created  {r['username']}")
            continue
        if not dry_run:
            conn.execute(
                "UPDATE app_user SET display_name = %s, email = %s, role = %s, unit_id = %s,"
                " unit_kind = %s, is_active = TRUE WHERE username = %s",
                (r["display_name"], r["email"], r["role"], r["unit_id"], r["unit_kind"],
                 r["username"]),
            )
        if auth.verify_password(r["password"], found[0]):
            out.append(f"updated  {r['username']}")
        else:
            if not dry_run:
                conn.execute(
                    "UPDATE app_user SET password_hash = %s, failed_attempts = 0,"
                    " locked_until = NULL, session_version = session_version + 1"
                    " WHERE username = %s",
                    (auth.hash_password(r["password"]), r["username"]),
                )
            out.append(f"updated  {r['username']} (new password; signed out)")
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("csv", type=Path, help="accounts file (see the format above)")
    parser.add_argument(
        "--dry-run", action="store_true", help="check the file and say what would change"
    )
    args = parser.parse_args(argv)
    if not args.csv.is_file():
        raise SystemExit(f"error: no such file: {args.csv}")
    rows = [_check(r) for r in _rows(args.csv)]
    if not rows:
        raise SystemExit(f"error: {args.csv} has no accounts")
    try:
        with psycopg.connect(auth.DATABASE_URL, connect_timeout=5, client_encoding="utf8") as conn:
            conn.execute("SELECT pg_advisory_xact_lock(727401)")
            conn.execute(auth.SCHEMA_SQL)
            for line in seed(rows, conn, dry_run=args.dry_run):
                print(("(dry run) " if args.dry_run else "") + line)
            if args.dry_run:
                conn.rollback()
    except psycopg.OperationalError as exc:
        raise SystemExit(f"error: cannot reach the database ({auth.DATABASE_URL}): {exc}") from None


if __name__ == "__main__":
    main(sys.argv[1:])
