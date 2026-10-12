"""ByteTrack (Zhang et al., ECCV 2022), implemented from the paper and its
reference code's control flow.

The idea that makes it the right tracker for a queue-counting camera:
**associate every detection box, including low-confidence ones.** A
motorcycle half-hidden behind a bus comes back from the detector with a low
score. A tracker that discards low-score boxes loses the motorcycle, then
re-finds it as a new vehicle when it reappears -- one vehicle counted twice,
or a queue that flickers. ByteTrack matches high-score boxes first, then
offers the *leftover* tracks a second chance against the low-score boxes, so
the partly hidden vehicle stays one track.

Differences from the reference code, all deliberate:

- Time is in seconds, not frames: `track_buffer_s` and `coast_output_s` are
  converted with the configured fps, so the same config works at 5 fps and
  at 25 fps.
- The output includes **coasting** tracks -- lost for at most
  `coast_output_s`, carried by their motion model and flagged -- because a
  queued vehicle that vanishes for two seconds behind a bus is still in the
  queue. The reference tracker reports only matched tracks.
- Each track keeps a score-weighted class vote, so one frame's mislabel does
  not change a vehicle's PCU.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from vision_service.classes import VClass
from vision_service.records import Detection, ImageTrack
from vision_service.track import kalman
from vision_service.track.assignment import gated_assignment, iou_matrix


@dataclass(frozen=True)
class ByteTrackConfig:
    fps: float = 5.0
    track_thresh: float = 0.5        # high/low split
    low_thresh: float = 0.1          # below this a box is ignored entirely
    new_track_thresh: float = 0.6    # a box must be this confident to start a track
    match_thresh: float = 0.8        # first stage: max (1 - IoU*score)
    second_match_thresh: float = 0.5  # second stage: max (1 - IoU)
    unconfirmed_match_thresh: float = 0.7
    track_buffer_s: float = 3.0      # how long a lost track can be re-found
    coast_output_s: float = 2.0      # how long a lost track is still *reported*
    fuse_score: bool = True


_NEW, _TRACKED, _LOST, _REMOVED = range(4)


@dataclass
class _Track:
    track_id: int
    mean: np.ndarray
    cov: np.ndarray
    score: float
    state: int
    activated: bool
    frame_id: int
    start_frame: int
    hits: int = 1
    class_votes: dict[VClass, float] = field(default_factory=dict)
    truth_votes: dict[str, int] = field(default_factory=dict)

    def vote(self, det: Detection) -> None:
        self.class_votes[det.vclass] = self.class_votes.get(det.vclass, 0.0) + det.score
        if det.truth_id is not None:
            self.truth_votes[det.truth_id] = self.truth_votes.get(det.truth_id, 0) + 1

    @property
    def vclass(self) -> VClass:
        return max(self.class_votes.items(), key=lambda kv: kv[1])[0]

    @property
    def truth_id(self) -> str | None:
        if not self.truth_votes:
            return None
        return max(self.truth_votes.items(), key=lambda kv: kv[1])[0]

    _box: np.ndarray | None = None

    @property
    def box(self) -> np.ndarray:
        if self._box is None:
            self._box = kalman.xyah_to_box(self.mean[:4])
        return self._box


class ByteTracker:
    def __init__(self, config: ByteTrackConfig | None = None):
        self.cfg = config or ByteTrackConfig()
        self.frame_id = 0
        self._next_id = 1
        self.tracked: list[_Track] = []
        self.lost: list[_Track] = []
        self._buffer_frames = max(1, int(round(self.cfg.track_buffer_s * self.cfg.fps)))
        self._coast_frames = max(0, int(round(self.cfg.coast_output_s * self.cfg.fps)))

    def reset(self) -> None:
        """Forget every track (after a gap in the video). Ids keep counting,
        so a track after the gap never reuses an id from before it."""
        self.tracked, self.lost = [], []

    # ---- helpers ------------------------------------------------------------

    def _predict(self, tracks: list[_Track]) -> None:
        if not tracks:
            return
        means = np.stack([t.mean for t in tracks])
        covs = np.stack([t.cov for t in tracks])
        for i, t in enumerate(tracks):
            if t.state != _TRACKED:
                means[i, 7] = 0.0  # a lost box keeps its size
        means, covs = kalman.predict_many(means, covs)
        boxes = kalman.xyah_to_box(means[:, :4])
        for i, t in enumerate(tracks):
            t.mean, t.cov, t._box = means[i], covs[i], boxes[i]

    @staticmethod
    def _dist(tracks: list[_Track], dets: list[Detection], fuse: bool) -> np.ndarray:
        if not tracks or not dets:
            return np.zeros((len(tracks), len(dets)))
        tb = np.stack([t.box for t in tracks])
        db = np.asarray([d.box for d in dets], dtype=np.float64)
        iou = iou_matrix(tb, db)
        if fuse:
            iou = iou * np.asarray([d.score for d in dets])[None, :]
        return 1.0 - iou

    def _update_tracks(self, pairs: list[tuple[_Track, Detection]]) -> None:
        """Kalman-update every matched (track, detection) pair in one batch."""
        if not pairs:
            return
        means = np.stack([t.mean for t, _ in pairs])
        covs = np.stack([t.cov for t, _ in pairs])
        meas = np.stack([kalman.box_to_xyah(np.asarray(d.box)) for _, d in pairs])
        means, covs = kalman.update_many(means, covs, meas)
        boxes = kalman.xyah_to_box(means[:, :4])
        for k, (t, det) in enumerate(pairs):
            t.mean, t.cov, t._box = means[k], covs[k], boxes[k]
            t.score = det.score
            t.state = _TRACKED
            t.activated = True
            t.frame_id = self.frame_id
            t.hits += 1
            t.vote(det)

    # ---- main --------------------------------------------------------------

    def update(self, detections: list[Detection]) -> list[ImageTrack]:
        self.frame_id += 1
        cfg = self.cfg
        high = [d for d in detections if d.score >= cfg.track_thresh]
        low = [d for d in detections if cfg.low_thresh <= d.score < cfg.track_thresh]

        unconfirmed = [t for t in self.tracked if not t.activated]
        confirmed = [t for t in self.tracked if t.activated]
        pool = confirmed + self.lost
        self._predict(pool)
        self._predict(unconfirmed)

        # stage 1: confirmed + lost vs high-score boxes
        dist = self._dist(pool, high, cfg.fuse_score)
        matches, u_track, u_high = gated_assignment(dist, cfg.match_thresh)
        refound: list[_Track] = []
        activated: list[_Track] = []
        for ti, _ in matches:
            t = pool[ti]
            (refound if t.state == _LOST else activated).append(t)
        self._update_tracks([(pool[ti], high[di]) for ti, di in matches])

        # stage 2: the leftovers that were being tracked vs low-score boxes
        remaining = [pool[i] for i in u_track if pool[i].state == _TRACKED]
        dist2 = self._dist(remaining, low, False)
        matches2, u_track2, _ = gated_assignment(dist2, cfg.second_match_thresh)
        self._update_tracks([(remaining[ti], low[di]) for ti, di in matches2])
        activated.extend(remaining[ti] for ti, _ in matches2)
        newly_lost = [remaining[i] for i in u_track2]
        for t in newly_lost:
            t.state = _LOST

        # unconfirmed tracks get one more chance against unused high boxes
        left_high = [high[i] for i in u_high]
        dist3 = self._dist(unconfirmed, left_high, cfg.fuse_score)
        matches3, u_unconf, u_high3 = gated_assignment(dist3, cfg.unconfirmed_match_thresh)
        self._update_tracks([(unconfirmed[ti], left_high[di]) for ti, di in matches3])
        activated.extend(unconfirmed[ti] for ti, _ in matches3)
        removed = {id(unconfirmed[i]) for i in u_unconf}

        # births
        born: list[_Track] = []
        for di in u_high3:
            d = left_high[di]
            if d.score < cfg.new_track_thresh:
                continue
            mean, cov = kalman.initiate(kalman.box_to_xyah(np.asarray(d.box)))
            t = _Track(
                track_id=self._next_id,
                mean=mean,
                cov=cov,
                score=d.score,
                state=_TRACKED,
                activated=self.frame_id == 1,
                frame_id=self.frame_id,
                start_frame=self.frame_id,
            )
            t.vote(d)
            self._next_id += 1
            born.append(t)

        # book-keeping
        still_lost = [t for t in self.lost if t.state == _LOST]
        still_lost += newly_lost
        still_lost = [t for t in still_lost if self.frame_id - t.frame_id <= self._buffer_frames]
        tracked_ids = {id(t) for t in activated + refound}
        self.tracked = [
            t for t in self.tracked
            if t.state == _TRACKED and id(t) not in removed and id(t) not in tracked_ids
        ] + activated + refound + born
        # de-duplicate (a track can appear via more than one list above)
        seen: set[int] = set()
        uniq = []
        for t in self.tracked:
            if id(t) not in seen and t.state == _TRACKED:
                seen.add(id(t))
                uniq.append(t)
        self.tracked = uniq
        self.lost = [t for t in still_lost if id(t) not in seen]
        self._remove_duplicates()
        return self._output()

    def _remove_duplicates(self, iou_thresh: float = 0.85) -> None:
        """The reference tracker's `remove_duplicate_stracks`, which the first
        version left out: a tracked and a lost track that overlap almost
        entirely are one vehicle. Keep whichever has been followed longer --
        otherwise the lost one is *reported* as coasting beside it for two
        seconds and the vehicle is counted twice."""
        if not self.tracked or not self.lost:
            return
        iou = iou_matrix(np.stack([t.box for t in self.tracked]),
                         np.stack([t.box for t in self.lost]))
        drop_tracked: set[int] = set()
        drop_lost: set[int] = set()
        for p, q in zip(*np.nonzero(iou > iou_thresh), strict=True):
            a, b = self.tracked[int(p)], self.lost[int(q)]
            if a.frame_id - a.start_frame > b.frame_id - b.start_frame:
                drop_lost.add(int(q))
            else:
                drop_tracked.add(int(p))
        self.tracked = [t for i, t in enumerate(self.tracked) if i not in drop_tracked]
        self.lost = [t for i, t in enumerate(self.lost) if i not in drop_lost]

    def _output(self) -> list[ImageTrack]:
        out: list[ImageTrack] = []
        for t in self.tracked:
            if not t.activated:
                continue
            out.append(ImageTrack(t.track_id, t.box, t.score, t.vclass, t.hits,
                                  self.frame_id - t.start_frame, False, t.truth_id))
        for t in self.lost:
            if self.frame_id - t.frame_id <= self._coast_frames and t.hits >= 3:
                out.append(ImageTrack(t.track_id, t.box, t.score, t.vclass, t.hits,
                                      self.frame_id - t.start_frame, True, t.truth_id))
        return out
