"""The VideoMAE accident detector's windowing and its fit into clip analysis."""

import numpy as np
import pytest

pytest.importorskip("cv2")

from vision_service.clips.accident import AlarmRule  # noqa: E402
from vision_service.clips.accident_videomae import (  # noqa: E402
    NF,
    STRIDE,
    VideoMaeAccident,
    proposals,
)
from vision_service.clips.analyse import ClipDetectors, analyse_clip  # noqa: E402


class _Stub(VideoMaeAccident):
    """The real windowing with the network swapped for a constant."""

    def __init__(self, p: float = 0.95):
        self.rule = AlarmRule(0.9, 2, 3, validated=True)
        self.p = p
        self.scored = 0
        self.reset()

    def _score_window(self) -> float:
        self._views()      # the real view-cutting still runs
        self.scored += 1
        return self.p


def _frame(i: int) -> np.ndarray:
    f = np.zeros((120, 160, 3), np.uint8)
    f[:, (i * 7) % 140:(i * 7) % 140 + 20] = 255       # something moving
    return f


def test_scores_once_a_second_after_sixteen_frames():
    m = _Stub()
    out = [m.prob(_frame(i)) for i in range(NF + 2 * STRIDE + 1)]
    assert out[:NF - 1] == [None] * (NF - 1)
    assert [i for i, p in enumerate(out) if p is not None] == [NF - 1, NF - 1 + STRIDE, NF - 1 + 2 * STRIDE]  # noqa: E501
    assert m.scored == 3


def test_reset_starts_a_clip_empty():
    m = _Stub()
    for i in range(NF):
        m.prob(_frame(i))
    m.reset()
    assert m.prob(_frame(0)) is None and m._n == 1


def test_proposals_pick_the_hottest_non_overlapping_areas():
    heat = np.zeros((32, 32), np.float32)
    heat[4, 4] = 9
    heat[25, 25] = 5
    (a, b) = proposals(heat, 640, 480)
    assert a[0] < 0.3 and a[1] < 0.3 and b[0] > 0.7 and b[1] > 0.7


def test_clip_analysis_alarms_from_a_stateful_model():
    frames = [(i / 4.0, _frame(i)) for i in range(60)]
    res = analyse_clip(iter(frames), ClipDetectors(accident=_Stub(0.95)))
    assert [f.anomaly_type for f in res.findings] == ["accident"]
    assert max(v for v in res.timeline["accident"] if v is not None) == pytest.approx(0.95)
    quiet = analyse_clip(iter(frames), ClipDetectors(accident=_Stub(0.1)))
    assert quiet.findings == []
