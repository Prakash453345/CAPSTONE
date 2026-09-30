"""Turns what a camera *could* see (`FilmedObjects`) into what a detector
*reports* (`Detection`s) -- misses, mislabels, jittered boxes, and things
that are not there.

Every number in a preset is an assumption about a detector nobody has run on
Vijayawada footage yet. They are set from published behaviour, not tuned to
make results look good, and the experiments sweep across presets precisely
because the true values are unknown. `vision_service/eval/mot.py` is how a
real annotated video replaces them.

Mechanisms, each chosen because leaving it out would flatter the tracker or
the incident rules:

- **Recall** = class base recall x a visibility curve x a size curve. A
  motorcycle 40 % hidden behind a bus, 14 pixels tall at 90 m, is usually
  missed; the same motorcycle unoccluded at 20 m is not.
- **Bursty misses.** Each object carries a two-state (Gilbert-Elliott)
  Markov chain. In the bad state -- glare, a passing truck, a pose the
  model handles poorly -- recall collapses and stays collapsed for several
  frames. Independent per-frame misses would let a tracker bridge every gap
  and make the pipeline look better than it will be.
- **Class confusion** with per-object persistence: a detector that calls one
  particular auto-rickshaw a car tends to keep calling it a car. The COCO
  preset maps most auto-rickshaws to car or motorcycle, because COCO has no
  such class.
- **Box jitter** proportional to box size, and lower confidence scores for
  partly hidden objects -- which is what ByteTrack's second, low-score
  association stage exists to use.
- **False positives**, two kinds: scattered one-frame ghosts, and
  **persistent hotspots** -- a billboard, a parked cart, a shadow that the
  detector calls a vehicle every few frames at the same spot. A hotspot on a
  lane is indistinguishable from a stalled vehicle by position alone, which
  is exactly the false-alarm case the incident rules have to survive.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field, replace

import numpy as np
from itms_geo.camera import PinholeCamera
from itms_geo.coverage import LaneCoverage
from itms_geo.road import Lane

from vision_service.classes import VClass
from vision_service.records import Detection
from vision_service.simcam.render import FilmedObjects


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


@dataclass(frozen=True)
class ErrorPreset:
    name: str
    base_recall: dict[VClass, float]
    size_h50_px: float          # box height (native px) at which recall halves
    vis_50: float               # visible fraction at which recall halves
    jitter_frac: float          # box jitter sigma as a fraction of box size
    fp_per_frame: float         # scattered ghost false positives (Poisson mean)
    fp_hotspots: int            # persistent false-positive spots per camera
    hotspot_rate: float         # per-frame firing probability of a hotspot
    confusion: dict[VClass, dict[VClass, float]] = field(default_factory=dict)
    p_good_to_bad: float = 0.0  # Gilbert-Elliott transition probabilities per frame
    p_bad_to_good: float = 1.0
    bad_recall_factor: float = 1.0
    confusion_flicker: float = 0.05  # per-frame chance a sticky label is re-drawn
    size_h50_by_class: dict[VClass, float] = field(default_factory=dict)  # overrides size_h50_px


_ALL = tuple(VClass)

PRESETS: dict[str, ErrorPreset] = {
    "ideal": ErrorPreset(
        name="ideal",
        base_recall=dict.fromkeys(_ALL, 1.0),
        size_h50_px=0.0,
        vis_50=0.05,
        jitter_frac=0.0,
        fp_per_frame=0.0,
        fp_hotspots=0,
        hotspot_rate=0.0,
    ),
    # An in-domain detector: YOLO11 fine-tuned on fixed Indian CCTV (BMD-45
    # class set), daylight.
    "finetuned_day": ErrorPreset(
        name="finetuned_day",
        base_recall={
            VClass.CAR: 0.97, VClass.BUS: 0.98, VClass.TRUCK: 0.97,
            VClass.AUTO_RICKSHAW: 0.94, VClass.MOTORCYCLE: 0.92,
            VClass.BICYCLE: 0.85, VClass.PERSON: 0.85,
        },
        size_h50_px=14.0,
        vis_50=0.35,
        jitter_frac=0.04,
        fp_per_frame=0.3,
        fp_hotspots=1,
        hotspot_rate=0.4,
        confusion={
            VClass.AUTO_RICKSHAW: {VClass.CAR: 0.04},
            VClass.MOTORCYCLE: {VClass.BICYCLE: 0.03},
            VClass.BUS: {VClass.TRUCK: 0.03},
        },
        p_good_to_bad=0.02,
        p_bad_to_good=0.30,
        bad_recall_factor=0.30,
    ),
    # A stock COCO-pretrained YOLO11 on Indian CCTV: no auto-rickshaw class,
    # weaker on small two-wheelers, more ghosts. The BMD-45 paper's own
    # cross-domain result (UA-DETRAC-trained: 33.6% mAP vs 83.8% in-domain)
    # is the reason this preset is materially worse, not a tuning choice.
    "coco_pretrained": ErrorPreset(
        name="coco_pretrained",
        base_recall={
            VClass.CAR: 0.92, VClass.BUS: 0.92, VClass.TRUCK: 0.88,
            VClass.AUTO_RICKSHAW: 0.85, VClass.MOTORCYCLE: 0.82,
            VClass.BICYCLE: 0.65, VClass.PERSON: 0.8,
        },
        size_h50_px=18.0,
        vis_50=0.45,
        jitter_frac=0.07,
        fp_per_frame=0.8,
        fp_hotspots=2,
        hotspot_rate=0.5,
        confusion={
            VClass.AUTO_RICKSHAW: {VClass.CAR: 0.55, VClass.MOTORCYCLE: 0.15},
            VClass.MOTORCYCLE: {VClass.BICYCLE: 0.08},
            VClass.BUS: {VClass.TRUCK: 0.20},
            VClass.CAR: {VClass.TRUCK: 0.04},
        },
        p_good_to_bad=0.04,
        p_bad_to_good=0.25,
        bad_recall_factor=0.25,
    ),
}

PRESETS["night_rain"] = replace(
    PRESETS["finetuned_day"],
    name="night_rain",
    base_recall={k: v * 0.82 for k, v in PRESETS["finetuned_day"].base_recall.items()},
    size_h50_px=24.0,
    vis_50=0.5,
    jitter_frac=0.10,
    fp_per_frame=1.0,
    fp_hotspots=2,
    hotspot_rate=0.5,
    p_good_to_bad=0.06,
    p_bad_to_good=0.20,
    bad_recall_factor=0.2,
)

# ---- measured detectors -------------------------------------------------------------
#
# Fitted by `scripts/m8_simcam_calibrate.py` to real detectors scored on 250
# labelled UVH-26 validation frames (Bengaluru Safe City CCTV, 1080p) at
# ByteTrack's 0.5 line: recall per class and its size curve by maximum
# likelihood, confusion from what each found vehicle was called
# (`baselines/2026-09-26_m8_measured_detectors/simcam_fit.json`). A still
# image cannot measure bursts, false positives or person recall, so those
# stay as the preset each starts from. The labels do not say how hidden a
# vehicle was, so occlusion misses are inside `base_recall` and SimCam's
# visibility curve applies on top: a little pessimistic, by construction.
_C, _A, _M, _B, _T, _BI, _P = (VClass.CAR, VClass.AUTO_RICKSHAW, VClass.MOTORCYCLE, VClass.BUS,
                               VClass.TRUCK, VClass.BICYCLE, VClass.PERSON)

# IISc's UVH-26 YOLO11-S, ITMS-class scores merged, 640 px input (56 ms a frame on a laptop CPU)
PRESETS["uvh26_640"] = replace(
    PRESETS["finetuned_day"],
    name="uvh26_640",
    base_recall={_C: 0.92, _A: 0.864, _M: 0.78, _B: 0.73, _T: 0.702, _BI: 0.464, _P: 0.85},
    size_h50_px=55.0,
    size_h50_by_class={_C: 53.0, _A: 48.0, _M: 58.75, _B: 55.0, _T: 86.0, _BI: 55.0},
    confusion={_A: {_C: 0.015, _M: 0.003, _T: 0.015}, _BI: {_M: 0.429}, _B: {_T: 0.052},
               _C: {_A: 0.002, _B: 0.003, _T: 0.002}, _M: {_C: 0.001},
               _T: {_A: 0.025, _B: 0.006, _C: 0.025}},
)
# the same model at 1280 px input (272 ms a frame on that CPU: a GPU's job for 19 cameras)
PRESETS["uvh26_1280"] = replace(
    PRESETS["finetuned_day"],
    name="uvh26_1280",
    base_recall={_C: 0.88, _A: 0.794, _M: 0.758, _B: 0.54, _T: 0.608, _BI: 0.532, _P: 0.85},
    size_h50_px=5.0,
    size_h50_by_class={_C: 31.0, _A: 5.0, _M: 5.0, _B: 5.0, _T: 51.25, _BI: 5.0},
    confusion={_A: {_B: 0.003, _C: 0.022, _M: 0.003, _T: 0.015}, _BI: {_M: 0.353},
               _B: {_T: 0.021}, _C: {_A: 0.003, _B: 0.003, _T: 0.008}, _M: {_A: 0.001, _C: 0.001},
               _T: {_A: 0.019, _B: 0.019, _C: 0.025}},
)
# The adopted fine-tune (notebook version 2; `baselines/2026-09-27_m8_finetune_v2/`):
# IISc's model trained further on 3,000 UVH-26 frames to the six ITMS types, in full precision.
# Fitted the same way; bus and bicycle (under 100 boxes each) share the pooled size curve. The
# fit undershoots the 20-40 px boxes (measured 0.44, fitted 0.26 at 640 px; 0.63 and 0.43 at
# 960, 63 boxes), so for distant vehicles these presets are pessimistic.
# 640 px input, 51 ms a frame on the laptop's CPU
PRESETS["itms6_640"] = replace(
    PRESETS["finetuned_day"],
    name="itms6_640",
    base_recall={_C: 0.94, _A: 0.866, _M: 0.804, _B: 0.792, _T: 0.79, _BI: 0.708, _P: 0.85},
    size_h50_px=43.75,
    size_h50_by_class={_C: 42.5, _A: 40.75, _M: 42.75, _B: 43.75, _T: 66.0, _BI: 43.75},
    confusion={_A: {_B: 0.002, _C: 0.007, _M: 0.005, _T: 0.012}, _BI: {_M: 0.364},
               _B: {_T: 0.108}, _C: {_A: 0.005, _B: 0.006, _T: 0.002},
               _T: {_A: 0.025, _B: 0.02, _C: 0.025}},
)
# the same recipe trained at 960 px input (136 ms a frame on that CPU)
PRESETS["itms6_960"] = replace(
    PRESETS["finetuned_day"],
    name="itms6_960",
    base_recall={_C: 0.956, _A: 0.892, _M: 0.802, _B: 0.786, _T: 0.78, _BI: 0.70, _P: 0.85},
    size_h50_px=37.5,
    size_h50_by_class={_C: 38.5, _A: 37.25, _M: 29.75, _B: 37.5, _T: 57.25, _BI: 37.5},
    confusion={_A: {_B: 0.005, _C: 0.014, _M: 0.002, _T: 0.009}, _BI: {_M: 0.227},
               _B: {_T: 0.076}, _C: {_A: 0.005, _B: 0.005, _T: 0.002},
               _T: {_A: 0.034, _B: 0.02, _C: 0.034}},
)
# stock COCO YOLO11-S, 640 px: no auto-rickshaw class, so an auto it finds is always another type
PRESETS["stock_640"] = replace(
    PRESETS["coco_pretrained"],
    name="stock_640",
    base_recall={_C: 0.86, _A: 0.596, _M: 0.33, _B: 0.718, _T: 0.678, _BI: 0.306, _P: 0.8},
    size_h50_px=88.5,
    size_h50_by_class={_C: 63.75, _A: 209.25, _M: 148.25, _B: 88.5, _T: 162.5, _BI: 88.5},
    confusion={_A: {_B: 0.122, _C: 0.4, _M: 0.011, _T: 0.467}, _B: {_T: 0.222}, _C: {_T: 0.042},
               _M: {_BI: 0.015, _C: 0.015}, _T: {_B: 0.087, _C: 0.035, _M: 0.009}},
)


@dataclass
class _Hotspot:
    box_ground_xy: np.ndarray
    vclass: VClass
    length: float
    width: float
    height: float


_PRUNE_EVERY = 3000  # frames: 10 minutes at 5 fps


class PerceptionErrorModel:
    """Stateful per camera: the Markov chains, sticky labels and hotspots
    persist across frames. One instance per (camera, run); deterministic for
    a given seed."""

    def __init__(self, preset: ErrorPreset | str, *, seed: int = 0, camera_id: str = ""):
        self.preset = PRESETS[preset] if isinstance(preset, str) else preset
        # Stable per-camera stream: the same seed and camera always produce
        # the same errors, independent of how many other cameras exist.
        # (crc32, not hash(): str hashing is salted per process, which would
        # make "the same seed" mean different errors on every run.)
        mix = zlib.crc32(camera_id.encode()) if camera_id else 0
        self.rng = np.random.default_rng([seed, mix])
        self._bad: dict[str, bool] = {}
        self._label: dict[str, VClass] = {}
        self._seen: dict[str, int] = {}  # vehicle -> last frame it was filmed
        self._frame = 0
        self._hotspots: list[_Hotspot] | None = None

    # ---- hotspots ----------------------------------------------------

    def place_hotspots(
        self, lanes: list[Lane], coverage: dict[str, LaneCoverage]
    ) -> None:
        """Pick this camera's persistent false-positive spots: just off the
        kerb of a covered lane, where roadside clutter lives, close enough
        that the lane locator's tolerance can put one on the lane."""
        self._hotspots = []
        cand = [ln for ln in lanes if ln.lane_id in coverage]
        for _ in range(self.preset.fp_hotspots):
            for _attempt in range(20):
                if not cand:
                    break
                lane = cand[int(self.rng.integers(len(cand)))]
                cov = coverage[lane.lane_id]
                s_ok = cov.s[cov.covered]
                if len(s_ok) == 0:
                    continue
                s = float(self.rng.choice(s_ok))
                side = 1.0 if self.rng.random() < 0.5 else -1.0
                lateral = side * (lane.width / 2.0 + float(self.rng.uniform(0.2, 0.9)))
                xy = lane.point_at(s, lateral)[0]
                # off every carriageway lane, not inside the neighbouring one
                if any(abs(float(o.project(xy[None])[1][0])) < o.width / 2.0 for o in cand):
                    continue
                vc = VClass.TRUCK if self.rng.random() < 0.4 else VClass.CAR
                self._hotspots.append(_Hotspot(xy, vc, 3.0, 1.6, 2.2))
                break

    # ---- per frame ------------------------------------------------------

    def _recall(self, filmed: FilmedObjects) -> np.ndarray:
        p = self.preset
        base = np.array([p.base_recall.get(c, 0.9) for c in filmed.vclass])
        h = filmed.boxes[:, 3] - filmed.boxes[:, 1]
        h50 = np.array([p.size_h50_by_class.get(c, p.size_h50_px) for c in filmed.vclass],
                       dtype=np.float64).reshape(len(h))
        size = np.where(h50 > 0, _sigmoid((h - h50) / np.maximum(1.0, 0.25 * h50)), 1.0)
        vis_eff = filmed.visible * filmed.in_frame
        vis = _sigmoid((vis_eff - p.vis_50) / 0.08)
        return base * size * vis

    def _label_for(self, truth_id: str, true_class: VClass) -> VClass:
        p = self.preset
        cur = self._label.get(truth_id)
        if cur is not None and self.rng.random() >= p.confusion_flicker:
            return cur
        options = p.confusion.get(true_class, {})
        r = self.rng.random()
        acc = 0.0
        label = true_class
        for other, prob in options.items():
            acc += prob
            if r < acc:
                label = other
                break
        self._label[truth_id] = label
        return label

    def detect(self, cam: PinholeCamera, filmed: FilmedObjects) -> list[Detection]:
        p = self.preset
        out: list[Detection] = []
        n = len(filmed)
        if n:
            recall = self._recall(filmed)
            bad = np.array([self._bad.get(vid, False) for vid in filmed.ids])
            r = self.rng.random(n)
            bad = np.where(bad, r >= p.p_bad_to_good, r < p.p_good_to_bad)
            for vid, b in zip(filmed.ids, bad, strict=True):
                self._bad[vid] = bool(b)
                self._seen[vid] = self._frame
            pr = recall * np.where(bad, p.bad_recall_factor, 1.0)
            hit = self.rng.random(n) < pr
            vis_eff = filmed.visible * filmed.in_frame
            # confidence: high for clear views, lower for partly hidden ones
            scores = np.clip(0.35 + 0.6 * vis_eff + self.rng.normal(0, 0.08, n), 0.05, 0.99)
            boxes = filmed.boxes.copy()
            if p.jitter_frac > 0:
                w = boxes[:, 2] - boxes[:, 0]
                h = boxes[:, 3] - boxes[:, 1]
                boxes += self.rng.normal(0.0, 1.0, (n, 4)) * p.jitter_frac * np.stack(
                    [w, h, w, h], axis=1)
                boxes[:, 2] = np.maximum(boxes[:, 2], boxes[:, 0] + 1.0)
                boxes[:, 3] = np.maximum(boxes[:, 3], boxes[:, 1] + 1.0)
            for i in np.nonzero(hit)[0]:
                vid = filmed.ids[i]
                true_class = filmed.vclass[i]
                label = self._label_for(vid, true_class) if true_class in p.confusion \
                    else true_class
                out.append(Detection(
                    box=(float(boxes[i, 0]), float(boxes[i, 1]), float(boxes[i, 2]),
                         float(boxes[i, 3])),
                    score=float(scores[i]),
                    vclass=label,
                    truth_id=vid,
                ))
        out.extend(self._ghosts(cam))
        self._frame += 1
        if self._frame % _PRUNE_EVERY == 0:
            self._forget_departed()
        return out

    def _forget_departed(self) -> None:
        """Drop the per-vehicle state of vehicles long gone from the frame --
        a service filming for days would otherwise keep every vehicle it
        ever saw."""
        cutoff = self._frame - _PRUNE_EVERY
        gone = [vid for vid, f in self._seen.items() if f < cutoff]
        for vid in gone:
            del self._seen[vid]
            self._bad.pop(vid, None)
            self._label.pop(vid, None)

    def _ghost_box(self, cam: PinholeCamera, xy: np.ndarray, length: float, width: float,
                   height: float) -> tuple[float, float, float, float] | None:
        th = np.radians(cam.heading_deg)
        fwd = np.array([np.sin(th), np.cos(th)])
        right = np.array([np.cos(th), -np.sin(th)])
        pts = []
        for a in (-1, 1):
            for b in (-1, 1):
                g = xy + a * fwd * length / 2 + b * right * width / 2
                pts.append([g[0], g[1], 0.0])
                pts.append([g[0], g[1], height])
        uv, depth = cam.project_points(np.asarray(pts))
        if (depth <= 0.5).any():
            return None
        x1, y1 = np.clip(uv.min(axis=0), 0, [cam.width_px, cam.height_px])
        x2, y2 = np.clip(uv.max(axis=0), 0, [cam.width_px, cam.height_px])
        if x2 - x1 < 3 or y2 - y1 < 3:
            return None
        return float(x1), float(y1), float(x2), float(y2)

    def _ghosts(self, cam: PinholeCamera) -> list[Detection]:
        p = self.preset
        out: list[Detection] = []
        for hs in self._hotspots or []:
            if self.rng.random() < p.hotspot_rate:
                box = self._ghost_box(cam, hs.box_ground_xy, hs.length, hs.width, hs.height)
                if box is not None:
                    out.append(Detection(box, float(self.rng.uniform(0.4, 0.8)), hs.vclass))
        n = int(self.rng.poisson(p.fp_per_frame)) if p.fp_per_frame > 0 else 0
        for _ in range(n):
            # a ghost somewhere below the horizon, vehicle-sized for its row
            v_top = max(0.0, cam.horizon_row() + 20.0)
            v = float(self.rng.uniform(v_top, cam.height_px - 1))
            u = float(self.rng.uniform(0, cam.width_px - 1))
            frac = (v - v_top) / max(1.0, cam.height_px - v_top)
            h = 8.0 + 120.0 * frac
            w = h * float(self.rng.uniform(0.6, 1.6))
            box = (u - w / 2, v - h, u + w / 2, v)
            out.append(
                Detection(
                    tuple(float(np.clip(b, 0, lim)) for b, lim in  # type: ignore[arg-type]
                          zip(box, (cam.width_px, cam.height_px) * 2, strict=True)),
                    float(self.rng.uniform(0.1, 0.55)),
                    VClass.CAR if self.rng.random() < 0.6 else VClass.MOTORCYCLE,
                )
            )
        return out
