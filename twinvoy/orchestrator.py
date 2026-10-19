"""Runs the twin: listens to transcript, decides, speaks, renders, streams.

Output goes to "subscribers" (the Recall camera page over WebSocket, or a
local virtual camera). Every frame passes through DisclosedVideoSink.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

import cv2
import numpy as np

from twinvoy.avatar.base import AvatarRenderer
from twinvoy.brain import Brain, Utterance
from twinvoy.disclosure import DisclosedVideoSink, DisclosureError, SpeechGate
from twinvoy.voice import TTS

FrameSub = Callable[[bytes], Awaitable[None]]           # JPEG bytes
AudioSub = Callable[[bytes, int], Awaitable[None]]      # PCM16 bytes, sample rate


@dataclass
class Twin:
    owner: str
    renderer: AvatarRenderer
    tts: TTS
    brain: Brain
    gate: SpeechGate = field(init=False)
    frame_subs: list[FrameSub] = field(default_factory=list)
    audio_subs: list[AudioSub] = field(default_factory=list)
    transcript_log: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.gate = SpeechGate(self.owner)
        self._latest: np.ndarray | None = None
        self.sink = DisclosedVideoSink(self._store, self.owner, generator=self.renderer.name)
        self._speech: asyncio.Queue[tuple[str, bool]] = asyncio.Queue()
        self._speaking = False

    def _store(self, frame: np.ndarray) -> None:
        self._latest = frame

    # ---- inputs -------------------------------------------------------
    async def on_transcript(self, speaker: str, text: str) -> None:
        self.transcript_log.append(f"{speaker}: {text}")
        if speaker.endswith("(AI twin)"):
            return
        decision = await asyncio.to_thread(self.brain.hear, Utterance(speaker, text))
        if decision.reply:
            await self._speech.put((decision.reply, False))

    async def joined(self) -> None:
        await self._speech.put(("", True))

    # ---- main loop ----------------------------------------------------
    async def run(self) -> None:
        fps = self.renderer.fps
        idle = self.renderer.idle_frames()
        period = 1.0 / fps
        while True:
            if not self._speech.empty() and not self._speaking:
                text, is_intro = await self._speech.get()
                await self._say(text, is_intro)
                continue
            t0 = time.monotonic()
            self.sink.write(next(idle))
            await self._publish_frame()
            await asyncio.sleep(max(0.0, period - (time.monotonic() - t0)))

    async def _say(self, text: str, is_intro: bool = False) -> None:
        if is_intro:
            if self.gate.disclosed:
                return  # already introduced itself
            text = self.gate.first_utterance()
        else:
            try:
                text = self.gate.check(text)
            except DisclosureError:
                if not self.gate.disclosed:
                    await self._say("", True)
                    text = self.gate.check(text)
                else:  # reply tried to claim to be human: replace, never send
                    text = f"Just to be clear, I'm {self.brain.first}'s AI twin."
        self._speaking = True
        self.transcript_log.append(f"{self.owner} (AI twin): {text}")
        try:
            pcm = await asyncio.to_thread(self.tts.synthesize, text)
            sr = self.tts.sample_rate
            pcm16 = (np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes()
            for sub in list(self.audio_subs):
                await sub(pcm16, sr)
            period = 1.0 / self.renderer.fps
            start = time.monotonic()
            for i, frame in enumerate(self.renderer.speak(pcm, sr)):
                self.sink.write(frame)
                await self._publish_frame()
                await asyncio.sleep(max(0.0, start + (i + 1) * period - time.monotonic()))
        finally:
            self._speaking = False

    async def _publish_frame(self) -> None:
        if self._latest is None or not self.frame_subs:
            return
        ok, jpg = cv2.imencode(".jpg", self._latest, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            data = jpg.tobytes()
            for sub in list(self.frame_subs):
                try:
                    await sub(data)
                except Exception:
                    self.frame_subs.remove(sub)

