"""Operator sign-in for the web console.

Users live in PostgreSQL (`app_user`), the same instance the rest of the
platform already uses. A successful sign-in sets a signed, HttpOnly session
cookie; the browser never sees the password hash or the signing secret, and
JavaScript can't read the cookie.

Design choices, and what they're for:

* Passwords are hashed with scrypt from the standard library -- a memory-hard
  KDF, no extra dependency to build or patch on the deploy host. The cost
  parameters are stored in each hash, so they can be raised later without
  invalidating existing passwords.
* Unknown usernames take the same time as wrong passwords (a dummy hash is
  verified) and get the same message, so the form can't be used to discover
  which accounts exist.
* Five wrong passwords in a row lock the account for 15 minutes. That stops
  online guessing; it does mean someone who knows a username can lock that
  user out, which is the usual trade and is cleared by waiting or by
  `python -m api_service.users unlock`. Put a per-IP limit on `/v1/auth/login`
  in the reverse proxy as well (see docs/auth.md).
* The session cookie is `base64url(json).base64url(hmac-sha256)`. It carries
  the username, an expiry and the user's `session_version`; `/me` re-reads the
  user, so disabling an account or changing its password (which bumps the
  version) ends its sessions immediately instead of at expiry.
* Nothing here defaults to a known password. There is no built-in account;
  create the first one with `python -m api_service.users create <name>`.
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import datetime as dt
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from api_service import mailer

log = logging.getLogger("api-service.auth")

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://itms:itms@localhost:5432/itms")

COOKIE_NAME = "itms_session"
SESSION_HOURS = float(os.environ.get("AUTH_SESSION_HOURS", "12"))
# Sign out after this long without activity (the page sends a heartbeat to
# /v1/auth/me while someone is using it). 0 turns the idle limit off.
IDLE_MINUTES = float(os.environ.get("AUTH_IDLE_MINUTES", "30"))
# /me only re-issues the cookie when the last one is older than this.
_REFRESH_AFTER_S = 60
# Secure cookies are only sent over HTTPS. Default on, so a deployment that
# forgets to configure this fails safe; `scripts/dev.sh` turns it off for
# plain-http local development.
COOKIE_SECURE = os.environ.get("AUTH_COOKIE_SECURE", "true").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}

# What an account is for. Operators run the console; crews follow a dispatched
# route on the crew page. Operators can open both (a supervisor checks what a
# crew sees); a crew account cannot open the console.
ROLES = ("operator", "responder")
DEFAULT_ROLE = "operator"
# A crew account is tied to one vehicle: the id dispatch uses for it (e.g. EV-001).
_UNIT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")


# What a crew drives. Dispatch sends a call to the nearest free crew *of the
# right kind*, so every crew account has to say which it is. Same names as the
# wire's EmergencyVehicleKind, lower-cased.
UNIT_KINDS = ("ambulance", "police", "fire_truck")


def validate_unit_kind(kind: str) -> str | None:
    """Why `kind` isn't a crew kind, or None."""
    if kind not in UNIT_KINDS:
        return f"crew kind must be one of: {', '.join(UNIT_KINDS)}"
    return None


def infer_unit_kind(unit: str | None) -> str | None:
    """Best guess at a crew's kind from its vehicle id (`unit-police-3`,
    `amb-01`, `fire-2`), for accounts made before kinds were recorded. None
    when the id says nothing, in which case the kind must be set explicitly."""
    lowered = (unit or "").lower()
    if "police" in lowered:
        return "police"
    if "fire" in lowered:
        return "fire_truck"
    if "amb" in lowered:
        return "ambulance"
    return None


def validate_unit(unit: str) -> str | None:
    """Why `unit` can't be a vehicle id, or None."""
    if not _UNIT_RE.fullmatch(unit):
        return "vehicle id may contain letters, digits and . _ - (up to 32 characters)"
    return None


MAX_FAILED_ATTEMPTS = 5
LOCKOUT = dt.timedelta(minutes=15)
# Forgot-password: a 6-digit code, emailed, valid briefly and for a few guesses.
RESET_CODE_MINUTES = 10
RESET_MAX_ATTEMPTS = 5
RESET_RESEND_AFTER = dt.timedelta(seconds=60)
MIN_PASSWORD_LENGTH = 10
MAX_USERNAME_LENGTH = 64
# Long enough for any passphrase, short enough that hashing one is not a DoS.
MAX_PASSWORD_LENGTH = 256

