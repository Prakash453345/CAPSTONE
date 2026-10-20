# Running TRAFFIX for other people (free)

One Docker setup runs everything: the database, Redis, the live simulation, the
API and the website, all on **one address**. The same files work on your Mac
today and on a server later; only where you run them changes.

```
browser ──https──> tunnel / Caddy ──> api (site + /api + /ws, port 8000) ──> postgres, redis
                                                         ▲
                                       sim (SUMO live) ──┘ (through redis)
```

Who can sign in: the accounts in `../.local/accounts.csv` (operators land on the
console, drivers on the crew page). Their passwords are in
`../.local/console_credentials.txt`. Both files are git-ignored.

## Now: on your Mac, with a free HTTPS link

Needs Docker Desktop (the same one `make infra-up` uses).

1. Stop `make dev` / `./scripts/dev.sh` first (Ctrl+C): two simulations at once
   would just share the CPU.
2. Settings, once:
   ```bash
   cd itms/deploy
   cp .env.example .env
   open -e .env      # fill POSTGRES_PASSWORD, AUTH_SECRET (openssl rand -hex 32), SMTP_*
   ```
3. Start it (the first build takes about 10 minutes):
   ```bash
   docker compose --profile tunnel up -d --build
   ```
4. Create the accounts (safe to repeat; it updates them):
   ```bash
   docker compose run --rm -v "$PWD/../.local:/local:ro" api seed /local/accounts.csv
   ```
5. Get the link and share it:
   ```bash
   docker compose logs tunnel | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | tail -1
   ```
   On your own Mac it is also at http://localhost:8080.

Good to know:
- The link is a Cloudflare "quick tunnel": free, HTTPS, no account. It **changes
  every time the tunnel restarts**, and it works only while your Mac is awake and
  online. Cloudflare means quick tunnels for testing and demos, not for always-on use.
- Stop everything: `docker compose --profile tunnel down`. Accounts are kept;
  `down -v` also deletes the database.
- After pulling new code: `docker compose --profile tunnel up -d --build`.

## Later: a free server

Any Ubuntu 22.04/24.04 machine with 2+ CPU cores and 4+ GB of memory will do.
A free option is Oracle Cloud's **Always Free** Ampere A1 VM (currently up to
2 cores and 12 GB of memory free).

1. Create the VM (Ubuntu), then on it:
   ```bash
   curl -fsSL https://get.docker.com | sudo sh
   sudo usermod -aG docker $USER && newgrp docker
   git clone https://github.com/Prakash453345/CAPSTONE.git && cd CAPSTONE && git checkout komal
   ```
2. Copy your two secret files from the Mac (they are not in git):
   ```bash
   # on the Mac
   scp itms/deploy/.env            ubuntu@<server-ip>:CAPSTONE/itms/deploy/.env
   scp itms/.local/accounts.csv    ubuntu@<server-ip>:CAPSTONE/itms/.local/accounts.csv
   ```
3. Same commands as on the Mac:
   ```bash
   cd CAPSTONE/itms/deploy
   docker compose --profile tunnel up -d --build
   docker compose run --rm -v "$PWD/../.local:/local:ro" api seed /local/accounts.csv
   ```
4. A fixed address instead of the changing tunnel link: point a (sub)domain at
   the server's IP (a free one from duckdns.org works), open ports 80 and 443 in
   the cloud firewall, set `SITE_DOMAIN=yourname.duckdns.org` in `.env`, and run
   `docker compose --profile https up -d --build`. Caddy gets the HTTPS
   certificate by itself. The site is then https://yourname.duckdns.org.

## Everyday commands (from `itms/deploy`)

| What | Command |
|---|---|
| Is it running? | `docker compose ps` |
| Logs | `docker compose logs -f api sim` |
| List accounts | `docker compose run --rm api users list` |
| Change a password | `docker compose run --rm api users passwd <username>` |
| Add/update accounts | edit `../.local/accounts.csv`, then the `seed` command above |
| Restart after a code change | `docker compose --profile tunnel up -d --build` |

## Settings

All in `deploy/.env` (see `.env.example` for every option). The ones that matter:

- `AUTH_SECRET`: keep it the same, or every restart signs everyone out.
- `AUTH_COOKIE_SECURE=true` behind the tunnel or Caddy (both are HTTPS). Only for
  plain `http://` testing set it to `false`, or sign-in silently fails.
- `SMTP_*`: forgot-password emails. For Gmail, `SMTP_PASSWORD` is an App password.
- `CREW_AUTO_ACCEPT=true` assigns the nearest free crew at once and notifies them;
  `false` asks them first. `CREW_REQUIRE_SIGN_IN=false` treats every crew as on duty.
- `API_REQUIRE_SIGN_IN=true`: commands and the live stream need a signed-in
  account, so a stranger with the link cannot drive the simulation.

Crew call alerts (browser notifications) need HTTPS, which the tunnel and Caddy
provide; on plain `http://<ip>` the crew page still shows calls, without alerts.

## Safety

- `.env` and `.local/` hold passwords: never commit them (both are git-ignored).
- Use a long random `POSTGRES_PASSWORD`. The database and Redis are not exposed
  outside Docker; only the site is.
- Anyone with the link can see the sign-in page. Give each person their own
  account, and disable accounts that are no longer needed
  (`docker compose run --rm api users disable <username>`).
