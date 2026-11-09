"""A camera flag becomes a review item, not an action."""

import numpy as np
import pytest

pytest.importorskip("cv2")

from vision_service import review  # noqa: E402


def _frames(n=6):
    return [(i * 0.5, np.full((48, 64, 3), 40 * i % 255, np.uint8)) for i in range(n)]


def test_frames_become_a_playable_mp4(tmp_path):
    import cv2

    out = tmp_path / "c.mp4"
    seconds = review.encode_mp4(_frames(), out)
    cap = cv2.VideoCapture(str(out))
    assert cap.isOpened() and int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == 6 and seconds > 2


def test_one_frame_is_not_a_clip(tmp_path):
    with pytest.raises(ValueError):
        review.encode_mp4(_frames(1), tmp_path / "c.mp4")


def test_the_upload_carries_the_key_the_road_and_who_sent_it(monkeypatch):
    sent = []

    class _Resp:
        status = 201

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(review.urllib.request, "urlopen",
                        lambda req, timeout: sent.append(req) or _Resp())
    t = [0.0]
    sink = review.make_review_sink("http://api:8000/", "k3y", clock=lambda: t[0])
    sink("cam-1", "edge-9", "fire", _frames())
    (req,) = sent
    assert req.full_url == "http://api:8000/v1/clips"
    assert req.get_header("X-api-key") == "k3y"
    body = req.data
    assert b'name="edge_id"\r\n\r\nedge-9' in body and b"camera:cam-1" in body
    assert b'filename="cam-1-fire.mp4"' in body


def test_a_camera_is_not_resent_inside_the_cooldown_and_a_failed_send_is_retried(monkeypatch):
    calls = []

    def urlopen(req, timeout):
        calls.append(1)
        raise OSError("down")

    monkeypatch.setattr(review.urllib.request, "urlopen", urlopen)
    t = [0.0]
    sink = review.make_review_sink("http://x", "k", clock=lambda: t[0])
    sink("c", "e", "fire", _frames())
    sink("c", "e", "fire", _frames())           # the first failed, so this retries
    assert len(calls) == 2
    monkeypatch.setattr(review.urllib.request, "urlopen",
                        lambda req, timeout: type("R", (), {"status": 201, "__enter__":
                                                            lambda s: s, "__exit__":
                                                            lambda s, *a: False})())
    sink("c", "e", "fire", _frames())            # sent: cooldown now applies
    t[0] = 10
    sink("c", "e", "fire", _frames())
    assert len(calls) == 2                        # no new failing call was made
