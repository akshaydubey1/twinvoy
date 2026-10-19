"""CPU-only renderer for testing the whole pipeline end to end.

Uses your enrolled front reference image with gentle head sway and a simple
loudness-driven mouth cue. It is intentionally basic: swap in MuseTalk or
another model for realistic lip-sync.
"""

from __future__ import annotations

import itertools
import math
from pathlib import Path
from typing import Iterator

import cv2
import numpy as np

from twinvoy.avatar.base import AvatarRenderer, audio_envelope


class PlaceholderRenderer(AvatarRenderer):
    name = "placeholder"

    def __init__(self, enroll_dir: Path, width: int = 1280, height: int = 720, fps: int = 25):
        self.fps, self.w, self.h = fps, width, height
        ref = Path(enroll_dir) / "front_0.jpg"
        img = cv2.imread(str(ref)) if ref.exists() else None
        if img is None:
            img = np.full((height, width, 3), 60, np.uint8)
            cv2.putText(img, "no enrollment yet", (40, height // 2), cv2.FONT_HERSHEY_SIMPLEX,
                        1.5, (220, 220, 220), 3)
        self.base = self._fit(img)
        self._t = 0

    def _fit(self, img: np.ndarray) -> np.ndarray:
        h, w = img.shape[:2]
        s = max(self.w / w, self.h / h)
        img = cv2.resize(img, (int(w * s) + 1, int(h * s) + 1))
        y0, x0 = (img.shape[0] - self.h) // 2, (img.shape[1] - self.w) // 2
        return img[y0:y0 + self.h, x0:x0 + self.w].copy()

    def _frame(self, mouth: float) -> np.ndarray:
        self._t += 1
        t = self._t / self.fps
        dx, dy = 4 * math.sin(t * 0.7), 3 * math.sin(t * 1.1)
        m = np.float32([[1.01, 0, dx - self.w * 0.005], [0, 1.01, dy - self.h * 0.005]])
        out = cv2.warpAffine(self.base, m, (self.w, self.h), borderMode=cv2.BORDER_REFLECT)
        if mouth > 0.05:  # speaking cue bar, bottom centre
            bw = int(self.w * 0.18 * mouth)
            cx, y = self.w // 2, int(self.h * 0.93)
            cv2.rectangle(out, (cx - bw, y - 6), (cx + bw, y + 6), (80, 200, 120), -1)
        return out

    def idle_frames(self) -> Iterator[np.ndarray]:
        for _ in itertools.count():
            yield self._frame(0.0)

    def speak(self, pcm: np.ndarray, sample_rate: int) -> Iterator[np.ndarray]:
        for level in audio_envelope(pcm, sample_rate, self.fps):
            yield self._frame(float(level))
