"""M8 real-footage smoke test: a real detector on real pixels, through the
same tracker, ground plane and estimator that SimCam feeds.

SimCam decides the numbers in the M8 gates; this script answers a different
question -- does the pipeline run end to end on actual video, with an actual
YOLO11 model, at a usable speed, and do its outputs look physically sane?
It is a smoke test, not an accuracy evaluation: the public clips it was run
on are short, sparse, and not Indian mixed traffic (see the M8 baseline
README for what an accuracy evaluation needs).

What it does, per clip:

1. runs the detector on every frame (Ultralytics YOLO11, low-confidence
   boxes kept for ByteTrack), timing it;
2. optionally exports the same weights to ONNX and checks that
   `OnnxDetector` -- our own letterbox + decode + NMS, no torch -- agrees
   with Ultralytics box for box;
3. tracks in the image with ByteTrack (fragmentation, track lengths);
4. with `--marks`: calibrates the camera from the lane markings visible in
   the frame (`itms_geo.lanecal`), builds a straight road for it, and runs
   the full `VisionSystem` -- ground tracking, lane assignment, speeds, a
   count line, link state, camera health;
5. writes a summary JSON, an annotated contact sheet, and (with
   `--redact-demo`) one privacy-redacted evidence frame.

    python scripts/m8_real_video_smoke.py --video highway.avi --weights yolo11n.pt \\
        --marks scripts/m8_video_marks/highway.json --fleet-scale --out results/m8_video/highway

Needs `pip install -e 'services/vision-service[yolo,onnx]'`.
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from itms_geo import HomographyCamera
from itms_geo.homography import apply_homography
from itms_geo.lanecal import calibrate_from_lane_marks
from itms_geo.road import Connection, Lane, RoadNetwork
from vision_service.cameras import CameraRig, CameraSpec
from vision_service.classes import VClass
from vision_service.eval.metrics import match_boxes
from vision_service.incidents.rules import StaticSignalState
from vision_service.pipeline import VisionSystem
from vision_service.privacy import EvidenceBuffer
from vision_service.records import Detection
from vision_service.track import ByteTrackConfig, ByteTracker


def read_frames(path: str) -> tuple[list[np.ndarray], float]:
    import cv2  # noqa: PLC0415

    cap = cv2.VideoCapture(path)
    fps = float(cap.get(cv2.CAP_PROP_FPS)) or 25.0
    frames = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    return frames, fps


def run_detector(det, frames: list[np.ndarray]) -> tuple[list[list[Detection]], float]:
    det.detect(frames[0])  # warm-up (model load, first-call allocations)
    out, t0 = [], time.perf_counter()
    for f in frames:
        out.append(det.detect(f))
    return out, (time.perf_counter() - t0) / len(frames)


def onnx_parity(a: list[list[Detection]], b: list[list[Detection]], conf: float = 0.25) -> dict:
    """Box-for-box agreement of two detectors on the same frames."""
    matched = only_a = only_b = 0
    dconf, iou = [], []
    for da, db in zip(a, b, strict=True):
        da = [d for d in da if d.score >= conf]
        db = [d for d in db if d.score >= conf]
        if not da or not db:
            only_a += len(da)
            only_b += len(db)
            continue
        ba = np.array([d.box for d in da])
        bb = np.array([d.box for d in db])
        pairs, _, _ = match_boxes(ba, bb, 0.5)
        for i, j in pairs:
            matched += 1
            dconf.append(abs(da[i].score - db[j].score))
            x1 = max(ba[i, 0], bb[j, 0])
            y1 = max(ba[i, 1], bb[j, 1])
            x2 = min(ba[i, 2], bb[j, 2])
            y2 = min(ba[i, 3], bb[j, 3])
            inter = max(0, x2 - x1) * max(0, y2 - y1)
            area = lambda q: (q[2] - q[0]) * (q[3] - q[1])  # noqa: E731
            iou.append(inter / (area(ba[i]) + area(bb[j]) - inter))
        only_a += len(da) - len(pairs)
        only_b += len(db) - len(pairs)
    total = matched + max(only_a, only_b)
    return {"conf_threshold": conf, "matched": matched, "only_ultralytics": only_a,
            "only_onnx": only_b, "agreement": matched / total if total else 1.0,
            "mean_abs_dconf": float(np.mean(dconf)) if dconf else None,
            "mean_iou": float(np.mean(iou)) if iou else None}


def image_tracking(dets: list[list[Detection]], fps: float) -> tuple[dict, list[list]]:
    tr = ByteTracker(ByteTrackConfig(fps=fps))
    per_frame, lengths, classes = [], Counter(), {}
    centres: dict[int, list[np.ndarray]] = defaultdict(list)
    widths: dict[int, list[float]] = defaultdict(list)
    for d in dets:
        tracks = tr.update(d)
        per_frame.append(tracks)
        for t in tracks:
            lengths[t.track_id] += 1
            classes[t.track_id] = t.vclass
            if not t.coasting:
                centres[t.track_id].append((t.box[:2] + t.box[2:]) / 2)
                widths[t.track_id].append(float(t.box[2] - t.box[0]))
    secs = [n / fps for n in lengths.values()]
    # parked cars and the like: long-lived tracks that never move more than a
    # fraction of their own width -- what the estimator's furniture/clutter
    # logic has to keep out of the queue
    stationary = [tid for tid, c in centres.items() if len(c) >= 10 * fps and
                  np.ptp(np.array(c), axis=0).max() < 0.25 * np.median(widths[tid])]
    return {
        "tracks": len(lengths),
        "tracks_by_class": dict(Counter(c.value for c in classes.values())),
        "track_seconds_median": st.median(secs) if secs else 0.0,
        "tracks_under_1s": sum(s < 1.0 for s in secs),
        "tracks_over_10s": sum(s >= 10.0 for s in secs),
        "stationary_tracks": len(stationary),
    }, per_frame


def pixel_health(frames: list[np.ndarray], fps: float) -> dict:
    """The camera-health pixel checks on real frames: no alarms on the clean
    clip, and how fast each tampering / failure is caught when it is applied
    to the second half of the same clip."""
    import cv2  # noqa: PLC0415
    from vision_service.health import PixelHealthMonitor  # noqa: PLC0415

    def run(seq):
        mon, out = PixelHealthMonitor(), []
        for f in seq:
            mon.update(f)
            out.append(mon.assess()[0].value)
        return out

    clean = run(frames)
    half = len(frames) // 2
    faults = {
        "blur": lambda f: cv2.GaussianBlur(f, (0, 0), 6),
        "lens_covered": lambda f: np.full_like(f, 18),
        "spray_or_fog": lambda f: cv2.addWeighted(cv2.GaussianBlur(f, (0, 0), 4), 0.4,
                                                  np.full_like(f, 200), 0.6, 0),
        "frozen": None,
        "night_underexposed": lambda f: (f * 0.08).astype(np.uint8),
    }
    caught = {}
    for name, fn in faults.items():
        if fn is None:
            seq = frames[:half] + [frames[half]] * (len(frames) - half)
        else:
            seq = frames[:half] + [fn(f) for f in frames[half:]]
        st_ = run(seq)
        after = [k for k, s in enumerate(st_[half:]) if s != "OK"]
        caught[name] = {"detected": bool(after),
                        "latency_s": round(after[0] / fps, 2) if after else None,
                        "status": st_[-1]}
    return {"clean_non_ok_frames": sum(s != "OK" for s in clean[50:]),
            "clean_frames": len(clean) - 50, "faults_on_second_half": caught}


# ---- ground plane -----------------------------------------------------------------------


def calibrate(marks: dict) -> tuple[np.ndarray, dict]:
    cal = calibrate_from_lane_marks(
        {float(k): v for k, v in marks["lines"].items()}, marks["dashes"],
        float(marks["dash_line_y"]), tuple(marks["image_size"]),
        crossbars=marks.get("crossbars", ()), dash_period_m=marks.get("dash_period_m", 1.0))
    return cal.h_ground_to_image, {"rms_m": cal.rms_m, "max_m": cal.max_m,
                                   "shear_fixed": cal.shear_fixed,
                                   "dash_period_m": cal.dash_period_m}


def box_length_units(h: np.ndarray, d: Detection) -> float:
    """Ground x-extent of a box's edge midpoints -- a vehicle's length when
    the camera looks down on the road more than along it."""
    x1, y1, x2, y2 = d.box
    mids = np.array([[x1, (y1 + y2) / 2], [x2, (y1 + y2) / 2], [(x1 + x2) / 2, y1],
                     [(x1 + x2) / 2, y2]])
    g = apply_homography(np.linalg.inv(h), mids)
    return float(g[:, 0].max() - g[:, 0].min())


def fleet_scale(h_unit: np.ndarray, dets: list[list[Detection]], size: tuple[int, int],
                car_length_m: float) -> tuple[float, dict]:
    """Metres per ground x unit from the median car: when the dash period is
    unknown and there is no crossbar, the fleet is the ruler."""
    w, hh = size
    lens = []
    for frame in dets:
        for d in frame:
            x1, y1, x2, y2 = d.box
            if d.vclass is VClass.CAR and d.score >= 0.5 and x1 > 3 and y1 > 3 \
                    and x2 < w - 6 and y2 < hh - 3:
                lens.append(box_length_units(h_unit, d))
    if len(lens) < 10:
        raise SystemExit(f"--fleet-scale needs >= 10 clean car boxes, got {len(lens)}")
    med = float(np.median(lens))
    q1, q3 = np.percentile(lens, [25, 75])
    return car_length_m / med, {"car_boxes": len(lens), "median_units": med,
                                "iqr_rel": float((q3 - q1) / med),
                                "assumed_car_length_m": car_length_m}


def straight_road(lines: dict, x0: float, x1: float, direction: int = +1) -> RoadNetwork:
    """The lanes between the calibrated lane lines, ending at a notional
    signal `J` just past the frame so the estimator has links to fill."""
    ys = sorted(float(k) for k in lines)  # right-most (most negative y) first
    lanes, conns, ids = {}, [], []
    for i in range(len(ys) - 1):
        yc, width = (ys[i] + ys[i + 1]) / 2, ys[i + 1] - ys[i]
        lid, oid = f"road_{i}", f"out_{i}"
        shape = np.array([[x0, yc], [x1, yc]])[:: direction]
        lanes[lid] = Lane(lid, "road", i, x1 - x0, width, 16.7, shape)
        end = shape[-1]
        lanes[oid] = Lane(oid, "out", i, 100.0, width, 16.7,
                          np.array([end + [5 * direction, 0], end + [105 * direction, 0]]))
        conns.append(Connection(lid, oid, "J", i, "s"))
        ids.append(lid)
    edges = {"road": tuple(ids), "out": tuple(f"out_{i}" for i in range(len(ids)))}
    net = RoadNetwork(lanes, edges, {"road": ("A", "J"), "out": ("J", "B")},
                      {"J": (x1 + 2.5, 0.0, "traffic_light")}, conns)
    net.green_phases["J"] = ["G" * len(ids)]
    return net


def ground_run(frames, dets, fps, h, marks, out: dict) -> list[dict]:
    w, hh = marks["image_size"]
    g = np.linalg.inv(h)
    # the visible stretch of road: where the frame's left/right edges meet the lane lines
    ys = [float(k) for k in marks["lines"]]
    edge_px = np.array([[3.0, v] for v in np.linspace(0, hh - 1, 12)] +
                       [[w - 6.0, v] for v in np.linspace(0, hh - 1, 12)])
    gx = apply_homography(g, edge_px)[:, 0]
    x0, x1 = float(np.floor(np.nanmin(gx))) - 5, float(np.ceil(np.nanmax(gx))) + 5
    net = straight_road(marks["lines"], x0, x1)
    nadir = marks.get("nadir_image")
    nadir_xy = apply_homography(g, np.array([nadir]))[0] if nadir else (x0 - 20.0, min(ys) - 10.0)
    cam = HomographyCamera.from_matrix(h, w, hh, nadir_xy, "clip")
    rig = CameraRig.build(net, [CameraSpec("clip", cam, tls_id="J", approach_edge="road",
                                           fps=fps)])
    approach, receiving = net.link_lane_maps()
    signal = StaticSignalState({("J", link): "G" for link in approach["J"]},
                               {("J", link): 0.0 for link in approach["J"]})
    vs = VisionSystem(rig, approach, receiving, fps=fps, signal_state=signal)
    pipe = vs.pipelines["clip"]
    x_count = (x0 + x1) / 2
    last_x: dict[int, float] = {}
    counted: dict[str, set[int]] = defaultdict(set)
    speeds: dict[int, list[float]] = defaultdict(list)
    lane_votes: dict[int, Counter] = defaultdict(Counter)
    statuses, links = [], []
    next_tick = 1.0
    for k, (frame, d) in enumerate(zip(frames, dets, strict=True)):
        t = k / fps
        gts = pipe.ingest_detections(t, d, frame)
        pipe.ground.assign_lanes(gts)
        for gt in gts:
            if gt.coasting:
                continue
            if gt.speed_known:
                speeds[gt.track_id].append(float(np.hypot(*gt.velocity)))
            if gt.lane_id:
                lane_votes[gt.track_id][gt.lane_id] += 1
            px = last_x.get(gt.track_id)
            if px is not None and px < x_count <= gt.xy[0] and gt.lane_id:
                counted[gt.lane_id].add(gt.track_id)
            last_x[gt.track_id] = float(gt.xy[0])
        if t >= next_tick:
            res = vs.tick(t)
            statuses.append(res.camera_status["clip"][0].value)
            links.append({lk: round(e.approaching_pcu, 2) for (_, lk), e in res.links.items()})
            next_tick += 1.0
    per_track = {tid: float(np.median(v)) for tid, v in speeds.items() if len(v) >= 5}
    cov = rig.coverage("road_0")
    out["ground"] = {
        "road_x_range_m": [x0, x1],
        "covered_m_road_0": cov.covered_m,
        "count_line_x_m": x_count,
        "crossings_by_lane": {lid: len(v) for lid, v in sorted(counted.items())},
        "tracks_with_speed": len(per_track),
        "speed_mps_median": st.median(per_track.values()) if per_track else None,
        "speed_mps_range": [min(per_track.values()), max(per_track.values())]
        if per_track else None,
        "lane_consistency": float(np.mean([c.most_common(1)[0][1] / sum(c.values())
                                           for c in lane_votes.values()])) if lane_votes else None,
        "camera_status_by_tick": dict(Counter(statuses)),
        "approaching_pcu_by_tick": links[-5:],
    }
    return [{"track_id": tid, "speed_mps": round(v, 1)} for tid, v in sorted(per_track.items())]


# ---- pictures -----------------------------------------------------------------------------


def contact_sheet(frames, dets, per_frame_tracks, path: Path, n: int = 6) -> None:
    """Six busy frames with their tracks drawn -- on *redacted* frames: this
    script never writes an unredacted pixel either."""
    import cv2  # noqa: PLC0415
    from vision_service.privacy import redact  # noqa: PLC0415
    from vision_service.service import tracked_boxes  # noqa: PLC0415

    busy = sorted(range(len(frames)), key=lambda i: -len(per_frame_tracks[i]))[: n * 4]
    pick = sorted(busy[::4][:n]) if busy else [0]
    tiles = []
    for i in pick:
        im = redact(frames[i], dets[i] + tracked_boxes(per_frame_tracks[i]))
        scale = max(1, int(round(640 / im.shape[1])))
        im = cv2.resize(im, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        for t in per_frame_tracks[i]:
            x1, y1, x2, y2 = (int(v * scale) for v in t.box)
            col = (0, 200, 255) if t.coasting else (60, 220, 60)
            cv2.rectangle(im, (x1, y1), (x2, y2), col, 2)
            cv2.putText(im, f"#{t.track_id} {t.vclass.value}", (x1, max(12, y1 - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1, cv2.LINE_AA)
        cv2.putText(im, f"frame {i}", (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        tiles.append(im)
    while len(tiles) % 3:
        tiles.append(np.zeros_like(tiles[0]))
    rows = [np.hstack(tiles[k:k + 3]) for k in range(0, len(tiles), 3)]
    cv2.imwrite(str(path), np.vstack(rows))


def redaction_demo(frames, dets, path: Path) -> dict:
    import cv2  # noqa: PLC0415

    sensitive = {VClass.PERSON, VClass.BICYCLE, VClass.MOTORCYCLE}
    best = max(range(len(frames)), key=lambda i: sum(d.vclass in sensitive and
                                                     d.score >= 0.4 for d in dets[i]))
    buf = EvidenceBuffer(seconds=1.0, fps=1.0, scale=1.0)
    buf.push(0.0, frames[best], [d for d in dets[best] if d.score >= 0.4])
    clip = buf.redacted_clip()
    if clip:
        cv2.imwrite(str(path), clip[0][1])  # only the redacted frame is ever written
    return {"frame": best, "redacted_regions": sum(d.vclass in sensitive and d.score >= 0.4
                                                   for d in dets[best])}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--video", required=True)
    ap.add_argument("--weights", default="yolo11n.pt")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--onnx", action="store_true", help="also export to ONNX and check parity")
    ap.add_argument("--marks", help="lane-mark calibration JSON (enables the ground stage)")
    ap.add_argument("--fleet-scale", action="store_true",
                    help="unknown dash period: take the scale from the median car length")
    ap.add_argument("--car-length", type=float, default=4.5)
    ap.add_argument("--redact-demo", action="store_true")
    ap.add_argument("--reuse", action="store_true", help="reuse cached detections in --out")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    from vision_service.detect.yolo import OnnxDetector, UltralyticsDetector  # noqa: PLC0415

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    frames, fps = read_frames(args.video)
    h_px, w_px = frames[0].shape[:2]
    summary: dict = {"video": Path(args.video).name, "frames": len(frames), "fps": fps,
                     "size": [w_px, h_px], "weights": args.weights, "imgsz": args.imgsz}

    cache = out_dir / "detections.json"
    if args.reuse and cache.exists():
        raw = json.loads(cache.read_text())
        dets = [[Detection(tuple(d[:4]), d[4], VClass(d[5])) for d in fr] for fr in raw["dets"]]
        s_per_frame = raw["s_per_frame"]
    else:
        det = UltralyticsDetector(args.weights, imgsz=args.imgsz, device="cpu")
        dets, s_per_frame = run_detector(det, frames)
        cache.write_text(json.dumps({"s_per_frame": s_per_frame, "dets": [
            [[*map(float, d.box), float(d.score), d.vclass.value] for d in fr] for fr in dets]}))
    summary["detector"] = {
        "backend": "ultralytics", "ms_per_frame_cpu": round(1000 * s_per_frame, 1),
        "detections_per_frame": round(float(np.mean([len(d) for d in dets])), 2),
        "confident_per_frame": round(float(np.mean([sum(x.score >= 0.5 for x in d)
                                                    for d in dets])), 2),
        "by_class_conf50": dict(Counter(x.vclass.value for d in dets for x in d
                                        if x.score >= 0.5)),
    }
    if args.onnx:
        from ultralytics import YOLO  # noqa: PLC0415

        onnx_path = YOLO(args.weights).export(format="onnx", imgsz=args.imgsz, dynamic=True,
                                              verbose=False)
        odet = OnnxDetector(str(onnx_path), imgsz=args.imgsz)
        odets, o_spf = run_detector(odet, frames)
        summary["onnx"] = {"ms_per_frame_cpu": round(1000 * o_spf, 1), "dynamic_rect": True,
                           **onnx_parity(dets, odets)}
    trk, per_frame = image_tracking(dets, fps)
    summary["image_tracking"] = trk
    summary["pixel_health"] = pixel_health(frames, fps)

    if args.marks:
        marks = json.loads(Path(args.marks).read_text())
        if args.fleet_scale:
            marks = {**marks, "dash_period_m": 1.0}
        h, cal = calibrate(marks)
        if args.fleet_scale:
            m_per_unit, fs = fleet_scale(h, dets, (w_px, h_px), args.car_length)
            marks["dash_period_m"] = m_per_unit
            h, cal = calibrate(marks)
            cal["fleet_scale"] = fs
        summary["calibration"] = cal
        t0 = time.perf_counter()
        speeds = ground_run(frames, dets, fps, h, marks, summary)
        summary["pipeline_ms_per_frame"] = round(1000 * (time.perf_counter() - t0) / len(frames),
                                                 2)
        summary["track_speeds"] = speeds
    if args.redact_demo:
        summary["redaction"] = redaction_demo(frames, dets, out_dir / "redaction.jpg")
    contact_sheet(frames, dets, per_frame, out_dir / "tracks.jpg")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    print(json.dumps({k: v for k, v in summary.items() if k != "track_speeds"}, indent=1,
                     default=str))


if __name__ == "__main__":
    main()
