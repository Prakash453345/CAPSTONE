"""Hand a live camera's detection to the review inbox.

A camera that flags something does not act on it: the redacted evidence clip
is uploaded to api-service (`POST /v1/clips`), which runs the same analysis
and review flow as an uploaded road video. A person watches it, confirms or
rejects, and only then does the backend dispatch. See `docs/` ADR-006.
"""

from __future__ import annotations

import logging
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np

log = logging.getLogger("vision.review")

ReviewSink = Callable[[str, str, str, Sequence[tuple[float, np.ndarray]]], None]
COOLDOWN_S = 60.0       # one review item per camera a minute, however long it stays flagged


def encode_mp4(frames: Sequence[tuple[float, np.ndarray]], path: Path) -> float:
    """Write `frames` (time, BGR) as an mp4 at their own rate; returns seconds."""
    import cv2  # noqa: PLC0415

    if len(frames) < 2:
        raise ValueError("need at least two frames for a clip")
    span = max(frames[-1][0] - frames[0][0], 1e-3)
    fps = max(1.0, min(30.0, (len(frames) - 1) / span))
    h, w = frames[0][1].shape[:2]
    out = cv2.VideoWriter(str(path), cv2.VideoWriter.fourcc(*"mp4v"), fps, (w, h))
    try:
        for _, f in frames:
            out.write(f)
    finally:
        out.release()
    return len(frames) / fps


def multipart(fields: dict[str, str], file_field: str, filename: str,
              data: bytes) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []
    for k, v in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'
                     .encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; '
                 f'filename="{filename}"\r\nContent-Type: video/mp4\r\n\r\n'.encode()
                 + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def make_review_sink(base_url: str, api_key: str, *,
                     clock: Callable[[], float] = time.monotonic) -> ReviewSink:
    last: dict[str, float] = {}

    def sink(camera_id: str, edge_id: str, kind: str,
             frames: Sequence[tuple[float, np.ndarray]]) -> None:
        now = clock()
        if now - last.get(camera_id, -1e9) < COOLDOWN_S:
            return
        if not edge_id or len(frames) < 2:
            return
        last[camera_id] = now
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / f"{camera_id}-{kind}.mp4"
                encode_mp4(frames, path)
                body, ctype = multipart(
                    {"edge_id": edge_id, "road_name": f"camera {camera_id} ({kind})",
                     "operator": f"camera:{camera_id}"},
                    "file", path.name, path.read_bytes())
            req = urllib.request.Request(
                f"{base_url.rstrip('/')}/v1/clips", data=body, method="POST",
                headers={"Content-Type": ctype, "X-API-Key": api_key})
            with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310
                log.info("camera %s: %s sent for review (%s)", camera_id, kind, r.status)
        except (OSError, urllib.error.URLError, ValueError) as e:
            last.pop(camera_id, None)       # try again at the next flag
            log.error("camera %s: could not send %s for review: %s", camera_id, kind, e)

    return sink
