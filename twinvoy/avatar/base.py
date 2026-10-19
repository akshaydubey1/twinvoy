from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator

import numpy as np


class AvatarRenderer(ABC):
    """Produces BGR frames. Frames are stamped by DisclosedVideoSink downstream."""

    fps: int
    name: str = "avatar"

    @abstractmethod
    def idle_frames(self) -> Iterator[np.ndarray]:
        """Endless frames while listening (subtle motion, blinks)."""

    @abstractmethod
    def speak(self, pcm: np.ndarray, sample_rate: int) -> Iterator[np.ndarray]:
        """Frames lip-synced to mono float32 PCM in [-1, 1]."""


def audio_envelope(pcm: np.ndarray, sample_rate: int, fps: int) -> np.ndarray:
    """Per-video-frame loudness in [0, 1]."""
    hop = max(1, sample_rate // fps)
    n = max(1, int(np.ceil(len(pcm) / hop)))
    padded = np.zeros(n * hop, dtype=np.float32)
    padded[: len(pcm)] = pcm
    rms = np.sqrt((padded.reshape(n, hop) ** 2).mean(axis=1))
    peak = rms.max()
    return rms / peak if peak > 1e-6 else rms
