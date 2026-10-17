"""Console sign-in: password hashing, session cookies, lockout, and the HTTP
contract the web app depends on. The route tests run against MemoryUserStore;
the Postgres class at the bottom runs the same flow against a real database
and is skipped unless RUN_INTEGRATION_TESTS=1 and AUTH_TEST_DATABASE_URL is set
(it creates and drops its own `app_user` rows, so point it at a scratch DB).
"""

from __future__ import annotations

import datetime as dt
import json
import os

import pytest
from api_service import auth, main
from fastapi.testclient import TestClient

PASSWORD = "correct horse battery"


@pytest.fixture
def store():
    s = auth.MemoryUserStore()
    s.add("Operator", PASSWORD, display_name="Op Erator")
    return s


@pytest.fixture
def client(store):
    main.app.dependency_overrides[auth.get_user_store] = lambda: store
    # Cookies are Secure by default, which the plain-http TestClient won't send back.
    auth.COOKIE_SECURE, saved = False, auth.COOKIE_SECURE
    yield TestClient(main.app)
    auth.COOKIE_SECURE = saved
    main.app.dependency_overrides.clear()


def login(client, username="operator", password=PASSWORD):
    return client.post("/v1/auth/login", json={"username": username, "password": password})


# ------------------------------------------------------------- primitives


def test_hash_roundtrip_and_salting():
    a, b = auth.hash_password("pw-one-two-three"), auth.hash_password("pw-one-two-three")
    assert a != b  # per-hash salt
    assert auth.verify_password("pw-one-two-three", a)
    assert not auth.verify_password("pw-one-two-four", a)
    assert "pw-one" not in a


@pytest.mark.parametrize(
    "stored", ["", "garbage", "scrypt$1$2$3$4", "bcrypt$a$b$c$d$e", "scrypt$x$8$1$!!$!!"]
)
def test_malformed_stored_hash_is_a_failed_login_not_a_crash(stored):
    assert auth.verify_password("anything", stored) is False


def test_token_roundtrip_tamper_and_expiry():
    now = auth.utcnow()
    token = auth.issue_token("operator", 3, now)
    assert auth.read_token(token, now) == ("operator", 3)

    body, sig = token.split(".")
    assert auth.read_token(f"{body}.{sig[:-2]}AA", now) is None  # bad signature
    forged = auth._b64url(json.dumps({"u": "admin", "v": 1, "exp": 9999999999}).encode())
    assert auth.read_token(f"{forged}.{sig}", now) is None  # valid-looking body, old signature
    later = now + dt.timedelta(hours=auth.SESSION_HOURS, seconds=1)
    assert auth.read_token(token, later) is None  # expired
    for junk in ["", "abc", "a.b.c", "é.é", "....", f"{body}."]:
        assert auth.read_token(junk, now) is None


def test_username_and_password_rules():
    assert auth.validate_username("op.erator-1@x") is None
    assert auth.validate_username("") is not None
    assert auth.validate_username("-lead") is not None
    assert auth.validate_username("has space") is not None
    assert auth.validate_username("a" * 65) is not None
    assert auth.validate_password("short") is not None
    assert auth.validate_password("x" * 257) is not None
    assert auth.validate_password("long enough pw") is None


# ----------------------------------------------------------------- routes


def test_login_sets_httponly_cookie_and_me_returns_user(client):
    res = login(client)
    assert res.status_code == 200
    assert res.json() == {"username": "operator", "display_name": "Op Erator"}
    assert "password" not in res.text
    cookie = res.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
    assert res.headers["cache-control"] == "no-store"

    me = client.get("/v1/auth/me")
    assert me.status_code == 200 and me.json()["username"] == "operator"
    assert me.headers["cache-control"] == "no-store"


def test_cookie_is_secure_by_default(store):
    main.app.dependency_overrides[auth.get_user_store] = lambda: store
    try:
        assert auth.COOKIE_SECURE is True
        res = TestClient(main.app, base_url="https://testserver").post(
            "/v1/auth/login", json={"username": "operator", "password": PASSWORD}
        )
        assert "secure" in res.headers["set-cookie"].lower()
    finally:
        main.app.dependency_overrides.clear()


def test_username_is_case_and_whitespace_insensitive(client):
    assert login(client, "  OPERATOR ").status_code == 200


def test_wrong_password_and_unknown_user_are_indistinguishable(client):
    wrong = login(client, password="not the password")
    unknown = login(client, username="nobody")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "Incorrect username or password."}
    assert "set-cookie" not in wrong.headers
    assert client.get("/v1/auth/me").status_code == 401


def test_me_requires_a_valid_cookie(client):
    assert client.get("/v1/auth/me").status_code == 401
    client.cookies.set(auth.COOKIE_NAME, "forged.value")
    assert client.get("/v1/auth/me").status_code == 401


def test_logout_clears_session_and_is_idempotent(client):
    login(client)
    assert client.post("/v1/auth/logout").status_code == 204
    assert client.get("/v1/auth/me").status_code == 401
    assert client.post("/v1/auth/logout").status_code == 204


