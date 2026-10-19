"""Serves the bot's camera page and streams the twin to it.

WebSocket /ws/media  -> binary messages: b"V"+jpeg  or  b"A"+uint32 sample_rate+pcm16
WebSocket /ws/transcript <- JSON {"speaker": str, "text": str} from the page
"""

from __future__ import annotations

import asyncio
import json
import secrets
import struct
from contextlib import asynccontextmanager
from importlib import resources

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from twinvoy.orchestrator import Twin


def create_app(twin: Twin, token: str | None = None) -> FastAPI:
    token = token or secrets.token_urlsafe(24)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(twin.run())
        yield
        task.cancel()

    app = FastAPI(title="Twinvoy", lifespan=lifespan)
    app.state.token = token
    app.state.joined = False

    def _check(t: str | None) -> None:
        if not t or not secrets.compare_digest(t, token):
            raise HTTPException(403)

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True, "owner": twin.owner, "renderer": twin.renderer.name}

    @app.get("/camera", response_class=HTMLResponse)
    async def camera(token: str | None = None) -> str:
        _check(token)
        html = resources.files("twinvoy.web").joinpath("camera.html").read_text()
        return (html.replace("__TOKEN__", token)
                    .replace("__OWNER__", twin.owner))

    @app.get("/followups")
    async def followups(token: str | None = None) -> dict:
        _check(token)
        return {"followups": twin.brain.followups, "transcript": twin.transcript_log[-200:]}

    @app.websocket("/ws/media")
    async def media(ws: WebSocket, token: str | None = None) -> None:
        if not token or not secrets.compare_digest(token, app.state.token):
            await ws.close(code=4403)
            return
        await ws.accept()

        async def send_frame(jpg: bytes) -> None:
            await ws.send_bytes(b"V" + jpg)

        async def send_audio(pcm16: bytes, sr: int) -> None:
            await ws.send_bytes(b"A" + struct.pack("<I", sr) + pcm16)

        twin.frame_subs.append(send_frame)
        twin.audio_subs.append(send_audio)
        if not app.state.joined:
            app.state.joined = True
            await twin.joined()
        try:
            while True:
                await ws.receive_text()  # keepalive pings from the page
        except WebSocketDisconnect:
            pass
        finally:
            for lst, fn in ((twin.frame_subs, send_frame), (twin.audio_subs, send_audio)):
                if fn in lst:
                    lst.remove(fn)

    @app.websocket("/ws/transcript")
    async def transcript(ws: WebSocket, token: str | None = None) -> None:
        if not token or not secrets.compare_digest(token, app.state.token):
            await ws.close(code=4403)
            return
        await ws.accept()
        try:
            while True:
                msg = json.loads(await ws.receive_text())
                text = str(msg.get("text", "")).strip()
                if text:
                    await twin.on_transcript(str(msg.get("speaker", "Someone")), text)
        except WebSocketDisconnect:
            pass

    return app
