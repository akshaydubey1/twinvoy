"""Text-to-speech in the owner's own (enrolled) voice."""

from __future__ import annotations

import io
import wave
from abc import ABC, abstractmethod

import numpy as np

from twinvoy.config import TwinConfig


class TTS(ABC):
    sample_rate: int = 24000

    @abstractmethod
    def synthesize(self, text: str) -> np.ndarray:
        """Return mono float32 PCM in [-1, 1] at self.sample_rate."""


class SilentTTS(TTS):
    """No audio, but realistic timing (~150 wpm) so the pipeline can be tested."""

    def synthesize(self, text: str) -> np.ndarray:
        words = max(1, len(text.split()))
        secs = words / 2.5
        t = np.arange(int(secs * self.sample_rate)) / self.sample_rate
        # low-level syllable-rate envelope so mouth cues move; inaudible amplitude
        return (0.001 * np.abs(np.sin(2 * np.pi * 4 * t))).astype(np.float32)


class OpenAICompatTTS(TTS):
    """POST /v1/audio/speech returning WAV; works with self-hosted cloned voices."""

    def __init__(self, base_url: str, voice: str, timeout: float = 30.0):
        import httpx
        self.client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)
        self.voice = voice

    def synthesize(self, text: str) -> np.ndarray:
        r = self.client.post("/v1/audio/speech",
                             json={"model": "tts", "input": text, "voice": self.voice,
                                   "response_format": "wav"})
        r.raise_for_status()
        return wav_to_pcm(r.content, self)


def wav_to_pcm(data: bytes, tts: TTS) -> np.ndarray:
    with wave.open(io.BytesIO(data)) as w:
        tts.sample_rate = w.getframerate()
        raw = w.readframes(w.getnframes())
        ch, width = w.getnchannels(), w.getsampwidth()
    if width != 2:
        raise ValueError("expected 16-bit WAV")
    pcm = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    return pcm.reshape(-1, ch).mean(axis=1) if ch > 1 else pcm


def make_tts(cfg: TwinConfig) -> TTS:
    if cfg.voice.tts_backend == "openai_compat":
        return OpenAICompatTTS(cfg.voice.tts_base_url, cfg.voice.tts_voice)
    return SilentTTS()