_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._@-]*$")

_env_secret = os.environ.get("AUTH_SECRET")
if _env_secret and len(_env_secret) < 32:
    raise RuntimeError("AUTH_SECRET must be at least 32 characters (try: openssl rand -hex 32)")
AUTH_SECRET: bytes = (_env_secret or secrets.token_urlsafe(48)).encode()
if not _env_secret:
    log.warning(
        "AUTH_SECRET not set -- generated one for this process, so every restart signs "
        "everyone out and multiple workers will reject each other's cookies. "
        "Set AUTH_SECRET (openssl rand -hex 32) for anything beyond local dev."
    )


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def normalize_username(raw: str) -> str:
    """Usernames are case-insensitive and stored lowercase."""
    return raw.strip().lower()


def validate_username(username: str) -> str | None:
    """Why `username` (already normalized) can't be used for a new account, or None."""
    if not username:
        return "username is required"
    if len(username) > MAX_USERNAME_LENGTH:
        return f"username must be at most {MAX_USERNAME_LENGTH} characters"
    if not _USERNAME_RE.fullmatch(username):
        return (
            "username may contain letters, digits and . _ @ - and must start with a letter or digit"
        )
    return None


def validate_password(password: str) -> str | None:
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"password must be at least {MIN_PASSWORD_LENGTH} characters"
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"password must be at most {MAX_PASSWORD_LENGTH} characters"
    return None


# -------------------------------------------------------------- passwords

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**15, 8, 1  # ~32 MiB, ~70 ms: OWASP-grade for scrypt
_SCRYPT_MAXMEM = 128 * 1024 * 1024


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        maxmem=_SCRYPT_MAXMEM,
        dklen=32,
    )
    return (
        f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}"
        f"${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"
    )


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check of `password` against a `hash_password` string.
    A malformed stored hash is a failed login, never an exception."""
    try:
        scheme, n, r, p, salt, expected = stored.split("$")
        if scheme != "scrypt":
            return False
        expected_bytes = base64.b64decode(expected, validate=True)
        digest = hashlib.scrypt(
            password.encode(),
            salt=base64.b64decode(salt, validate=True),
            n=int(n),
            r=int(r),
            p=int(p),
            maxmem=_SCRYPT_MAXMEM,
            dklen=len(expected_bytes),
        )
    except (ValueError, TypeError, binascii.Error):
        return False
    return hmac.compare_digest(digest, expected_bytes)


# Verified when the username doesn't exist, so "no such user" costs as much as
# "wrong password". Computed once at import from a throwaway password.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


# --------------------------------------------------------------- sessions


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(body: str) -> str:
    return _b64url(hmac.new(AUTH_SECRET, body.encode(), hashlib.sha256).digest())


def issue_token(username: str, session_version: int, now: dt.datetime | None = None) -> str:
    now = now or utcnow()
    exp = int((now + dt.timedelta(hours=SESSION_HOURS)).timestamp())
    claims = {"u": username, "v": session_version, "exp": exp, "ls": int(now.timestamp())}
    body = _b64url(json.dumps(claims).encode())
    return f"{body}.{_sign(body)}"


def read_token(token: str, now: dt.datetime | None = None) -> tuple[str, int] | None:
    """(username, session_version) from a valid, unexpired token; else None."""
    try:
        body, sig = token.split(".")
        if not hmac.compare_digest(sig, _sign(body)):
            return None
        claims = json.loads(_unb64url(body))
        username, version, exp = claims["u"], claims["v"], claims["exp"]
        if not (isinstance(username, str) and isinstance(version, int) and isinstance(exp, int)):
            return None
    except (ValueError, KeyError, TypeError, binascii.Error):
        return None
    now_s = int((now or utcnow()).timestamp())
    if exp <= now_s:
        return None
    last_seen = claims.get("ls")
    if IDLE_MINUTES > 0 and isinstance(last_seen, int) and now_s - last_seen > IDLE_MINUTES * 60:
        return None
    return username, version


def token_age_s(token: str, now: dt.datetime | None = None) -> int:
    """Seconds since the token was last refreshed (large when unreadable)."""
    try:
        claims = json.loads(_unb64url(token.split(".")[0]))
        return max(0, int((now or utcnow()).timestamp()) - int(claims["ls"]))
    except (ValueError, KeyError, TypeError, binascii.Error):
        return 10**9


# ------------------------------------------------------------------ store


@dataclass
class UserRecord:
    username: str
    password_hash: str
    display_name: str = ""
    is_active: bool = True
    failed_attempts: int = 0
    locked_until: dt.datetime | None = None
    session_version: int = 1
    email: str | None = None
    reset_code_hash: str | None = None
    reset_expires_at: dt.datetime | None = None
    reset_attempts: int = 0
    reset_sent_at: dt.datetime | None = None
    role: str = DEFAULT_ROLE
    unit_id: str | None = None
    unit_kind: str | None = None


class StoreUnavailable(Exception):
    """The user database couldn't be reached or queried."""


