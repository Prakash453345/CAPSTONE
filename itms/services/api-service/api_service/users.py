"""Manage console accounts from the command line.

    python -m api_service.users create <username> [--name "Display Name"]
    python -m api_service.users passwd <username>
    python -m api_service.users disable <username>
    python -m api_service.users enable <username>
    python -m api_service.users unlock <username>
    python -m api_service.users list

Passwords are prompted for (never taken as an argument, which would land in
shell history and `ps`). For scripted setup, pipe the password on stdin and
pass --stdin. Reads DATABASE_URL, like the API.
"""

from __future__ import annotations

import argparse
import getpass
import sys

import psycopg

from api_service import auth


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        password = getpass.getpass("Password: ")
        if getpass.getpass("Repeat password: ") != password:
            raise SystemExit("error: passwords do not match")
    problem = auth.validate_password(password)
    if problem:
        raise SystemExit(f"error: {problem}")
    return password


def _username(raw: str) -> str:
    username = auth.normalize_username(raw)
    problem = auth.validate_username(username)
    if problem:
        raise SystemExit(f"error: {problem}")
    return username


def _require_one(cur: psycopg.Cursor, username: str) -> None:
    if cur.rowcount != 1:
        raise SystemExit(f"error: no such user: {username}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m api_service.users", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    create = sub.add_parser("create", help="add a user")
    create.add_argument("username")
    create.add_argument("--name", default="", help="display name shown in the console")
    create.add_argument("--stdin", action="store_true", help="read the password from stdin")
    passwd = sub.add_parser("passwd", help="change a password (signs the user out everywhere)")
    passwd.add_argument("username")
    passwd.add_argument("--stdin", action="store_true", help="read the password from stdin")
    for name, text in (
        ("disable", "block sign-in and end existing sessions"),
        ("enable", "allow sign-in again"),
        ("unlock", "clear a failed-attempt lockout"),
    ):
        sub.add_parser(name, help=text).add_argument("username")
    sub.add_parser("list", help="show all users")
    args = parser.parse_args(argv)

    try:
        with psycopg.connect(auth.DATABASE_URL, connect_timeout=5, client_encoding="utf8") as conn:
            conn.execute("SELECT pg_advisory_xact_lock(727401)")
            conn.execute(auth.SCHEMA_SQL)
            if args.cmd == "list":
                rows = conn.execute(
                    "SELECT username, display_name, is_active, locked_until, last_login_at"
                    " FROM app_user ORDER BY username"
                ).fetchall()
                for username, name, active, locked, last in rows:
                    flags = ("" if active else " [disabled]") + (
                        " [locked]" if locked and locked > auth.utcnow() else ""
                    )
                    print(f"{username}\t{name}\tlast login: {last or 'never'}{flags}")
                if not rows:
                    print("no users yet -- create one: python -m api_service.users create <name>")
                return
            username = _username(args.username)
            if args.cmd == "create":
                password = _read_password(args.stdin)
                try:
                    conn.execute(
                        "INSERT INTO app_user (username, display_name, password_hash)"
                        " VALUES (%s, %s, %s)",
                        (username, args.name.strip(), auth.hash_password(password)),
                    )
                except psycopg.errors.UniqueViolation:
                    raise SystemExit(f"error: user already exists: {username}") from None
                print(f"created {username}")
            elif args.cmd == "passwd":
                password = _read_password(args.stdin)
                cur = conn.execute(
                    "UPDATE app_user SET password_hash = %s, failed_attempts = 0,"
                    " locked_until = NULL, session_version = session_version + 1"
                    " WHERE username = %s",
                    (auth.hash_password(password), username),
                )
                _require_one(cur, username)
                print(f"password changed for {username}; their sessions are signed out")
            elif args.cmd == "disable":
                cur = conn.execute(
                    "UPDATE app_user SET is_active = false, session_version = session_version + 1"
                    " WHERE username = %s",
                    (username,),
                )
                _require_one(cur, username)
                print(f"disabled {username}")
            elif args.cmd == "enable":
                cur = conn.execute(
                    "UPDATE app_user SET is_active = true WHERE username = %s", (username,)
                )
                _require_one(cur, username)
                print(f"enabled {username}")
            elif args.cmd == "unlock":
                cur = conn.execute(
                    "UPDATE app_user SET failed_attempts = 0, locked_until = NULL"
                    " WHERE username = %s",
                    (username,),
                )
                _require_one(cur, username)
                print(f"unlocked {username}")
    except psycopg.OperationalError as exc:
        raise SystemExit(f"error: cannot reach the database: {exc}") from None


if __name__ == "__main__":
    main()
