"""Every setting the api-gateway reads from the environment, in one place.

| Variable     | Default                  | Meaning                                       |
|--------------|--------------------------|-----------------------------------------------|
| REDIS_URL    | redis://localhost:6379/0 | the event bus                                 |
| API_KEY      | generated per process    | shared secret for the review endpoints        |
| CLIPS_DIR    | backend/var/clips        | uploaded videos, shared with vision-service   |
| CLIP_MAX_MB  | 300                      | upload size limit                             |
| CORS_ORIGINS | *                        | comma-separated allowed browser origins       |

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
    cors_origins: tuple[str, ...] = ("*",)
    topics: tuple[str, ...] = RELAYED_TOPICS

    @classmethod
    def from_env(cls) -> Settings:
        env_key = os.environ.get("API_KEY")
        settings = cls(
            redis_url=os.environ.get("REDIS_URL", cls.redis_url),
            api_key=env_key or secrets.token_urlsafe(24),
            clips_dir=Path(os.environ.get("CLIPS_DIR", cls.clips_dir)).resolve(),
            clip_max_bytes=int(float(os.environ.get("CLIP_MAX_MB", "300")) * 1024 * 1024),
            cors_origins=tuple(
                o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()
            ),
        )
        if not env_key:
            log.warning(
                "API_KEY not set -- generated one for this process so incident confirm/reject "
                "stay protected without extra setup (X-API-Key: %s). It changes every restart; "
                "set API_KEY yourself for anything beyond local dev.",
                settings.api_key,
            )
        return settings