class UserStore(Protocol):
    def get(self, username: str) -> UserRecord | None: ...
    def record_failure(self, username: str, now: dt.datetime) -> None: ...
    def record_success(self, username: str, now: dt.datetime) -> None: ...
    def set_reset(
        self, username: str, code_hash: str, expires: dt.datetime, sent_at: dt.datetime
    ) -> None: ...
    def record_reset_failure(self, username: str) -> None: ...
    def complete_reset(self, username: str, password_hash: str) -> None: ...


class MemoryUserStore:
    """In-process store for tests and for running the API without Postgres."""

    def __init__(self) -> None:
        self.users: dict[str, UserRecord] = {}
        self._lock = threading.Lock()

    def add(self, username: str, password: str, display_name: str = "", **kw) -> UserRecord:
        record = UserRecord(
            username=normalize_username(username),
            password_hash=hash_password(password),
            display_name=display_name,
            **kw,
        )
        self.users[record.username] = record
        return record

    def get(self, username: str) -> UserRecord | None:
        with self._lock:
            record = self.users.get(username)
            return None if record is None else UserRecord(**record.__dict__)

    def record_failure(self, username: str, now: dt.datetime) -> None:
        with self._lock:
            record = self.users.get(username)
            if record is None:
                return
            _apply_failure(record, now)

    def record_success(self, username: str, now: dt.datetime) -> None:
        with self._lock:
            record = self.users.get(username)
            if record is not None:
                record.failed_attempts, record.locked_until = 0, None

    def set_reset(
        self, username: str, code_hash: str, expires: dt.datetime, sent_at: dt.datetime
    ) -> None:
        with self._lock:
            record = self.users.get(username)
            if record is not None:
                record.reset_code_hash, record.reset_expires_at = code_hash, expires
                record.reset_attempts, record.reset_sent_at = 0, sent_at

    def record_reset_failure(self, username: str) -> None:
        with self._lock:
            record = self.users.get(username)
            if record is None or record.reset_code_hash is None:
                return
            record.reset_attempts += 1
            if record.reset_attempts >= RESET_MAX_ATTEMPTS:
                record.reset_code_hash = None  # burnt: they must ask for a new code

    def complete_reset(self, username: str, password_hash: str) -> None:
        with self._lock:
            record = self.users.get(username)
            if record is None:
                return
            record.password_hash = password_hash
            record.session_version += 1
            record.failed_attempts, record.locked_until = 0, None
            record.reset_code_hash = record.reset_expires_at = None
            record.reset_attempts = 0


