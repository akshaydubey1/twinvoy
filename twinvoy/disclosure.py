"""Disclosure enforcement.

Everything the twin shows or says passes through this module:

* display names always carry an "AI twin" marker,
* every outgoing video frame is stamped with a visible badge,
* the first utterance in a meeting is a spoken disclosure,
* every frame batch carries a provenance record (EU AI Act Art. 50(2) style
  machine-readable marking).

These are deliberately not configurable. Removing them turns the tool into an
impersonation device, which this project does not support.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

AI_MARKER = "(AI twin)"
_MARKER_PATTERNS = ("ai twin", "ai avatar", "ai assistant", "(ai)")

BADGE_TEXT = "AI TWIN"


class DisclosureError(ValueError):
    """Raised when something would present the twin as a live human."""


def has_marker(name: str) -> bool:
    lower = name.lower()
    return any(p in lower for p in _MARKER_PATTERNS)


def enforce_display_name(name: str) -> str:
    """Return a meeting display name that discloses the twin."""
    name = " ".join(name.split())
    if not name:
        raise DisclosureError("display name cannot be empty")
    return name if has_marker(name) else f"{name} {AI_MARKER}"


def intro_line(owner_name: str) -> str:
    first = owner_name.split()[0] if owner_name.strip() else "the owner"
    return (
        f"Hi everyone, I'm {first}'s AI twin, joining on {first}'s behalf. "
        f"I'm taking notes and can answer some questions, and I'll pass "
        f"anything that needs a decision to {first} directly."
    )


def stamp_frame(frame: np.ndarray, owner_name: str) -> np.ndarray:
    """Draw the disclosure badge onto a BGR frame (in place) and return it.

    The badge is sized relative to the frame so it stays legible after the
    meeting platform downscales the tile.
    """
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("expected an HxWx3 BGR frame")
    h, w = frame.shape[:2]
    scale = max(h, 240) / 720.0
    pad = int(14 * scale)
    font = cv2.FONT_HERSHEY_SIMPLEX
    label = f"{BADGE_TEXT}  |  {owner_name}" if owner_name else BADGE_TEXT
    fs = 0.9 * scale
    th = max(1, int(2 * scale))
    (tw, tht), base = cv2.getTextSize(label, font, fs, th)
    x0, y0 = pad, pad
    x1, y1 = x0 + tw + 2 * pad, y0 + tht + base + 2 * pad
    overlay = frame.copy()
    cv2.rectangle(overlay, (x0, y0), (min(x1, w - 1), min(y1, h - 1)), (40, 40, 200), -1)
    cv2.addWeighted(overlay, 0.85, frame, 0.15, 0, dst=frame)
    cv2.putText(frame, label, (x0 + pad, y0 + pad + tht), font, fs, (255, 255, 255), th, cv2.LINE_AA)
    # thin border so the tile reads as synthetic even when the badge is cropped
    cv2.rectangle(frame, (0, 0), (w - 1, h - 1), (40, 40, 200), max(2, int(4 * scale)))
    return frame


@dataclass
class ProvenanceLog:
    """Machine-readable record that the outgoing media is AI-generated."""

    owner: str
    generator: str
    entries: list[dict] = field(default_factory=list)
    _chain: str = "genesis"

    def record(self, frame: np.ndarray) -> dict:
        digest = hashlib.sha256(frame.tobytes()).hexdigest()[:16]
        self._chain = hashlib.sha256((self._chain + digest).encode()).hexdigest()[:16]
        entry = {
            "t": round(time.time(), 3),
            "ai_generated": True,
            "generator": self.generator,
            "owner": self.owner,
            "frame": digest,
            "chain": self._chain,
        }
        self.entries.append(entry)
        return entry

    def dumps(self) -> str:
        return "\n".join(json.dumps(e) for e in self.entries)


class DisclosedVideoSink:
    """The only path from an avatar renderer to the meeting.

    Wraps any `write(frame)` callable so every frame is stamped and logged.
    """

    def __init__(self, write, owner_name: str, generator: str, log_every: int = 25):
        self._write = write
        self._owner = owner_name
        self.provenance = ProvenanceLog(owner=owner_name, generator=generator)
        self._n = 0
        self._log_every = max(1, log_every)

    def write(self, frame: np.ndarray) -> None:
        frame = stamp_frame(np.ascontiguousarray(frame), self._owner)
        if self._n % self._log_every == 0:
            self.provenance.record(frame)
        self._n += 1
        self._write(frame)


class SpeechGate:
    """Blocks the twin from speaking until its disclosure has been spoken."""

    def __init__(self, owner_name: str):
        self.owner_name = owner_name
        self.disclosed = False

    def first_utterance(self) -> str:
        self.disclosed = True
        return intro_line(self.owner_name)

    def check(self, text: str) -> str:
        if not self.disclosed:
            raise DisclosureError("the twin must speak its disclosure first")
        lowered = text.lower()
        for claim in ("i am not an ai", "i'm not an ai", "i am a real person",
                      "i'm a real person", "i am human", "i'm human",
                      "this is really me", "i'm not a bot", "i am not a bot"):
            if claim in lowered:
                raise DisclosureError(f"refusing to claim to be human: {claim!r}")
        return text
