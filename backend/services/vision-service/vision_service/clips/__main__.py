"""`python -m vision_service.clips`: run the clip worker (see worker.py)."""

from __future__ import annotations

import logging
import os

from vision_service.clips.worker import run_forever

logging.basicConfig(level=logging.INFO, format="%(asctime)s vision-clips %(message)s")

if __name__ == "__main__":
    try:
        run_forever(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    except KeyboardInterrupt:
        pass
