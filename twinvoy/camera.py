"""Live camera + MediaPipe FaceLandmarker -> Observation stream with an on-screen guide."""

from __future__ import annotations

import time
import urllib.request
from pathlib import Path
from typing import Iterator

import cv2
import numpy as np

from twinvoy.enroll import Observation
from twinvoy.headpose import estimate_pose, sharpness

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/latest/face_landmarker.task"
)


def ensure_landmarker_model(home: Path) -> Path:
    path = Path(home) / "models" / "face_landmarker.task"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading face landmark model to {path} ...")
        urllib.request.urlretrieve(MODEL_URL, path)
    return path


class LiveCamera:
    """Yields Observations from a webcam and draws the current prompt."""

    def __init__(self, model_path: Path, index: int = 0, width: int = 1280, height: int = 720,
                 show_window: bool = True):
        from mediapipe.tasks.python import BaseOptions, vision

        self.cap = cv2.VideoCapture(index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        if not self.cap.isOpened():
            raise RuntimeError(f"cannot open camera {index}")
        opts = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=2,
        )
        self.landmarker = vision.FaceLandmarker.create_from_options(opts)
        self.prompt = ""
        self.show = show_window
        self._t0 = time.monotonic()

    def set_prompt(self, text: str) -> None:
        self.prompt = text
        print(f">> {text}")

    def __iter__(self) -> Iterator[Observation]:
        import mediapipe as mp

        while True:
            ok, frame = self.cap.read()
            if not ok:
                return
            frame = cv2.flip(frame, 1)  # mirror so "turn left" feels natural
            h, w = frame.shape[:2]
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            ts = int((time.monotonic() - self._t0) * 1000)
            res = self.landmarker.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ts)
            pose = lm = None
            warn = ""
            if len(res.face_landmarks) == 1:
                lm = np.array([(p.x * w, p.y * h) for p in res.face_landmarks[0]])
                # frame is mirrored, so flip yaw back to the user's own left/right
                p = estimate_pose(lm, w, h)
                if p is not None:
                    from twinvoy.headpose import Pose
                    pose = Pose(yaw=-p.yaw, pitch=p.pitch, roll=p.roll)
            elif len(res.face_landmarks) > 1:
                warn = "Only one person may be in frame"
            else:
                warn = "No face detected"
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            obs = Observation(frame=frame.copy(), pose=pose, landmarks=lm, sharpness=sharpness(gray))
            if self.show:
                self._draw(frame, pose, warn)
            yield obs

    def _draw(self, frame, pose, warn) -> None:
        cv2.putText(frame, self.prompt, (30, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 255, 0), 2)
        if pose:
            cv2.putText(frame, f"yaw {pose.yaw:+.0f}  pitch {pose.pitch:+.0f}", (30, 90),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        if warn:
            cv2.putText(frame, warn, (30, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        cv2.imshow("Twinvoy enrollment (press q to quit)", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            raise KeyboardInterrupt

    def close(self) -> None:
        self.cap.release()
        self.landmarker.close()
        if self.show:
            cv2.destroyAllWindows()


def record_talking_clip(out: Path, seconds: int = 30, index: int = 0) -> Path:
    """Record a neutral talking clip (video-driven avatar backends need it)."""
    cap = cv2.VideoCapture(index)
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    vw = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), 25, (w, h))
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        ok, frame = cap.read()
        if not ok:
            break
        vw.write(frame)
        left = seconds - int(time.monotonic() - t0)
        disp = frame.copy()
        cv2.putText(disp, f"Talk naturally, e.g. describe your week  ({left}s)", (30, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
        cv2.imshow("Twinvoy clip", disp)
        cv2.waitKey(1)
    vw.release()
    cap.release()
    cv2.destroyAllWindows()
    return out
