"""Avatar renderers turn speech audio into video frames of the owner's face."""

from __future__ import annotations

from pathlib import Path

from twinvoy.avatar.base import AvatarRenderer
from twinvoy.config import TwinConfig


def make_renderer(cfg: TwinConfig) -> AvatarRenderer:
    enroll = Path(cfg.enrollment_dir)
    if cfg.avatar.backend == "placeholder":
        from twinvoy.avatar.placeholder import PlaceholderRenderer
        return PlaceholderRenderer(enroll, cfg.avatar.width, cfg.avatar.height, cfg.avatar.fps)
    if cfg.avatar.backend == "musetalk":
        from twinvoy.avatar.musetalk import MuseTalkRenderer
        return MuseTalkRenderer(enroll, cfg.avatar.musetalk_repo, cfg.avatar.fps)
    raise ValueError(
        "the 'tavus' backend renders in Tavus's hosted pipeline rather than locally; "
        "see docs/ARCHITECTURE.md (Option B) for how it plugs into the camera page"
    )
