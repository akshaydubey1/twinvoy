"""Guided multi-angle face enrollment with liveness and consent.

Flow
----
1. Consent: the owner types (and optionally speaks) a consent statement that
   names themselves and the purpose. Stored with a timestamp.
2. Liveness challenges in a *random order*: look straight, turn left, turn
   right, look up, look down, blink twice. Random order defeats replaying a
   pre-recorded video; the blink and the smooth pose changes defeat a photo.
3. For each pose, the sharpest frames are kept as reference images for the
   avatar model, plus a 20-30 s neutral "talking" clip for video-driven
   backends (MuseTalk, Tavus custom replicas).

Enrollment only ever captures from a live camera. There is deliberately no
"import photos" path: the twin must be built from the person at the camera.
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable

import numpy as np

from twinvoy.headpose import Pose, mean_ear

CONSENT_TEMPLATE = (
    "I, {name}, am creating an AI twin of my own face and voice. "
    "It will always identify itself as an AI twin in meetings, and I will not "
    "use it to make anyone believe they are talking to me live."
)


@dataclass(frozen=True)
class Challenge:
    key: str
    prompt: str
    test: Callable[[Pose], bool]
    hold_frames: int = 8


YAW_T, PITCH_T = 20.0, 12.0

CHALLENGES: dict[str, Challenge] = {
    "front": Challenge("front", "Look straight at the camera",
                       lambda p: abs(p.yaw) < 8 and abs(p.pitch) < 8),
    "left": Challenge("left", "Slowly turn your head to your LEFT",
                      lambda p: p.yaw > YAW_T),
    "right": Challenge("right", "Slowly turn your head to your RIGHT",
                       lambda p: p.yaw < -YAW_T),
    "up": Challenge("up", "Tilt your head UP", lambda p: p.pitch > PITCH_T),
    "down": Challenge("down", "Tilt your head DOWN", lambda p: p.pitch < -PITCH_T),
}


def challenge_order(seed: int | None = None) -> list[str]:
    """Front first (for a clean reference), the rest shuffled, blink last."""
    rest = ["left", "right", "up", "down"]
    random.Random(seed).shuffle(rest)
    return ["front", *rest, "blink"]


class BlinkDetector:
    """Counts blinks from a stream of eye-aspect-ratio values."""

    def __init__(self, closed: float = 0.19, opened: float = 0.24, min_closed_frames: int = 1):
        self.closed, self.opened = closed, opened
        self.min_closed = min_closed_frames
        self._closed_run = 0
        self.count = 0

    def update(self, ear: float) -> int:
        if ear < self.closed:
            self._closed_run += 1
        elif ear > self.opened:
            if self._closed_run >= self.min_closed:
                self.count += 1
            self._closed_run = 0
        return self.count


class HoldTracker:
    """A pose must be held for N consecutive frames to count."""

    def __init__(self, needed: int):
        self.needed, self.run = needed, 0

    def update(self, ok: bool) -> bool:
        self.run = self.run + 1 if ok else 0
        return self.run >= self.needed


@dataclass
class Observation:
    """One processed camera frame."""
    frame: np.ndarray            # BGR
    pose: Pose | None
    landmarks: np.ndarray | None  # (N,2) px
    sharpness: float = 0.0


@dataclass
class EnrollmentResult:
    owner: str
    consent_text: str
    consent_at: float
    order: list[str]
    captures: dict[str, list[str]] = field(default_factory=dict)
    blinks: int = 0
    completed: bool = False
    manifest_sha256: str = ""


class EnrollmentSession:
    """Pure state machine; camera and UI are injected so it is testable."""

    def __init__(self, owner: str, out_dir: Path, seed: int | None = None,
                 keep_per_pose: int = 3, blinks_needed: int = 2, timeout_s: float = 45.0):
        self.owner = owner
        self.out_dir = Path(out_dir)
        self.order = challenge_order(seed)
        self.keep = keep_per_pose
        self.blinks_needed = blinks_needed
        self.timeout_s = timeout_s
        self.result: EnrollmentResult | None = None

    def record_consent(self, typed: str) -> None:
        expected = CONSENT_TEMPLATE.format(name=self.owner)
        if " ".join(typed.split()).lower() != " ".join(expected.split()).lower():
            raise ValueError("consent statement must be typed exactly as shown")
        self.result = EnrollmentResult(owner=self.owner, consent_text=expected,
                                       consent_at=time.time(), order=list(self.order))

    def run(self, observations: Iterable[Observation],
            on_prompt: Callable[[str], None] = print,
            save: Callable[[Path, np.ndarray], None] | None = None,
            clock: Callable[[], float] = time.monotonic) -> EnrollmentResult:
        if self.result is None:
            raise RuntimeError("record consent before capturing")
        save = save or _imwrite
        self.out_dir.mkdir(parents=True, exist_ok=True)
        it = iter(observations)
        for key in self.order:
            on_prompt(CHALLENGES[key].prompt if key != "blink" else "Blink twice")
            started = clock()
            if key == "blink":
                if not self._blink_step(it, clock, started):
                    return self._fail(f"liveness: no blinks detected ({self.result.blinks})")
                continue
            ch = CHALLENGES[key]
            hold = HoldTracker(ch.hold_frames)
            best: list[tuple[float, np.ndarray]] = []
            for obs in it:
                if clock() - started > self.timeout_s:
                    return self._fail(f"timed out on '{key}'")
                ok = obs.pose is not None and ch.test(obs.pose)
                if ok:
                    best.append((obs.sharpness, obs.frame))
                if hold.update(ok):
                    break
            else:
                return self._fail(f"camera ended during '{key}'")
            best.sort(key=lambda t: t[0], reverse=True)
            paths = []
            for i, (_, img) in enumerate(best[: self.keep]):
                p = self.out_dir / f"{key}_{i}.jpg"
                save(p, img)
                paths.append(p.name)
            self.result.captures[key] = paths
        self.result.completed = True
        self._write_manifest()
        on_prompt("Enrollment complete")
        return self.result

    def _blink_step(self, it, clock, started) -> bool:
        det = BlinkDetector()
        for obs in it:
            if clock() - started > self.timeout_s:
                break
            if obs.landmarks is not None:
                self.result.blinks = det.update(mean_ear(obs.landmarks))
                if self.result.blinks >= self.blinks_needed:
                    return True
        return False

    def _fail(self, reason: str) -> EnrollmentResult:
        raise EnrollmentFailed(reason)

    def _write_manifest(self) -> None:
        data = asdict(self.result)
        data.pop("manifest_sha256")
        blob = json.dumps(data, sort_keys=True).encode()
        self.result.manifest_sha256 = hashlib.sha256(blob).hexdigest()
        (self.out_dir / "manifest.json").write_text(json.dumps(asdict(self.result), indent=2))


class EnrollmentFailed(RuntimeError):
    pass


def _imwrite(path: Path, img: np.ndarray) -> None:
    import cv2
    cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 95])


def load_manifest(enroll_dir: Path) -> EnrollmentResult:
    data = json.loads((Path(enroll_dir) / "manifest.json").read_text())
    res = EnrollmentResult(**data)
    check = dict(data)
    check.pop("manifest_sha256")
    digest = hashlib.sha256(json.dumps(check, sort_keys=True).encode()).hexdigest()
    if digest != res.manifest_sha256 or not res.completed:
        raise EnrollmentFailed("enrollment manifest is missing, incomplete or was modified")
    return res
