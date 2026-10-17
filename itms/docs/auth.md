# Console sign-in

The web console (`/console/*`) requires an account. Signed-out visitors are
redirected to `/login`; after signing in they land on the page they asked for.
The landing page (`/`) stays public.

## Database

**PostgreSQL**, the instance the platform already runs (`docker compose up -d
postgres`). Accounts live in one table, `app_user`
([`infra/postgres/init/003_app_user.sql`](../infra/postgres/init/003_app_user.sql)).
Passwords are stored only as scrypt hashes. api-service creates the table itself
the first time it needs it, so an existing database needs no manual migration.

No account exists until you create one. There is no default password.

```bash
cd itms
make setup                                   # installs api-service (+ psycopg)
make infra-up                                # Postgres, Redis, MinIO
.venv/bin/python -m api_service.users create komal --name "Komal S"
make dev                                     # then open http://localhost:5173
```

Other account commands: `passwd`, `disable`, `enable`, `unlock`, `list`
(`python -m api_service.users --help`). Changing a password or disabling an
account signs that user out everywhere. Passwords are at least 10 characters.

## Configuration (api-service environment)

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `postgresql://itms:itms@localhost:5432/itms` | Use a real password in production. |
| `AUTH_SECRET` | random per process | **Required in production.** At least 32 characters (`openssl rand -hex 32`). Signs session cookies. If unset, every restart signs everyone out and several workers reject each other's cookies. |
| `AUTH_COOKIE_SECURE` | `true` | Leave on behind HTTPS. `scripts/dev.sh` sets `false` for plain-http local dev only. |
| `AUTH_SESSION_HOURS` | `12` | Session lifetime. |

## Deploying

The browser calls `/api/v1/auth/*` on **the same origin as the site**, and the
session is an HttpOnly cookie, so the site and api-service must sit behind one
host. A static-only deployment (just the built `dist/` on a static host) cannot
sign anyone in; the login page says "can't reach the sign-in service" and the
console stays closed.

Build the frontend (`npm run build`), serve `dist/` with a fallback to
`index.html`, and proxy `/api/` (and `/ws/` for the live stream) to api-service. Example nginx:

```nginx
limit_req_zone $binary_remote_addr zone=itms_login:10m rate=10r/m;

server {
    listen 443 ssl;                       # HTTPS is required for Secure cookies
    server_name console.example.org;
    root /srv/itms/dist;

    location / { try_files $uri /index.html; }

    # Per-IP brake on password guessing, on top of the per-account lockout.
    location = /api/v1/auth/login {
        limit_req zone=itms_login burst=5 nodelay;
        proxy_pass http://127.0.0.1:8000/v1/auth/login;
    }
    location /api/ {
        proxy_pass http://127.0.0.1:8000/;      # strips the /api prefix
        proxy_set_header Host $host;
    }
    location /ws/ {                             # live stream: browser uses /ws/v1/stream
        proxy_pass http://127.0.0.1:8000/;      # strips the /ws prefix
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

Checklist before going live: HTTPS on; `AUTH_SECRET` set and identical on every
api-service instance; `DATABASE_URL` points at a database with a non-default
password; first account created; `/api` proxied same-origin.

## What this does and does not protect

- It gates the **web console**. A signed-out visitor cannot open any console page.
- It does **not yet** protect api-service's own endpoints: the WebSocket stream,
  `POST /v1/commands` and the incident reads are as open as before (incident
  confirm/reject still need `X-API-Key`). Anyone who can reach api-service
  directly can use them, so keep it off the public internet (bind it to
  localhost / a private network, expose only the proxy) until those endpoints
  take `Depends(auth.current_user)`. This was already listed as a deployment
  gate in [`command-center-experience.md`](command-center-experience.md).
- After five wrong passwords an account locks for 15 minutes. That also lets
  someone who knows a username lock that user out for a while; `users unlock`
  clears it.
- Sessions are stateless cookies. "Sign out" clears the cookie in that browser;
  to cut off a session elsewhere, change the password or disable the account.
- There is no self-service sign-up or password reset: an administrator manages
  accounts with the commands above.

## Tests

- `services/api-service/tests/test_auth.py` (hashing, cookies, lockout, HTTP
  contract). The Postgres class runs with `RUN_INTEGRATION_TESTS=1
  AUTH_TEST_DATABASE_URL=postgresql://…` pointing at a scratch database.
- `web-app/src/services/auth/*.test.ts` (client, store, redirect safety) and
  `web-app/e2e/login.spec.ts` (the flow in a browser, plus axe in both themes).
