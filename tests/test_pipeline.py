import asyncio
import struct

import numpy as np
from fastapi.testclient import TestClient

from twinvoy.avatar.base import audio_envelope
from twinvoy.avatar.placeholder import PlaceholderRenderer
from twinvoy.brain import Brain, Utterance
from twinvoy.meeting.server import create_app
from twinvoy.orchestrator import Twin
from twinvoy.voice import SilentTTS

KW = ["approve", "budget"]


def test_brain_only_replies_when_addressed_and_escalates():
    b = Brain("Akshay D", KW)
    assert b.hear(Utterance("Sam", "let's move on")).reply is None
    d = b.hear(Utterance("Sam", "Akshay, can you approve the budget?"))
    assert d.escalate and "back to you" in d.reply
    assert b.followups


def test_brain_uses_llm_and_skip():
    calls = []
    def llm(system, msgs):
        calls.append(system)
        return "SKIP" if len(calls) > 1 else "The deploy finished yesterday."
    b = Brain("Akshay D", KW, notes="deploy done", llm=llm)
    assert b.hear(Utterance("Sam", "Akshay, status of deploy?")).reply.startswith("The deploy")
    assert b.hear(Utterance("Sam", "thanks Akshay")).reply is None
    assert "never claim" in calls[0].lower()


def test_audio_envelope_length():
    pcm = np.ones(24000, np.float32)
    assert len(audio_envelope(pcm, 24000, 25)) == 25


def make_twin(tmp_path):
    r = PlaceholderRenderer(tmp_path, 320, 180, 25)
    return Twin("Akshay D", r, SilentTTS(), Brain("Akshay D", KW))


def test_twin_speaks_intro_first_and_streams(tmp_path):
    twin = make_twin(tmp_path)
    frames, audio = [], []

    async def fsub(j): frames.append(j)
    async def asub(p, sr): audio.append((len(p), sr))
    twin.frame_subs.append(fsub)
    twin.audio_subs.append(asub)

    async def go():
        task = asyncio.create_task(twin.run())
        await twin.on_transcript("Sam", "Akshay, any update?")  # before intro
        await twin.joined()
        await asyncio.sleep(0.5)
        task.cancel()
    asyncio.run(go())
    said = [l for l in twin.transcript_log if l.startswith("Akshay D (AI twin)")]
    assert "I'm Akshay's AI twin" in said[0], "intro must be the first thing the twin says"
    assert sum("I'm Akshay's AI twin" in l for l in said) == 1, "intro spoken exactly once"
    assert twin.gate.disclosed and frames and audio


def test_server_auth_and_media(tmp_path):
    twin = make_twin(tmp_path)
    app = create_app(twin, token="secret")
    with TestClient(app) as c:
        assert c.get("/camera").status_code == 403
        page = c.get("/camera?token=secret").text
        assert "AI TWIN of Akshay D" in page and "secret" in page
        with c.websocket_connect("/ws/media?token=secret") as ws:
            kinds = set()
            for _ in range(80):
                m = ws.receive_bytes()
                kinds.add(m[:1])
                if m[:1] == b"A":
                    assert struct.unpack("<I", m[1:5])[0] == 24000
                if kinds == {b"V", b"A"}:
                    break
            assert kinds == {b"V", b"A"}
        assert any("AI twin" in l for l in twin.transcript_log)
