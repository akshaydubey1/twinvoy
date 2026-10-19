"""Configuration loading and validation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from twinvoy.disclosure import enforce_display_name

DEFAULT_HOME = Path(os.environ.get("TWINVOY_HOME", Path.home() / ".twinvoy"))


class OwnerConfig(BaseModel):
    full_name: str
    email: str = ""


class AvatarConfig(BaseModel):
    backend: Literal["placeholder", "musetalk", "tavus"] = "placeholder"
    musetalk_repo: str = ""          # path to a local MuseTalk checkout
    tavus_replica_id: str = ""
    fps: int = Field(25, ge=10, le=60)
    width: int = 1280
    height: int = 720


class VoiceConfig(BaseModel):
    # "openai_compat" = any self-hosted server exposing /v1/audio/speech
    # (e.g. MOSS-TTS's OpenAI-compatible API, or a Qwen3-TTS server)
    tts_backend: Literal["silent", "openai_compat"] = "silent"
    tts_base_url: str = "http://localhost:8880"
    tts_voice: str = "owner"         # voice id cloned from your own enrollment sample
    reference_audio: str = ""        # your own voice sample from enrollment
    stt_backend: Literal["recall", "whisper"] = "recall"


class BrainConfig(BaseModel):
    model: str = "claude-sonnet-5-5"
    knowledge_dir: str = ""          # notes the twin may answer from
    escalate_keywords: list[str] = Field(
        default_factory=lambda: [
            "approve", "sign off", "commit to", "budget", "contract",
            "salary", "offer", "password", "credentials", "confidential",
        ]
    )


class MeetingConfig(BaseModel):
    transport: Literal["recall", "virtualcam"] = "recall"
    recall_region: str = "us-east-1"
    public_base_url: str = ""        # where the bot's camera page is served
    display_name: str = ""           # filled from owner name if empty

    @field_validator("display_name")
    @classmethod
    def _must_disclose(cls, v: str) -> str:
        return enforce_display_name(v) if v else v


class TwinConfig(BaseModel):
    owner: OwnerConfig
    avatar: AvatarConfig = AvatarConfig()
    voice: VoiceConfig = VoiceConfig()
    brain: BrainConfig = BrainConfig()
    meeting: MeetingConfig = MeetingConfig()
    home: Path = DEFAULT_HOME

    def resolved_display_name(self) -> str:
        return self.meeting.display_name or enforce_display_name(self.owner.full_name)

    @property
    def enrollment_dir(self) -> Path:
        return self.home / "enrollment"


def load_config(path: str | Path) -> TwinConfig:
    data = yaml.safe_load(Path(path).read_text()) or {}
    return TwinConfig.model_validate(data)
