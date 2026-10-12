"""ByteTrack keeps identities through the things that break simpler
trackers: low-confidence (half-hidden) boxes and short gaps."""

from __future__ import annotations

from vision_service.classes import VClass
from vision_service.records import Detection
from vision_service.track import ByteTrackConfig, ByteTracker


def _box(x: float, y: float = 100.0, w: float = 40.0, h: float = 30.0):
    return (x, y, x + w, y + h)


def _run(tracker: ByteTracker, frames):
    return [tracker.update(f) for f in frames]


def test_one_moving_vehicle_keeps_one_identity() -> None:
    tr = ByteTracker(ByteTrackConfig(fps=5))
    out = _run(tr, [[Detection(_box(10 + 6 * k), 0.9, VClass.CAR)] for k in range(20)])
    ids = {t.track_id for frame in out[2:] for t in frame}
    assert ids == {1}


def test_a_low_score_box_keeps_the_track_alive() -> None:
    """The half-hidden frames come back at score 0.3: the second association
    stage must use them rather than let the track go."""
    tr = ByteTracker(ByteTrackConfig(fps=5, coast_output_s=0.0))
    frames = [[Detection(_box(10 + 5 * k), 0.9, VClass.CAR)] for k in range(5)]
    frames += [[Detection(_box(35 + 5 * k), 0.3, VClass.CAR)] for k in range(5)]
    frames += [[Detection(_box(60 + 5 * k), 0.9, VClass.CAR)] for k in range(5)]
    out = _run(tr, frames)
    assert all(len(f) == 1 and f[0].track_id == 1 for f in out[2:])


def test_a_short_gap_is_bridged_and_reported_as_coasting() -> None:
    tr = ByteTracker(ByteTrackConfig(fps=5, track_buffer_s=2.0, coast_output_s=1.0))
    frames = [[Detection(_box(10 + 5 * k), 0.9, VClass.CAR)] for k in range(6)]
    frames += [[] for _ in range(4)]  # 0.8 s hidden
    frames += [[Detection(_box(60 + 5 * k), 0.9, VClass.CAR)] for k in range(4)]
    out = _run(tr, frames)
    hidden = out[6:10]
    assert all(len(f) == 1 and f[0].coasting for f in hidden)
    assert out[-1][0].track_id == 1 and not out[-1][0].coasting


def test_a_weak_box_cannot_start_a_track() -> None:
    tr = ByteTracker(ByteTrackConfig(fps=5))
    out = _run(tr, [[Detection(_box(10), 0.45, VClass.CAR)] for _ in range(5)])
    assert all(f == [] for f in out)


def test_class_is_a_vote_not_the_last_frame() -> None:
    tr = ByteTracker(ByteTrackConfig(fps=5))
    frames = [[Detection(_box(10 + 5 * k), 0.9, VClass.AUTO_RICKSHAW)] for k in range(8)]
    frames.append([Detection(_box(50), 0.9, VClass.CAR)])
    out = _run(tr, frames)
    assert out[-1][0].vclass is VClass.AUTO_RICKSHAW


def test_two_vehicles_do_not_swap() -> None:
    tr = ByteTracker(ByteTrackConfig(fps=5))
    frames = [[Detection(_box(10 + 5 * k, y=100), 0.9, VClass.CAR),
               Detection(_box(300 - 5 * k, y=300), 0.9, VClass.BUS)] for k in range(15)]
    out = _run(tr, frames)
    first = {t.vclass: t.track_id for t in out[3]}
    last = {t.vclass: t.track_id for t in out[-1]}
    assert first == last and len(first) == 2


def test_a_lost_track_drifting_onto_a_live_one_is_dropped() -> None:
    """The reference tracker's duplicate removal: a lost track whose
    prediction lies on top of a tracked one is the same vehicle; the one
    followed longer survives, so the vehicle is not reported twice."""
    import numpy as np
    from vision_service.track import bytetrack as bt

    tr = ByteTracker(ByteTrackConfig(fps=5))
    for _ in range(8):
        tr.update([Detection(_box(10), 0.9, VClass.CAR), Detection(_box(300), 0.9, VClass.CAR)])
    old, young = sorted(tr.tracked, key=lambda t: t.track_id)
    young.start_frame = tr.frame_id - 2          # followed for a shorter time
    old.state = bt._LOST
    tr.lost, tr.tracked = [old], [young]
    old.mean = young.mean.copy()                 # its prediction now sits on the other
    old._box = None
    tr._remove_duplicates()
    assert len(tr.tracked) + len(tr.lost) == 1
    assert (tr.tracked or tr.lost)[0] is old     # the longer-followed one is kept
    assert np.isfinite(old.box).all()
