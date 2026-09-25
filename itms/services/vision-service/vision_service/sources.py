"""Frame sources for real cameras: video files and RTSP streams.

`VideoSource` yields `(t, frame)` at the requested processing rate,
dropping frames rather than falling behind -- a traffic controller wants
the newest frame, not every frame. For files, `t` is the frame's media
time, so a recorded video replays deterministically; for live streams it
is wall-clock seconds since the source opened.

A live stream that drops is reopened with exponential backoff (1 s ... 30 s)
and the gap is simply a gap: `CameraHealth` sees no frames and marks the
camera FAILED after two seconds, which is what should drive confidence to
zero, rather than the source pretending nothing happened.

`realtime=True` paces a *file* at its own frame rate, so a recording fed to
the running service behaves like the camera it came from -- without it a
file is decoded as fast as the CPU allows, and a service that stamps frames
with its own clock would see vehicles move at several times their speed.

**Credentials.** An RTSP URL usually carries a user and password. The URI
may name environment variables (`rtsp://${CAM_USER}:${CAM_PASS}@10.0.0.12/s1`)
so the camera registry never has to hold a secret, and every log line and
error shows the URI with its user-info masked.
"""

from __future__ import annotations

import logging
import os
import re
import time
from collections.abc import Iterator

import numpy as np

log = logging.getLogger("vision.sources")

_USERINFO = re.compile(r"^([a-z][a-z0-9+.-]*://)[^/@]*@", re.IGNORECASE)


def mask_uri(uri: str) -> str:
    """`uri` with any `user:password@` replaced by `***@`, for logs."""
    return _USERINFO.sub(r"\1***@", uri)


class VideoSource:
    def __init__(self, uri: str, *, fps: float = 5.0, max_backoff_s: float = 30.0,
                 realtime: bool = False):
        self.uri = os.path.expandvars(uri)
        self.shown = mask_uri(uri)  # before expansion: never a secret in a log
        self.fps = fps
        self.live = self.uri.startswith(("rtsp://", "rtsps://", "http://", "https://"))
        self.realtime = realtime
        self.max_backoff_s = max_backoff_s
        self._cap = None
        self._t0 = time.monotonic()
        self.width = 0
        self.height = 0
        self.native_fps = 0.0

    def _open(self):
        import cv2  # noqa: PLC0415 -- optional dependency (vision-service[video])

        cap = cv2.VideoCapture(self.uri)
        if not cap.isOpened():
            raise OSError(f"cannot open {self.shown}")
        self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.native_fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
        return cap

    def frames(self) -> Iterator[tuple[float, np.ndarray]]:
        import cv2  # noqa: PLC0415

        backoff = 1.0
        next_t = 0.0
        index = 0
        while True:
            if self._cap is None:
                try:
                    self._cap = self._open()
                    backoff = 1.0
                except OSError as exc:
                    if not self.live:
                        raise
                    log.warning("%s -- retrying in %.0fs", exc, backoff)
                    time.sleep(backoff)
                    backoff = min(self.max_backoff_s, backoff * 2)
                    continue
            cap = self._cap
            assert cap is not None
            ok, frame = cap.read()
            if not ok:
                if not self.live:
                    return
                log.warning("stream %s dropped; reopening", self.shown)
                cap.release()
                self._cap = None
                continue
            if self.live:
                t = time.monotonic() - self._t0
            else:
                t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
                if t <= 0:
                    t = index / max(self.native_fps, 1e-6)
            index += 1
            if t + 1e-6 < next_t:
                continue  # sub-sample to the processing rate
            next_t = t + 1.0 / self.fps
            if self.realtime and not self.live:
                ahead = t - (time.monotonic() - self._t0)
                if ahead > 0:
                    time.sleep(ahead)  # a recording plays at the speed it was filmed
            yield t, frame

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