def _apply_failure(record: UserRecord, now: dt.datetime) -> None:
    """Mirror of the SQL in PostgresUserStore.record_failure."""
    if record.locked_until is not None and record.locked_until <= now:
        record.failed_attempts, record.locked_until = 0, None
    record.failed_attempts += 1
    if record.failed_attempts >= MAX_FAILED_ATTEMPTS:
        record.locked_until = now + LOCKOUT


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS app_user (
    id               BIGSERIAL PRIMARY KEY,
    username         TEXT NOT NULL,
    display_name     TEXT NOT NULL DEFAULT '',
    password_hash    TEXT NOT NULL,
    is_active        BOOLEAN NOT NULL DEFAULT true,
    failed_attempts  INTEGER NOT NULL DEFAULT 0,
    locked_until     TIMESTAMPTZ,
    session_version  INTEGER NOT NULL DEFAULT 1,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at    TIMESTAMPTZ,
    email            TEXT,
    reset_code_hash  TEXT,
    reset_expires_at TIMESTAMPTZ,
    reset_attempts   INTEGER NOT NULL DEFAULT 0,
    reset_sent_at    TIMESTAMPTZ,
    role             TEXT NOT NULL DEFAULT 'operator',
    unit_id          TEXT,
    unit_kind        TEXT,
    CONSTRAINT app_user_username_lower CHECK (username = lower(username)),
    CONSTRAINT app_user_username_len CHECK (char_length(username) BETWEEN 1 AND 64)
);
CREATE UNIQUE INDEX IF NOT EXISTS app_user_username_idx ON app_user (username);
ALTER TABLE app_user ADD COLUMN IF NOT EXISTS email TEXT;
ALTER TABLE app_user ADD COLUMN IF NOT EXISTS reset_code_hash TEXT;
ALTER TABLE app_user ADD COLUMN IF NOT EXISTS reset_expires_at TIMESTAMPTZ;
ALTER TABLE app_user ADD COLUMN IF NOT EXISTS reset_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE app_user ADD COLUMN IF NOT EXISTS reset_sent_at TIMESTAMPTZ;
ALTER TABLE app_user ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'operator';
ALTER TABLE app_user ADD COLUMN IF NOT EXISTS unit_id TEXT;
ALTER TABLE app_user ADD COLUMN IF NOT EXISTS unit_kind TEXT;
-- One crew account per vehicle: two drivers claiming the same unit would both
-- be offered its calls, and the second accept would overwrite the first.
CREATE UNIQUE INDEX IF NOT EXISTS app_user_unit_idx ON app_user (unit_id)
    WHERE unit_id IS NOT NULL;
"""


class PostgresUserStore:
    """One short-lived connection per call. Sign-ins are rare and a login must
    never hold a connection while it burns ~70 ms hashing, so a pool would buy
    nothing here."""

    def __init__(self, url: str = DATABASE_URL) -> None:
        self.url = url
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    @contextlib.contextmanager
    def _conn(self):
        import psycopg  # imported lazily so tests with MemoryUserStore don't need it

        try:
            # client_encoding: a SQL_ASCII database (the default under a C locale)
            # otherwise hands text back as bytes.
            with psycopg.connect(self.url, connect_timeout=5, client_encoding="utf8") as conn:
                self._ensure_schema(conn)
                yield conn
        except psycopg.Error as exc:
            raise StoreUnavailable(str(exc)) from exc

    def _ensure_schema(self, conn) -> None:
        # Databases created before this feature never ran infra/postgres/init/
        # 003_app_user.sql (it only runs on a fresh volume), so make it so.
        if self._schema_ready:
            return
        with self._schema_lock:
            if not self._schema_ready:
                # The advisory lock keeps two workers booting together from
                # racing CREATE INDEX.
                conn.execute("SELECT pg_advisory_xact_lock(727401)")
                conn.execute(SCHEMA_SQL)
                conn.commit()
                self._schema_ready = True

    def get(self, username: str) -> UserRecord | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT username, password_hash, display_name, is_active, failed_attempts,"
                " locked_until, session_version, email, reset_code_hash, reset_expires_at,"
                " reset_attempts, reset_sent_at, role, unit_id, unit_kind"
                " FROM app_user WHERE username = %s",
                (username,),
            ).fetchone()
        return None if row is None else UserRecord(*row)

    def record_failure(self, username: str, now: dt.datetime) -> None:
        # One atomic UPDATE, so concurrent wrong guesses can't each read the
        # same count and slip past the limit.
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE app_user SET
                    failed_attempts = CASE
                        WHEN locked_until IS NOT NULL AND locked_until <= %(now)s THEN 1
                        ELSE failed_attempts + 1 END,
                    locked_until = CASE
                        WHEN (CASE WHEN locked_until IS NOT NULL AND locked_until <= %(now)s
                                   THEN 1 ELSE failed_attempts + 1 END) >= %(max)s
                            THEN %(now)s + %(lockout)s
                        WHEN locked_until IS NOT NULL AND locked_until <= %(now)s THEN NULL
                        ELSE locked_until END
                WHERE username = %(u)s
                """,
                {"now": now, "max": MAX_FAILED_ATTEMPTS, "lockout": LOCKOUT, "u": username},
            )

    def record_success(self, username: str, now: dt.datetime) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE app_user SET failed_attempts = 0, locked_until = NULL,"
                " last_login_at = %s WHERE username = %s",
                (now, username),
            )

    def set_reset(
        self, username: str, code_hash: str, expires: dt.datetime, sent_at: dt.datetime
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE app_user SET reset_code_hash = %s, reset_expires_at = %s,"
                " reset_attempts = 0, reset_sent_at = %s WHERE username = %s",
                (code_hash, expires, sent_at, username),
            )

    def record_reset_failure(self, username: str) -> None:
        # Atomic, like record_failure: parallel guesses can't share one count.
        with self._conn() as conn:
            conn.execute(
                "UPDATE app_user SET reset_attempts = reset_attempts + 1,"
                " reset_code_hash = CASE WHEN reset_attempts + 1 >= %s"
                " THEN NULL ELSE reset_code_hash END"
                " WHERE username = %s AND reset_code_hash IS NOT NULL",
                (RESET_MAX_ATTEMPTS, username),
            )

    def complete_reset(self, username: str, password_hash: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE app_user SET password_hash = %s, session_version = session_version + 1,"
                " failed_attempts = 0, locked_until = NULL, reset_code_hash = NULL,"
                " reset_expires_at = NULL, reset_attempts = 0 WHERE username = %s",
                (password_hash, username),
            )