def test_lockout_after_repeated_failures_then_recovers(client, store):
    for _ in range(auth.MAX_FAILED_ATTEMPTS):
        assert login(client, password="wrong wrong wrong").status_code == 401
    locked = login(client)  # even the right password is refused while locked
    assert locked.status_code == 429
    assert int(locked.headers["retry-after"]) > 0
    assert client.get("/v1/auth/me").status_code == 401

    store.users["operator"].locked_until = auth.utcnow() - dt.timedelta(seconds=1)
    assert login(client).status_code == 200
    assert store.users["operator"].failed_attempts == 0


def test_expired_lock_does_not_carry_old_failures(store):
    rec = store.users["operator"]
    rec.failed_attempts = auth.MAX_FAILED_ATTEMPTS
    rec.locked_until = auth.utcnow() - dt.timedelta(minutes=1)
    store.record_failure("operator", auth.utcnow())
    assert rec.failed_attempts == 1 and rec.locked_until is None


def test_unknown_user_does_not_lock_anything_or_crash(client, store):
    for _ in range(auth.MAX_FAILED_ATTEMPTS + 2):
        assert login(client, username="ghost").status_code == 401
    assert login(client).status_code == 200


def test_disabled_user_cannot_login_and_existing_session_ends(client, store):
    login(client)
    store.users["operator"].is_active = False
    assert client.get("/v1/auth/me").status_code == 401
    assert login(client).status_code == 401


def test_password_change_ends_existing_sessions(client, store):
    login(client)
    store.users["operator"].session_version += 1
    assert client.get("/v1/auth/me").status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"username": "operator"},
        {"username": "", "password": "x"},
        {"username": "operator", "password": ""},
        {"username": "operator", "password": "x" * 257},
        {"username": "x" * 200, "password": "x"},
        {"username": 1, "password": ["x"]},
    ],
)
def test_malformed_login_bodies_are_rejected_without_hashing(client, body):
    assert client.post("/v1/auth/login", json=body).status_code == 422


def test_store_outage_is_a_503_not_a_500_or_a_false_401(client):
    class Down:
        def get(self, username):
            raise auth.StoreUnavailable("connection refused")

    main.app.dependency_overrides[auth.get_user_store] = lambda: Down()
    res = login(client)
    assert res.status_code == 503
    assert "refused" not in res.text  # no internals leaked
    client.cookies.set(auth.COOKIE_NAME, auth.issue_token("operator", 1))
    assert client.get("/v1/auth/me").status_code == 503


# --------------------------------------------------------------- postgres


@pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_TESTS") != "1" or not os.environ.get("AUTH_TEST_DATABASE_URL"),
    reason="set RUN_INTEGRATION_TESTS=1 and AUTH_TEST_DATABASE_URL (a scratch Postgres) to run",
)
class TestPostgresStore:
    @pytest.fixture
    def pg(self):
        import psycopg

        url = os.environ["AUTH_TEST_DATABASE_URL"]
        store = auth.PostgresUserStore(url)
        with psycopg.connect(url) as conn:
            conn.execute("DROP TABLE IF EXISTS app_user")
        store.get("warmup")  # creates the schema on first use
        with psycopg.connect(url) as conn:
            conn.execute(
                "INSERT INTO app_user (username, display_name, password_hash) VALUES (%s,%s,%s)",
                ("operator", "Op Erator", auth.hash_password(PASSWORD)),
            )
        yield store
        with psycopg.connect(url) as conn:
            conn.execute("DROP TABLE IF EXISTS app_user")

    def test_flow_and_lockout_sql_matches_memory_store(self, pg):
        main.app.dependency_overrides[auth.get_user_store] = lambda: pg
        auth.COOKIE_SECURE, saved = False, auth.COOKIE_SECURE
        try:
            c = TestClient(main.app)
            assert login(c).status_code == 200
            assert c.get("/v1/auth/me").json()["display_name"] == "Op Erator"
            assert pg.get("operator").failed_attempts == 0

            for _ in range(auth.MAX_FAILED_ATTEMPTS):
                assert login(c, password="wrong wrong wrong").status_code == 401
            rec = pg.get("operator")
            assert rec.failed_attempts == auth.MAX_FAILED_ATTEMPTS and rec.locked_until
            assert login(c).status_code == 429

            # lock expired -> first new failure restarts the count at 1
            pg.record_failure("operator", rec.locked_until + dt.timedelta(seconds=1))
            rec = pg.get("operator")
            assert rec.failed_attempts == 1 and rec.locked_until is None
        finally:
            auth.COOKIE_SECURE = saved
            main.app.dependency_overrides.clear()

    def test_unreachable_database_is_store_unavailable(self):
        store = auth.PostgresUserStore("postgresql://x:y@127.0.0.1:1/none")
        with pytest.raises(auth.StoreUnavailable):
            store.get("operator")

    def test_schema_creation_is_idempotent_across_workers(self, pg):
        for _ in range(2):
            auth.PostgresUserStore(pg.url).get("operator")
