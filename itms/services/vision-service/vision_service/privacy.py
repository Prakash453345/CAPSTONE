"""Privacy by construction: nothing identifying leaves the vision service
unless an incident needs evidence, and then only redacted and time-limited.

The posture (ARCH §21, ADR-006, and India's Digital Personal Data Protection
Act, 2023 -- purpose limitation and storage limitation):

- **No frame is stored in normal operation.** `EvidenceBuffer` keeps the last
  few seconds per camera in memory, downscaled, and overwrites it.
- **Evidence only with an incident candidate**, and **redacted first**:
  every person box, the rider region of every two-wheeler and bicycle, and
  a number-plate strip of every other vehicle are pixelated before a single
  byte is written. Pixelation (a coarse mosaic), not Gaussian blur: blur is
  partly invertible by deconvolution, a mosaic at this block size is not.
- **Retention is part of the record.** Every stored clip carries its
  delete-after date; `EvidenceStore.purge_expired` enforces it for the local
  store, and object tags carry it to MinIO lifecycle rules.
- **No cross-camera identity.** Track ids are per camera and restart with it.

numpy only for redaction; OpenCV (optional) for encoding clips; `minio`
(optional) for the object store.
"""

from __future__ import annotations

import json
import time
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from vision_service.classes import VClass
from vision_service.records import Detection

_RIDER_CLASSES = frozenset({VClass.MOTORCYCLE, VClass.BICYCLE})


@dataclass(frozen=True)
class RedactionPolicy:
    person: bool = True
    riders: bool = True
    plates: bool = True
    # Share of a two-wheeler box, from the top, that holds the rider. The
    # whole box by default: "the rider sits on top" holds only for a camera
    # level with the road -- from a pole or an overhead view the rider is in
    # the middle of the box (seen on real footage).
    rider_fraction: float = 1.0
    plate_height_fraction: float = 0.3  # bottom share of a vehicle box that holds the plate
    plate_width_fraction: float = 0.7
    min_block_px: int = 8
    block_fraction: float = 0.25       # mosaic block as a share of the region's short side


DEFAULT_POLICY = RedactionPolicy()


def _pixelate(img: np.ndarray, x1: int, y1: int, x2: int, y2: int, block: int) -> None:
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(img.shape[1], x2), min(img.shape[0], y2)
    if x2 <= x1 or y2 <= y1:
        return
    region = img[y1:y2, x1:x2]
    b = max(1, block)
    for yy in range(0, region.shape[0], b):
        for xx in range(0, region.shape[1], b):
            cell = region[yy:yy + b, xx:xx + b]
            cell[...] = cell.reshape(-1, cell.shape[-1]).mean(axis=0) if cell.ndim == 3 \
                else cell.mean()


def redaction_regions(dets: Iterable[Detection], policy: RedactionPolicy | None = None
                      ) -> list[tuple[int, int, int, int]]:
    policy = policy or DEFAULT_POLICY
    out = []
    for d in dets:
        x1, y1, x2, y2 = d.box
        w, h = x2 - x1, y2 - y1
        if d.vclass is VClass.PERSON:
            if policy.person:
                out.append((x1, y1, x2, y2))
        elif d.vclass in _RIDER_CLASSES:
            if policy.riders:
                out.append((x1, y1, x2, y1 + policy.rider_fraction * h))
            if policy.plates:
                out.append((x1, y2 - policy.plate_height_fraction * h, x2, y2))
        elif policy.plates:
            cx = (x1 + x2) / 2.0
            half = policy.plate_width_fraction * w / 2.0
            out.append((cx - half, y2 - policy.plate_height_fraction * h, cx + half, y2))
    return [(int(np.floor(a)), int(np.floor(b)), int(np.ceil(c)), int(np.ceil(d)))
            for a, b, c, d in out]


def redact(frame: np.ndarray, dets: Iterable[Detection],
           policy: RedactionPolicy | None = None) -> np.ndarray:
    """A redacted *copy*; the input frame is never modified."""
    policy = policy or DEFAULT_POLICY
    img = np.array(frame, copy=True)
    for x1, y1, x2, y2 in redaction_regions(dets, policy):
        short = max(1, min(x2 - x1, y2 - y1))
        block = max(policy.min_block_px, int(short * policy.block_fraction))
        _pixelate(img, x1, y1, x2, y2, block)
    return img


