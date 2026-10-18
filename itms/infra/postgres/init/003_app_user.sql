-- Console sign-in accounts (api-service: api_service/auth.py). Passwords are
-- stored only as scrypt hashes. There is deliberately no seed user: create the
-- first with `python -m api_service.users create <username>`.
--
-- Runs on first container init only; api-service and the users CLI also run
-- this same idempotent statement themselves, so an existing volume gets the
-- table without a manual step. Keep the three copies identical.

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