_store: UserStore | None = None
_store_lock = threading.Lock()


def get_user_store() -> UserStore:
    """FastAPI dependency; tests override it with a MemoryUserStore."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = PostgresUserStore()
    return _store


# ----------------------------------------------------------------- routes

router = APIRouter(prefix="/v1/auth", tags=["auth"])

StoreDep = Annotated[UserStore, Depends(get_user_store)]


class LoginRequest(BaseModel):
    # Bounded so an oversized body can't make us hash megabytes.
    username: str = Field(min_length=1, max_length=MAX_USERNAME_LENGTH * 2)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class SessionUser(BaseModel):
    username: str
    display_name: str
    role: str
    # The vehicle a crew account drives; null for operators (who see every unit).
    unit_id: str | None = None
    # What the crew drives: ambulance | police | fire_truck. Null for operators.
    unit_kind: str | None = None


def _crew_kind(record: UserRecord) -> str | None:
    if record.unit_kind in UNIT_KINDS:
        return record.unit_kind
    return infer_unit_kind(record.unit_id)


def _user_out(record: UserRecord) -> SessionUser:
    return SessionUser(
        username=record.username,
        display_name=record.display_name or record.username,
        role=record.role if record.role in ROLES else DEFAULT_ROLE,
        unit_id=record.unit_id if record.role == "responder" else None,
        unit_kind=_crew_kind(record) if record.role == "responder" else None,
    )


def _no_store(response: Response) -> None:
    # Session state must never be served from a shared or browser cache.
    response.headers["Cache-Control"] = "no-store"


def _not_signed_in() -> HTTPException:
    return HTTPException(
        status_code=401, detail="Not signed in.", headers={"Cache-Control": "no-store"}
    )


def _store_down() -> HTTPException:
    return HTTPException(status_code=503, detail="Sign-in is temporarily unavailable.")


@router.post("/login", response_model=SessionUser)
def login(body: LoginRequest, response: Response, store: StoreDep) -> SessionUser:
    _no_store(response)
    username = normalize_username(body.username)
    now = utcnow()
    try:
        record = store.get(username)
        if record is not None and record.locked_until and record.locked_until > now:
            retry = int((record.locked_until - now).total_seconds()) + 1
            raise HTTPException(
                status_code=429,
                detail="Too many failed attempts. Try again later.",
                headers={"Retry-After": str(retry), "Cache-Control": "no-store"},
            )
        # Always run exactly one scrypt, whatever the username.
        ok = verify_password(body.password, record.password_hash if record else _DUMMY_HASH)
        if record is None or not record.is_active or not ok:
            if record is not None and record.is_active:
                store.record_failure(username, now)
            raise HTTPException(
                status_code=401,
                detail="Incorrect username or password.",
                headers={"Cache-Control": "no-store"},
            )
        store.record_success(username, now)
    except StoreUnavailable as exc:
        log.error("login: user store unavailable: %s", exc)
        raise _store_down() from exc

    response.set_cookie(
        COOKIE_NAME,
        issue_token(record.username, record.session_version, now),
        max_age=int(SESSION_HOURS * 3600),
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    return _user_out(record)


@router.post("/logout", status_code=204)
def logout(response: Response) -> Response:
    # Idempotent: signing out when already signed out is not an error.
    response.delete_cookie(
        COOKIE_NAME, path="/", secure=COOKIE_SECURE, httponly=True, samesite="lax"
    )
    response.headers["Cache-Control"] = "no-store"
    response.status_code = 204
    return response


def current_user(request: Request, store: StoreDep) -> UserRecord:
    """Dependency for any endpoint that needs a signed-in operator."""
    claims = read_token(request.cookies.get(COOKIE_NAME, ""))
    if claims is None:
        raise _not_signed_in()
    username, version = claims
    try:
        record = store.get(username)
    except StoreUnavailable as exc:
        log.error("session check: user store unavailable: %s", exc)
        raise _store_down() from exc
    if record is None or not record.is_active or record.session_version != version:
        raise _not_signed_in()
    return record


@router.get("/me", response_model=SessionUser)
def me(
    request: Request, response: Response, record: Annotated[UserRecord, Depends(current_user)]
) -> SessionUser:
    _no_store(response)
    # Sliding session: a page that is being used keeps asking, which keeps it alive.
    if token_age_s(request.cookies.get(COOKIE_NAME, "")) >= _REFRESH_AFTER_S:
        response.set_cookie(
            COOKIE_NAME,
            issue_token(record.username, record.session_version),
            max_age=int(SESSION_HOURS * 3600),
            httponly=True,
            secure=COOKIE_SECURE,
            samesite="lax",
            path="/",
        )
    return _user_out(record)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)
    new_password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


@router.post("/password", status_code=204)
def change_password(
    body: ChangePasswordRequest,
    response: Response,
    record: Annotated[UserRecord, Depends(current_user)],
    store: StoreDep,
) -> Response:
    """Change the signed-in user's password. Every other session is signed out;
    this one gets a fresh cookie so the person is not."""
    now = utcnow()
    if record.locked_until and record.locked_until > now:
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again later.")
    try:
        if not verify_password(body.current_password, record.password_hash):
            store.record_failure(record.username, now)
            raise HTTPException(status_code=400, detail="Current password is incorrect.")
        problem = validate_password(body.new_password)
        if problem:
            raise HTTPException(status_code=422, detail=problem.capitalize() + ".")
        if verify_password(body.new_password, record.password_hash):
            raise HTTPException(
                status_code=422, detail="New password must differ from the current one."
            )
        store.complete_reset(record.username, hash_password(body.new_password))
        fresh = store.get(record.username)
    except StoreUnavailable as exc:
        raise _store_down() from exc
    if fresh is None:
        raise _not_signed_in()
    response.set_cookie(
        COOKIE_NAME,
        issue_token(fresh.username, fresh.session_version, now),
        max_age=int(SESSION_HOURS * 3600),
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    response.status_code = 204
    return response


# --------------------------------------------------------- forgot password

NO_ACCOUNT = "No such user. Check your username."
EMAIL_NOT_USERNAME = "That looks like an email address. Enter your username instead."
_EMAIL_LIKE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
NO_EMAIL = "That account has no email on file. Ask an administrator to reset your password."


MAIL_FAILED = "We couldn't send the email. Try again shortly, or ask an administrator."


def mask_email(email: str) -> str:
    """k***@gmail.com -- enough to recognise your own address, not to learn anyone else's."""
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