@dataclass
class EvidenceBuffer:
    """The last `seconds` of one camera, in memory only, at most `fps`
    frames per second and downscaled by `scale`."""

    seconds: float = 10.0
    fps: float = 2.0
    scale: float = 0.5
    _frames: deque = field(default_factory=deque)
    _last_t: float = -1e9

    def push(self, t: float, frame: np.ndarray, dets: list[Detection]) -> None:
        if t - self._last_t < 1.0 / self.fps:
            return
        self._last_t = t
        step = max(1, int(round(1.0 / self.scale)))
        small = frame[::step, ::step].copy()
        s = 1.0 / step
        small_dets = [Detection(tuple(v * s for v in d.box), d.score, d.vclass)  # type: ignore
                      for d in dets]
        self._frames.append((t, small, small_dets))
        while self._frames and self._frames[0][0] < t - self.seconds:
            self._frames.popleft()

    def redacted_clip(self, policy: RedactionPolicy | None = None) -> list[
        tuple[float, np.ndarray]
    ]:
        return [(t, redact(f, d, policy)) for t, f, d in self._frames]

    def __len__(self) -> int:
        return len(self._frames)


@dataclass
class EvidenceStore:
    """Stores redacted clips. Local directory by default; MinIO when an
    endpoint is given (`vision-service[evidence]`)."""

    root: Path = Path("var/evidence")
    retention_days: int = 30
    minio_endpoint: str | None = None
    minio_bucket: str = "itms-evidence"
    minio_access_key: str | None = None
    minio_secret_key: str | None = None

    def save(self, anomaly_id: str, camera_id: str,
             clip: list[tuple[float, np.ndarray]], meta: dict | None = None) -> str:
        if not clip:
            raise ValueError("empty clip")
        created = time.time()
        record = {
            "anomaly_id": anomaly_id,
            "camera_id": camera_id,
            "frames": len(clip),
            "t_start": clip[0][0],
            "t_end": clip[-1][0],
            "created_unix": created,
            "delete_after_unix": created + self.retention_days * 86400,
            "redacted": True,
            **(meta or {}),
        }
        folder = self.root / anomaly_id / camera_id
        folder.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(folder / "clip.npz", t=np.array([c[0] for c in clip]),
                            frames=np.stack([c[1] for c in clip]))
        (folder / "evidence.json").write_text(json.dumps(record, indent=1))
        if self.minio_endpoint:
            self._upload(folder, anomaly_id, camera_id, record)
            return f"s3://{self.minio_bucket}/{anomaly_id}/{camera_id}/"
        return str(folder)

    def _upload(self, folder: Path, anomaly_id: str, camera_id: str, record: dict) -> None:
        from minio import Minio  # noqa: PLC0415 -- optional dependency
        from minio.commonconfig import Tags  # noqa: PLC0415

        client = Minio(self.minio_endpoint, access_key=self.minio_access_key,
                       secret_key=self.minio_secret_key, secure=False)
        if not client.bucket_exists(self.minio_bucket):
            client.make_bucket(self.minio_bucket)
        tags = Tags(for_object=True)
        tags["retention_days"] = str(self.retention_days)
        tags["redacted"] = "true"
        for f in folder.iterdir():
            client.fput_object(self.minio_bucket, f"{anomaly_id}/{camera_id}/{f.name}", str(f),
                               tags=tags)

    def purge_expired(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        n = 0
        for meta in self.root.glob("*/*/evidence.json"):
            rec = json.loads(meta.read_text())
            if rec.get("delete_after_unix", float("inf")) <= now:
                for f in meta.parent.iterdir():
                    f.unlink()
                meta.parent.rmdir()
                try:
                    meta.parent.parent.rmdir()  # the anomaly folder, once its last camera is gone
                except OSError:
                    pass  # another camera's clip for the same anomaly is still in date
                n += 1
        return n
