"""Publish the fleet onto the bus, so the dispatcher knows who exists.

The fleet is not a list anyone maintains: it *is* the set of crew accounts.
A responder account with a `unit_kind` and a `unit_id` is a vehicle; create
the account and the vehicle exists, disable it and the vehicle is gone. That
removes the class of bug where a hardcoded unit list and the real crews drift
apart -- the console used to offer "Ambulance 12" whether or not anyone could
drive it.

api-service publishes because api-service owns the accounts database;
sim-service, which does the matching, has no business holding Postgres
credentials. It goes on the bus rather than over HTTP because every other
piece of live state already does, and a periodic snapshot is naturally
self-healing: a sim-service that restarts, or starts before api-service, picks
up the whole roster on the next tick instead of needing a handshake.

`on_duty` is "signed in recently", which is the honest thing the server can
know without the crew's device reporting in: an account that has not been seen
since `DUTY_WINDOW` ago is not someone you can hand an emergency to. Once the
crew page reports presence this should be replaced by that signal -- see
`mark_on_duty`.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os

from itms_common.events import encode_envelope

from api_gateway.services import auth

log = logging.getLogger("api-service.crew_roster")

TOPIC = "crew.roster"
# Republished on this cadence. Small (a few hundred bytes per unit) and
# idempotent, so the cost is noise next to the vehicle-position stream.
PUBLISH_EVERY_S = float(os.environ.get("CREW_ROSTER_SECONDS", "15"))
# How long after their last sign-in a crew still counts as on duty. A shift is
# longer than a session, so this is deliberately generous; it exists to keep
# accounts that nobody has touched in days out of the dispatch pool.
DUTY_WINDOW = dt.timedelta(hours=float(os.environ.get("CREW_DUTY_WINDOW_HOURS", "12")))
# In the simulation every crew vehicle is driven by SUMO whether or not its
# driver has the crew page open, so by default every active crew account is on
# duty. CREW_REQUIRE_SIGN_IN=true brings back "signed in within DUTY_WINDOW".
REQUIRE_SIGN_IN = os.environ.get("CREW_REQUIRE_SIGN_IN", "false").strip().lower() in {
    "1", "true", "yes", "on",
}

_SQL = """
SELECT username, display_name, unit_kind, unit_id, is_active, last_login_at
FROM app_user
WHERE role = 'responder' AND unit_kind IS NOT NULL AND unit_id IS NOT NULL
ORDER BY unit_id
"""


def read_roster(now: dt.datetime | None = None) -> list[dict]:
    """Crew accounts as dispatchable units. Raises `auth.StoreUnavailable`
    if the database cannot be reached, so the caller can keep the last
    roster rather than publishing an empty fleet."""
    import psycopg  # noqa: PLC0415 -- lazily, like PostgresUserStore

    now = now or auth.utcnow()
    try:
        with psycopg.connect(
            auth.DATABASE_URL, connect_timeout=5, client_encoding="utf8"
        ) as conn:
            rows = conn.execute(_SQL).fetchall()
    except psycopg.Error as exc:
        raise auth.StoreUnavailable(str(exc)) from exc

    units: list[dict] = []
    for username, display_name, unit_kind, unit_id, is_active, last_login in rows:
        if not is_active or unit_kind not in auth.UNIT_KINDS:
            continue
        units.append(
            {
                "username": username,
                "display_name": display_name or username,
                "unit_kind": unit_kind,
                "unit_id": unit_id,
                # A disabled account is already filtered out above; this is the
                # "have they been around today" part.
                "on_duty": (
                    bool(last_login and now - last_login <= DUTY_WINDOW)
                    if REQUIRE_SIGN_IN
                    else True
                ),
            }
        )
    return units


def mark_on_duty(username: str) -> None:
    """Placeholder seam for real presence. When the crew page starts reporting
    that a driver is at the wheel, set it here instead of inferring duty from
    the last sign-in."""
    raise NotImplementedError("crew presence reporting is not wired yet")


async def publish_forever(bus, *, every_s: float = PUBLISH_EVERY_S) -> None:
    """Publish the roster on `crew.roster` until cancelled.

    Database trouble is logged once per outage and retried, never allowed to
    kill the task: the dispatcher keeping a slightly stale roster is far better
    than it losing the fleet because Postgres blinked.
    """
    failing = False
    while True:
        try:
            units = await asyncio.to_thread(read_roster)
        except auth.StoreUnavailable as exc:
            if not failing:
                log.warning("crew roster unavailable, keeping the last one: %s", exc)
                failing = True
        except Exception:
            log.exception("crew roster read failed")
        else:
            if failing:
                log.info("crew roster readable again")
                failing = False
            # Encoded like every other event on the bus (Avro, per
            # contracts/events/crew_roster_updated.avsc): sim-service decodes
            # everything it drains that way, and a raw-JSON roster was skipped
            # as undecodable, so the dispatcher never learned the fleet.
            try:
                raw = encode_envelope(
                    event_type="CrewRosterUpdated", source="api-service",
                    payload={"units": units}, partition_key="crew",
                )
                await bus.publish(TOPIC, raw)
            except Exception:
                log.exception("crew roster publish failed")
        await asyncio.sleep(every_s)
