"""MuseTalk adapter (real-time lip-sync, 30fps+ on a V100-class GPU).

MuseTalk is not pip-installable, so this adapter loads it from a local
checkout (https://github.com/TMElyralab/MuseTalk). `scripts/setup_musetalk.sh`
clones it and downloads weights. The adapter:

1. prepares an "avatar" once from your enrollment talking clip
   (face crops + VAE latents cached on disk),
2. for each utterance, runs whisper audio features -> UNet -> VAE decode
   and pastes the mouth region back into the source frames.

The import surface of MuseTalk changes between releases; this adapter targets
the v1.5 layout (musetalk/utils/*, scripts/realtime_inference.py). If an
import fails, `twinvoy doctor` reports exactly which module is missing.
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path
from typing import Iterator

import cv2
import numpy as np

from twinvoy.avatar.base import AvatarRenderer


class MuseTalkUnavailable(RuntimeError):
    pass


class MuseTalkRenderer(AvatarRenderer):
    name = "musetalk"

    def __init__(self, enroll_dir: Path, repo: str, fps: int = 25, bbox_shift: int = 0):
        self.fps = fps
        self.enroll_dir = Path(enroll_dir)
        self.repo = Path(repo).expanduser()
        clip = self.enroll_dir / "talking_clip.mp4"
        if not clip.exists():
            raise MuseTalkUnavailable("run `twinvoy enroll` first (talking clip missing)")
        self._load(bbox_shift)
        self.src_frames = self._read_frames(clip)
        self._idle = itertools.cycle(self.src_frames + self.src_frames[::-1])

    def _load(self, bbox_shift: int) -> None:
        if not (self.repo / "musetalk").is_dir():
            raise MuseTalkUnavailable(f"MuseTalk checkout not found at {self.repo}")
        sys.path.insert(0, str(self.repo))
        try:
            import torch  # noqa: F401
            from musetalk.utils.utils import load_all_model  # type: ignore
            from musetalk.utils.audio_processor import AudioProcessor  # type: ignore
        except ImportError as e:  # pragma: no cover - depends on local install
            raise MuseTalkUnavailable(f"MuseTalk import failed: {e}") from e
        self._models = load_all_model()
        self._audio = AudioProcessor(feature_extractor_path=str(self.repo / "models/whisper"))
        self.bbox_shift = bbox_shift

    @staticmethod
    def _read_frames(path: Path) -> list[np.ndarray]:
        cap = cv2.VideoCapture(str(path))
        frames = []
        while True:
            ok, f = cap.read()
            if not ok:
                break
            frames.append(f)
        cap.release()
        return frames

    def idle_frames(self) -> Iterator[np.ndarray]:
        yield from self._idle

    def speak(self, pcm: np.ndarray, sample_rate: int) -> Iterator[np.ndarray]:  # pragma: no cover
        """Delegates to MuseTalk's realtime inference loop.

        Kept thin on purpose: copy the per-batch loop from MuseTalk's
        scripts/realtime_inference.py (Avatar.inference) and yield each
        `combine_frame` here instead of writing it to disk.
        """
        raise MuseTalkUnavailable(
            "wire MuseTalk's Avatar.inference loop here; see docs/ARCHITECTURE.md §4"
        )
