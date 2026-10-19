"""Head pose and blink estimation from 2D face landmarks.

Works with MediaPipe Face Mesh / FaceLandmarker indices (468/478 points).
The math is kept separate from the landmark detector so it can be unit tested.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

# MediaPipe face-mesh indices
NOSE_TIP, CHIN = 1, 152
L_EYE_OUTER, R_EYE_OUTER = 33, 263
MOUTH_L, MOUTH_R = 61, 291
# eye-aspect-ratio points (p1..p6) for each eye
L_EYE = (33, 160, 158, 133, 153, 144)
R_EYE = (362, 385, 387, 263, 373, 380)

# Generic 3D face model (mm), matching the six points above.
MODEL_3D = np.array(
    [
        (0.0, 0.0, 0.0),        # nose tip
        (0.0, -63.6, -12.5),    # chin
        (-43.3, 32.7, -26.0),   # left eye outer
        (43.3, 32.7, -26.0),    # right eye outer
        (-28.9, -28.9, -24.1),  # mouth left
        (28.9, -28.9, -24.1),   # mouth right
    ],
    dtype=np.float64,
)
POSE_IDX = (NOSE_TIP, CHIN, L_EYE_OUTER, R_EYE_OUTER, MOUTH_L, MOUTH_R)


@dataclass(frozen=True)
class Pose:
    yaw: float    # + = user turned to their left (camera sees right cheek)
    pitch: float  # + = looking up
    roll: float


def estimate_pose(landmarks_px: np.ndarray, width: int, height: int) -> Pose | None:
    """landmarks_px: (N, 2) pixel coordinates."""
    if landmarks_px.shape[0] <= max(POSE_IDX):
        return None
    image_pts = np.array([landmarks_px[i] for i in POSE_IDX], dtype=np.float64)
    focal = float(width)
    cam = np.array([[focal, 0, width / 2], [0, focal, height / 2], [0, 0, 1]], dtype=np.float64)
    ok, rvec, _ = cv2.solvePnP(MODEL_3D, image_pts, cam, np.zeros(4), flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok:
        return None
    rmat, _ = cv2.Rodrigues(rvec)
    sy = np.hypot(rmat[0, 0], rmat[1, 0])
    pitch = np.degrees(np.arctan2(rmat[2, 1], rmat[2, 2]))
    yaw = np.degrees(np.arctan2(-rmat[2, 0], sy))
    roll = np.degrees(np.arctan2(rmat[1, 0], rmat[0, 0]))
    # solvePnP with image y-down flips pitch to around +/-180; normalise
    pitch = (pitch + 180) % 360 - 180
    if pitch > 90:
        pitch -= 180
    elif pitch < -90:
        pitch += 180
    return Pose(yaw=float(yaw), pitch=float(-pitch), roll=float(roll))


def eye_aspect_ratio(landmarks_px: np.ndarray, idx: tuple[int, ...]) -> float:
    p = [landmarks_px[i] for i in idx]
    vertical = np.linalg.norm(p[1] - p[5]) + np.linalg.norm(p[2] - p[4])
    horizontal = 2.0 * np.linalg.norm(p[0] - p[3])
    return float(vertical / horizontal) if horizontal > 1e-6 else 0.0


def mean_ear(landmarks_px: np.ndarray) -> float:
    return (eye_aspect_ratio(landmarks_px, L_EYE) + eye_aspect_ratio(landmarks_px, R_EYE)) / 2


def sharpness(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())
