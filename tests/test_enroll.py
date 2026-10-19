import json

import numpy as np
import pytest

from twinvoy.enroll import (
    CONSENT_TEMPLATE, BlinkDetector, EnrollmentFailed, EnrollmentSession, Observation,
    challenge_order, load_manifest,
)
from twinvoy.headpose import L_EYE, R_EYE, Pose, estimate_pose, MODEL_3D, POSE_IDX

import cv2

NAME = "Akshay D"


def fake_landmarks(eye_open: bool) -> np.ndarray:
    lm = np.zeros((478, 2))
    for idx in (L_EYE, R_EYE):
        p1, p2, p3, p4, p5, p6 = idx
        lm[p1], lm[p4] = (0, 0), (30, 0)
        h = 8 if eye_open else 1
        lm[p2], lm[p3] = (10, -h), (20, -h)
        lm[p6], lm[p5] = (10, h), (20, h)
    return lm


def obs(pose=None, eye_open=True):
    return Observation(frame=np.full((48, 64, 3), 128, np.uint8), pose=pose,
                       landmarks=fake_landmarks(eye_open), sharpness=1.0)


def scripted_stream(order):
    poses = {"front": Pose(0, 0, 0), "left": Pose(30, 0, 0), "right": Pose(-30, 0, 0),
             "up": Pose(0, 20, 0), "down": Pose(0, -20, 0)}
    for key in order:
        if key == "blink":
            for _ in range(2):
                yield obs(Pose(0, 0, 0), True)
                yield obs(Pose(0, 0, 0), False)
                yield obs(Pose(0, 0, 0), True)
        else:
            for _ in range(10):
                yield obs(poses[key])


def session(tmp_path, seed=1):
    s = EnrollmentSession(NAME, tmp_path, seed=seed, timeout_s=1e9)
    s.record_consent(CONSENT_TEMPLATE.format(name=NAME))
    return s


def test_consent_must_match(tmp_path):
    s = EnrollmentSession(NAME, tmp_path)
    with pytest.raises(ValueError):
        s.record_consent("yes ok")
    with pytest.raises(RuntimeError):
        s.run([])


def test_order_is_randomised_but_bounded():
    orders = {tuple(challenge_order(seed)) for seed in range(20)}
    assert len(orders) > 1
    for o in orders:
        assert o[0] == "front" and o[-1] == "blink" and len(o) == 6


def test_full_enrollment_writes_verified_manifest(tmp_path):
    s = session(tmp_path)
    res = s.run(scripted_stream(s.order), on_prompt=lambda _: None)
    assert res.completed and res.blinks >= 2
    assert set(res.captures) == {"front", "left", "right", "up", "down"}
    assert load_manifest(tmp_path).owner == NAME


def test_tampered_manifest_rejected(tmp_path):
    s = session(tmp_path)
    s.run(scripted_stream(s.order), on_prompt=lambda _: None)
    m = json.loads((tmp_path / "manifest.json").read_text())
    m["owner"] = "Someone Else"
    (tmp_path / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(EnrollmentFailed):
        load_manifest(tmp_path)


def test_photo_fails_liveness(tmp_path):
    """A static photo can hold poses (if moved) but never blinks."""
    s = session(tmp_path)
    def stream():
        for o in scripted_stream([k for k in s.order if k != "blink"]):
            yield o
        for _ in range(50):
            yield obs(Pose(0, 0, 0), True)
    with pytest.raises(EnrollmentFailed, match="liveness"):
        s.run(stream(), on_prompt=lambda _: None)


def test_replayed_video_in_wrong_order_fails(tmp_path):
    s = session(tmp_path, seed=3)
    wrong = ["front", "down", "up", "right", "left", "blink"]
    assert wrong != s.order
    with pytest.raises(EnrollmentFailed):
        s.run(scripted_stream(wrong), on_prompt=lambda _: None)


def test_blink_detector():
    d = BlinkDetector()
    for ear in [0.3, 0.1, 0.3, 0.3, 0.1, 0.1, 0.3]:
        d.update(ear)
    assert d.count == 2


def test_headpose_recovers_yaw():
    w, h = 1280, 720
    cam = np.array([[w, 0, w / 2], [0, w, h / 2], [0, 0, 1]], float)
    for yaw in (-30, 0, 30):
        rvec = np.array([0.0, np.radians(yaw), 0.0])
        pts, _ = cv2.projectPoints(MODEL_3D, rvec, np.array([0, 0, 600.0]), cam, np.zeros(4))
        lm = np.zeros((478, 2))
        for i, idx in enumerate(POSE_IDX):
            lm[idx] = pts[i, 0]
        p = estimate_pose(lm, w, h)
        assert abs(abs(p.yaw) - abs(yaw)) < 3
