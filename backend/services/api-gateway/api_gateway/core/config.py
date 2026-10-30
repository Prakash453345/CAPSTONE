"""Every setting the api-gateway reads from the environment, in one place.

| Variable     | Default                  | Meaning                                       |
|--------------|--------------------------|-----------------------------------------------|
| REDIS_URL    | redis://localhost:6379/0 | the event bus                                 |
| API_KEY      | generated per process    | shared secret for the review endpoints        |
| CLIPS_DIR    | backend/var/clips        | uploaded videos, shared with vision-service   |
| CLIP_MAX_MB  | 300                      | upload size limit                             |
| CORS_ORIGINS | localhost:5173 and :4173 | comma-separated allowed browser origins       |
| API_REQUIRE_SIGN_IN | true              | commands, stream, incidents, clips need sign-in |
| WEB_DIST     | (unset)                  | built web app to serve from this port (servers) |

API_KEY is a single shared secret, not a user/session system: it guards the
endpoints that change state (incident and clip confirm/reject), matching this
project's threat model (a local demo, one operator role). Left unset, a fresh
one is generated at start-up so local development needs no setup and the
endpoints are never silently open -- but it changes on every restart, so set
it for anything beyond local development.
"""

from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from itms_domain.paths import VAR_DIR

log = logging.getLogger("api-service.config")

# Live topics relayed to WebSocket clients. Order is only cosmetic: each topic
# gets its own consumer so busy traffic cannot starve alarms.
RELAYED_TOPICS: tuple[str, ...] = (
    "system.heartbeat",
    "traffic.vehicle-positions",
    "traffic.updated",
    "incident.candidate",
    "incident.detected",
    "incident.updated",
    "signal.changed",  # from SIM_MODE=live's arbitration ladder
    "signal.faulted",
    "anomaly.updated",  # operator / detector anomalies (SIM_MODE=live)
    "emergency.request-updated",  # emergency dispatch + routing (SIM_MODE=live)
    "emergency.vehicle-updated",  # live EV position while in transit (SIM_MODE=live)
    "emergency.corridor-updated",  # green corridor lifecycle (SIM_MODE=live)
    "emergency.dispatched",  # incident -> authority alert (SIM_MODE=live)
    "crew.offer",  # a call offered to a crew, and how they answered
    "vision.link-state",  # M8 camera-measured link state (vision-service)
    "vision.camera-status",  # M8 camera health changes (vision-service)
    "vision.clip-analysed",  # uploaded-clip analysis progress/results (vision-service clip worker)
)
# Kept as "api-service": the consumer group and event `source` are wire
# identifiers other services and existing Redis streams already use.
CONSUMER_GROUP = "api-service"
EVENT_SOURCE = "api-service"
COMMANDS_TOPIC = "commands.operator"


@dataclass(frozen=True)
class Settings:
    redis_url: str = "redis://localhost:6379/0"
    api_key: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    clips_dir: Path = VAR_DIR / "clips"
    clip_max_bytes: int = 300 * 1024 * 1024
    # Which websites may call this API from a browser. The console never
    # needs CORS (Vite serves it and proxies /api and /ws same-origin), so
    # the default is only the console's own dev and preview origins, not "*":
    # with "*" any page an operator opened could post commands to a gateway
    # running on their machine. Set CORS_ORIGINS for other deployments.
    cors_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    )
    topics: tuple[str, ...] = RELAYED_TOPICS
    # Anyone who can reach the gateway could otherwise drive the simulation and
    # read the live stream. With the site shared beyond one laptop, both need a
    # signed-in account (the same session cookie the pages use).
    require_sign_in: bool = True
    # The built web app (`npm run build` -> frontend/dist). When set, the gateway
    # serves it and `/api` + `/ws` on one address, so sign-in stays a same-origin
    # cookie without a separate web server (deploy/README.md).
    web_dist: str = ""

    @classmethod
    def from_env(cls) -> Settings:
        env_key = os.environ.get("API_KEY")
        settings = cls(
            redis_url=os.environ.get("REDIS_URL", cls.redis_url),
            api_key=env_key or secrets.token_urlsafe(24),
            clips_dir=Path(os.environ.get("CLIPS_DIR", cls.clips_dir)).resolve(),
            clip_max_bytes=int(float(os.environ.get("CLIP_MAX_MB", "300")) * 1024 * 1024),
            cors_origins=tuple(
                o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()
            )
            or cls.cors_origins,
            require_sign_in=os.environ.get("API_REQUIRE_SIGN_IN", "true").strip().lower()
            not in {"0", "false", "no", "off"},
            web_dist=os.environ.get("WEB_DIST", "").strip(),
        )
        if not env_key:
            log.warning(
                "API_KEY not set -- generated one for this process so incident confirm/reject "
                "stay protected without extra setup (X-API-Key: %s). It changes every restart; "
                "set API_KEY yourself for anything beyond local dev.",
                settings.api_key,
            )
        return settings
