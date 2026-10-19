"""Join Zoom / Google Meet / Teams through Recall.ai's Output Media API.

Recall's bot renders a web page as its camera + microphone. We point it at
our own /camera page, which streams the twin's (badge-stamped) frames and
voice, and forwards the meeting transcript back to us.
"""

from __future__ import annotations

import os

import httpx

from twinvoy.disclosure import enforce_display_name

WEB_VARIANT = {"zoom": "web_4_core", "google_meet": "web_4_core", "microsoft_teams": "web_4_core"}


def bot_payload(meeting_url: str, display_name: str, camera_page_url: str) -> dict:
    return {
        "meeting_url": meeting_url,
        "bot_name": enforce_display_name(display_name),
        "output_media": {"camera": {"kind": "webpage", "config": {"url": camera_page_url}}},
        "variant": dict(WEB_VARIANT),
    }


class RecallClient:
    def __init__(self, region: str = "us-east-1", api_key: str | None = None):
        key = api_key or os.environ.get("RECALL_API_KEY")
        if not key:
            raise RuntimeError("set RECALL_API_KEY")
        self.http = httpx.Client(base_url=f"https://{region}.recall.ai/api/v1",
                                 headers={"Authorization": f"Token {key}"}, timeout=30)

    def join(self, meeting_url: str, display_name: str, camera_page_url: str) -> dict:
        r = self.http.post("/bot/", json=bot_payload(meeting_url, display_name, camera_page_url))
        r.raise_for_status()
        return r.json()

    def status(self, bot_id: str) -> dict:
        r = self.http.get(f"/bot/{bot_id}/")
        r.raise_for_status()
        return r.json()

    def leave(self, bot_id: str) -> None:
        self.http.post(f"/bot/{bot_id}/leave_call/").raise_for_status()