BAD_CODE = "That code is incorrect or has expired."


class ForgotRequest(BaseModel):
    username: str = Field(min_length=1, max_length=MAX_USERNAME_LENGTH * 2)


class CodeRequest(ForgotRequest):
    code: str = Field(min_length=1, max_length=16)


class ResetRequest(CodeRequest):
    new_password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


def _code_digest(username: str, code: str) -> str:
    # Keyed, so a leaked database row can't be brute-forced offline without the secret.
    return hmac.new(AUTH_SECRET, f"reset:{username}:{code}".encode(), hashlib.sha256).hexdigest()


def _code_ok(store: UserStore, username: str, code: str, now: dt.datetime) -> bool:
    """True if `code` is the live reset code for `username`. A wrong guess
    counts against the code's attempts; the fifth burns it."""
    record = store.get(username)
    live = (
        record is not None
        and record.is_active
        and record.reset_code_hash is not None
        and record.reset_expires_at is not None
        and record.reset_expires_at > now
        and record.reset_attempts < RESET_MAX_ATTEMPTS
    )
    if not live:
        return False
    if (
        record
        and record.reset_code_hash
        and hmac.compare_digest(record.reset_code_hash, _code_digest(username, code.strip()))
    ):
        return True
    store.record_reset_failure(username)
    return False


