"""Local mode: send the (badge-stamped) twin to a virtual webcam.

Use this when you are in the meeting yourself and want the twin to present
or answer for you, with your meeting name set to include "(AI twin)".
Requires `pip install pyvirtualcam` plus OBS Virtual Camera (Windows/macOS)
or v4l2loopback (Linux).
"""

from __future__ import annotations

import asyncio

import cv2

from twinvoy.orchestrator import Twin


async def run_virtualcam(twin: Twin) -> None:
    import pyvirtualcam

    r = twin.renderer
    first = next(r.idle_frames())
    h, w = first.shape[:2]
    with pyvirtualcam.Camera(width=w, height=h, fps=r.fps) as cam:
        print(f"Virtual camera ready: {cam.device}. Select it in your meeting app.")

        async def push(jpg: bytes) -> None:
            img = cv2.imdecode(__import__("numpy").frombuffer(jpg, "uint8"), cv2.IMREAD_COLOR)
            cam.send(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))

        twin.frame_subs.append(push)
        await twin.joined()
        await twin.run()


def main(twin: Twin) -> None:
    asyncio.run(run_virtualcam(twin))
