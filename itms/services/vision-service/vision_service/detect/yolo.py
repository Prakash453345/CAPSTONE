"""Real detectors: YOLO11 through Ultralytics, or any YOLOv8/11-family model
exported to ONNX and run with ONNX Runtime (no torch).

Both return `Detection`s in the ITMS taxonomy with **low-confidence boxes
kept** (default `conf=0.1`): ByteTrack's second association stage is built
on exactly those boxes, and dropping them at the detector would quietly
turn ByteTrack back into an ordinary tracker.

Class mapping: a stock COCO checkpoint goes through `COCO_TO_VCLASS`; a
fine-tuned model (BMD-45, IDD, UVH-26 ...) goes through its own class names
and `vclass_from_name`. Anything that is not a road user is dropped.

**Several model classes to one ITMS class.** UVH-26 and BMD-45 split a car
five ways (hatchback, sedan, SUV, MUV, van) and a bus three. Such a model
often spreads its confidence over the types -- "0.45 sedan, 0.40
hatchback" -- and taking the best single type would drop a vehicle it is
sure is a car below ByteTrack's 0.5 line; measured on 250 UVH-26 validation
images, the car recall at that line was 0.58 against an AP50 of 0.85. So
for a many-to-one map the scores are summed per ITMS class (capped at 1:
the types are mutually exclusive) *before* the threshold and before NMS,
which also stops one car surviving NMS twice as two types. Classes the
taxonomy drops ("Others") form their own group and win or lose like any
other. A one-to-one map (COCO) is decoded exactly as before.

    det = UltralyticsDetector("yolo11n.pt")          # pip install 'vision-service[yolo]'
    det = OnnxDetector("yolo11n.onnx")               # pip install 'vision-service[onnx]'
    detections = det.detect(frame_bgr)
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

from vision_service.classes import COCO_TO_VCLASS, VClass, vclass_from_name
from vision_service.records import Detection

# The 80 COCO names, in id order -- what an exported model carries when its
# metadata is missing.
COCO_NAMES: tuple[str, ...] = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog",
    "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
    "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball", "kite",
    "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket", "bottle",
    "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich",
    "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote",
    "keyboard", "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book",
    "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush",
)


def class_map_for(names: Sequence[str] | Mapping[int, str]) -> dict[int, VClass]:
    """Model class id -> ITMS class. COCO-named models use the COCO table
    (so 'truck' stays truck, not a name-guess); anything else by name."""
    items: list[tuple[int, str]] = (list(names.items()) if isinstance(names, Mapping)
                                    else list(enumerate(names)))
    if len(items) == 80 and [n for _, n in sorted(items)] == list(COCO_NAMES):
        return dict(COCO_TO_VCLASS)
    out = {}
    for i, n in items:
        vc = vclass_from_name(str(n))
        if vc is not None:
            out[int(i)] = vc
    return out


def merge_matrix(class_map: Mapping[int, VClass], n_classes: int
                 ) -> tuple[list[VClass], np.ndarray] | None:
    """For a many-to-one class map: the ITMS classes in column order, and a
    `(n_classes, K + 1)` 0/1 matrix that sums each ITMS class's model
    classes (the last column collects the classes the taxonomy drops).
    `None` when every ITMS class has at most one model class."""
    groups = sorted(set(class_map.values()), key=lambda v: v.value)
    if len(groups) == len(class_map):
        return None
    m = np.zeros((n_classes, len(groups) + 1), dtype=np.float32)
    for i in range(n_classes):
        m[i, groups.index(class_map[i]) if i in class_map else len(groups)] = 1.0
    return groups, m


def letterbox(frame: np.ndarray, size: int, *, rect: bool, stride: int = 32
              ) -> tuple[np.ndarray, float, tuple[int, int]]:
    """Ultralytics' letterbox: scale to fit `size`, pad with grey -- to a
    square, or (`rect`) only to a multiple of `stride`."""
    import cv2  # noqa: PLC0415

    h, w = frame.shape[:2]
    r = min(size / h, size / w)
    nh, nw = int(round(h * r)), int(round(w * r))
    resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
    if rect:
        ch = nh + (size - nh) % stride
        cw = nw + (size - nw) % stride
    else:
        ch = cw = size
    canvas = np.full((ch, cw, 3), 114, dtype=np.uint8)
    top, left = (ch - nh) // 2, (cw - nw) // 2
    canvas[top:top + nh, left:left + nw] = resized
    return canvas, r, (left, top)


def decode(pred: np.ndarray, class_map: Mapping[int, VClass], *, conf: float, iou: float,
           r: float, pad: tuple[float, float]) -> list[Detection]:
    """Raw YOLOv8/11 head output `(4 + C, N)` (centre-format boxes in the
    letterboxed input) -> `Detection`s in frame pixels, with class-wise NMS
    in the ITMS taxonomy (see the module docstring on many-to-one maps)."""
    pred = pred.T
    cls_scores = pred[:, 4:]
    merged = merge_matrix(class_map, cls_scores.shape[1])
    if merged is None:
        label = cls_scores.argmax(axis=1)
        scores = cls_scores[np.arange(len(label)), label]
        vclass_of = class_map.get
    else:
        groups, m = merged
        g = np.minimum(cls_scores @ m, 1.0)
        label = g.argmax(axis=1)
        scores = g[np.arange(len(label)), label]
        vclass_of = {k: v for k, v in enumerate(groups)}.get  # the last column maps to None
    keep = scores >= conf
    pred, label, scores = pred[keep], label[keep], scores[keep]
    if len(pred) == 0:
        return []
    cx, cy, bw, bh = pred[:, 0], pred[:, 1], pred[:, 2], pred[:, 3]
    boxes = np.stack([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], axis=1)
    dx, dy = pad
    boxes[:, [0, 2]] = (boxes[:, [0, 2]] - dx) / r
    boxes[:, [1, 3]] = (boxes[:, [1, 3]] - dy) / r
    out: list[Detection] = []
    for c in np.unique(label):  # class-wise NMS, like the reference post-processing
        vc = vclass_of(int(c))
        if vc is None:
            continue
        idx = np.nonzero(label == c)[0]
        for k in nms(boxes[idx], scores[idx], iou):
            b = boxes[idx[k]]
            out.append(Detection((float(b[0]), float(b[1]), float(b[2]), float(b[3])),
                                 float(scores[idx[k]]), vc))
    return out


def nms(boxes: np.ndarray, scores: np.ndarray, iou: float) -> np.ndarray:
    """Greedy non-maximum suppression; returns kept indices, best first."""
    order = np.argsort(-scores)
    keep = []
    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    while len(order):
        i = order[0]
        keep.append(i)
        if len(order) == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(boxes[i, 0], boxes[rest, 0])
        yy1 = np.maximum(boxes[i, 1], boxes[rest, 1])
        xx2 = np.minimum(boxes[i, 2], boxes[rest, 2])
        yy2 = np.minimum(boxes[i, 3], boxes[rest, 3])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        ov = inter / np.maximum(areas[i] + areas[rest] - inter, 1e-9)
        order = rest[ov <= iou]
    return np.asarray(keep, dtype=np.int64)


class UltralyticsDetector:
    """A model with a many-to-one class map is run through its raw head and
    `decode` (Ultralytics' own post-processing would threshold and suppress
    per model class); any other through `predict`."""

    def __init__(self, weights: str = "yolo11n.pt", *, conf: float = 0.1, iou: float = 0.6,
                 imgsz: int = 1280, device: str | None = None):
        from ultralytics import YOLO  # noqa: PLC0415 -- optional dependency

        self.model = YOLO(weights)
        self.conf, self.iou, self.imgsz, self.device = conf, iou, imgsz, device
        self.class_map = class_map_for(self.model.names)
        self.name = f"ultralytics:{weights}"
        self._raw = merge_matrix(self.class_map, len(self.model.names)) is not None
        if self._raw:
            self._net = self.model.model.float().eval()
            if device:
                self._net.to(device)
            self._stride = int(max(self._net.stride))

    def _detect_raw(self, frame: np.ndarray) -> list[Detection]:
        import torch  # noqa: PLC0415

        img, r, pad = letterbox(frame, self.imgsz, rect=True, stride=self._stride)
        x = np.ascontiguousarray(img[:, :, ::-1].transpose(2, 0, 1)[None], dtype=np.float32)
        dev = next(self._net.parameters()).device
        with torch.no_grad():
            out = self._net(torch.from_numpy(x / 255.0).to(dev))
        pred = (out[0] if isinstance(out, (list, tuple)) else out)[0].float().cpu().numpy()
        return decode(pred, self.class_map, conf=self.conf, iou=self.iou, r=r, pad=pad)

    def detect(self, frame: np.ndarray) -> list[Detection]:
        if self._raw:
            return self._detect_raw(frame)
        res = self.model.predict(frame, conf=self.conf, iou=self.iou, imgsz=self.imgsz,
                                 device=self.device, verbose=False)[0]
        boxes = res.boxes
        xyxy = boxes.xyxy.cpu().numpy()
        scores = boxes.conf.cpu().numpy()
        cls = boxes.cls.cpu().numpy().astype(int)
        out = []
        for b, s, c in zip(xyxy, scores, cls, strict=True):
            vc = self.class_map.get(int(c))
            if vc is not None:
                out.append(Detection((float(b[0]), float(b[1]), float(b[2]), float(b[3])),
                                     float(s), vc))
        return out


class OnnxDetector:
    """A YOLOv8/YOLO11 ONNX export: input `(1, 3, H, W)` RGB in [0, 1], output
    `(1, 4 + C, N)` with centre-format boxes. Letterboxed like Ultralytics.

    Export with `dynamic=True` if you can: a fixed `S x S` input pads a 16:9
    frame to a square and spends ~45 % of the compute on grey padding; a
    dynamic model gets Ultralytics' minimal "rect" letterbox (padding only
    to a multiple of the stride), which is also what `UltralyticsDetector`
    feeds its PyTorch model -- so the two agree box for box."""

    def __init__(self, path: str, *, conf: float = 0.1, iou: float = 0.6, imgsz: int = 640,
                 names: Sequence[str] | None = None, providers: Sequence[str] | None = None):
        import onnxruntime as ort  # noqa: PLC0415 -- optional dependency

        self.session = ort.InferenceSession(path, providers=list(providers or
                                                                 ["CPUExecutionProvider"]))
        inp = self.session.get_inputs()[0]
        self.input_name = inp.name
        fixed = isinstance(inp.shape[2], int) and isinstance(inp.shape[3], int)
        self.size = int(inp.shape[2]) if fixed else imgsz
        self.rect = not fixed
        self.stride = 32
        meta = self.session.get_modelmeta().custom_metadata_map
        if names is None and "names" in meta:
            import ast  # noqa: PLC0415

            parsed = ast.literal_eval(meta["names"])
            names = [parsed[k] for k in sorted(parsed)] if isinstance(parsed, dict) else parsed
        self.class_map = class_map_for(names or COCO_NAMES)
        self.conf, self.iou = conf, iou
        self.name = f"onnx:{path}"

    def _letterbox(self, frame: np.ndarray) -> tuple[np.ndarray, float, tuple[int, int]]:
        return letterbox(frame, self.size, rect=self.rect, stride=self.stride)

    def detect(self, frame: np.ndarray) -> list[Detection]:
        img, r, pad = self._letterbox(frame)
        x = img[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        pred = self.session.run(None, {self.input_name: x})[0][0]  # (4 + C, N)
        return decode(pred, self.class_map, conf=self.conf, iou=self.iou, r=r, pad=pad)


class VehicleClassFilter:
    """Wraps a detector and drops classes a deployment does not want (e.g.
    `person` when no redaction evidence is being kept)."""

    def __init__(self, inner, keep: set[VClass]):
        self.inner, self.keep = inner, keep
        self.name = getattr(inner, "name", "filtered")

    def detect(self, frame: np.ndarray) -> list[Detection]:
        return [d for d in self.inner.detect(frame) if d.vclass in self.keep]