@router.post("/forgot", status_code=202)
def forgot(body: ForgotRequest, response: Response, store: StoreDep) -> dict[str, str]:
    """Email a one-time code to the account's address.

    Unlike sign-in this does say when the username is unknown or has no email:
    accounts here are created by an administrator for a small set of operators,
    and a person who mistyped (or typed their email instead of their username)
    needs to be told. Put a per-IP limit on this path in the reverse proxy.
    """
    _no_store(response)
    username = normalize_username(body.username)
    now = utcnow()
    try:
        record = store.get(username)
        if record is None or not record.is_active:
            detail = EMAIL_NOT_USERNAME if _EMAIL_LIKE.fullmatch(username) else NO_ACCOUNT
            raise HTTPException(status_code=404, detail=detail)
        if not record.email:
            raise HTTPException(status_code=409, detail=NO_EMAIL)
        cooling = (
            record.reset_sent_at is not None and now - record.reset_sent_at < RESET_RESEND_AFTER
        )
        if not cooling:
            code = f"{secrets.randbelow(10**6):06d}"
            # Send first and store only if it went out, so a failed send neither
            # claims success nor starts the resend cooldown.
            try:
                mailer.send_reset_code(record.email, code, RESET_CODE_MINUTES)
            except mailer.MailError as exc:
                raise HTTPException(status_code=503, detail=MAIL_FAILED) from exc
            store.set_reset(
                username,
                _code_digest(username, code),
                now + dt.timedelta(minutes=RESET_CODE_MINUTES),
                now,
            )
    except StoreUnavailable as exc:
        log.error("forgot: user store unavailable: %s", exc)
        raise _store_down() from exc
    return {"detail": "Code sent.", "email_hint": mask_email(record.email)}


@router.post("/forgot/verify", status_code=204)
def forgot_verify(body: CodeRequest, response: Response, store: StoreDep) -> Response:
    """Check a code without using it, so the form can reject a wrong one before
    asking for a new password."""
    try:
        ok = _code_ok(store, normalize_username(body.username), body.code, utcnow())
    except StoreUnavailable as exc:
        raise _store_down() from exc
    if not ok:
        raise HTTPException(status_code=400, detail=BAD_CODE, headers={"Cache-Control": "no-store"})
    response.headers["Cache-Control"] = "no-store"
    response.status_code = 204
    return response


@router.post("/forgot/reset", status_code=204)
def forgot_reset(body: ResetRequest, response: Response, store: StoreDep) -> Response:
    """Set a new password with a valid code. Signs the user out everywhere."""
    username = normalize_username(body.username)
    problem = validate_password(body.new_password)
    if problem:
        raise HTTPException(status_code=422, detail=problem.capitalize() + ".")
    try:
        if not _code_ok(store, username, body.code, utcnow()):
            raise HTTPException(
                status_code=400, detail=BAD_CODE, headers={"Cache-Control": "no-store"}
            )
        store.complete_reset(username, hash_password(body.new_password))
    except StoreUnavailable as exc:
        raise _store_down() from exc
    response.headers["Cache-Control"] = "no-store"
    response.status_code = 204
    return response
