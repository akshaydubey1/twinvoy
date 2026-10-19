"""Decides whether and what the twin says, grounded in the owner's notes.

Policy:
* Only reply when addressed (owner's first name or "twin") or asked a direct
  question it can answer from the knowledge notes.
* Never makes commitments: anything matching an escalation keyword gets
  "I'll check with <owner> and get back to you" and is logged for the owner.
* Never claims to be human (also enforced by SpeechGate).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

SYSTEM = """You are the AI twin of {owner}, attending a meeting on their behalf.
Everyone in the meeting has been told you are an AI twin. Never claim or imply
you are {first} in person or a human.

Rules:
- Speak briefly (1-3 sentences), in a natural, friendly, professional tone.
- Answer only from the NOTES below or the meeting transcript. If unsure, say
  you'll check with {first}.
- Never agree to deadlines, approvals, budgets, contracts, offers or anything
  binding; say {first} will follow up.
- If asked whether you are an AI or a real person, say plainly you are {first}'s AI twin.

NOTES:
{notes}
"""


@dataclass
class Utterance:
    speaker: str
    text: str


@dataclass
class Decision:
    reply: str | None
    escalate: bool = False
    reason: str = ""


@dataclass
class Brain:
    owner: str
    escalate_keywords: list[str]
    notes: str = ""
    llm: Callable[[str, list[dict]], str] | None = None
    history: list[Utterance] = field(default_factory=list)
    followups: list[str] = field(default_factory=list)

    @property
    def first(self) -> str:
        return self.owner.split()[0]

    def addressed(self, text: str) -> bool:
        t = text.lower()
        return bool(re.search(rf"\b({re.escape(self.first.lower())}|twin)\b", t))

    def needs_escalation(self, text: str) -> bool:
        t = text.lower()
        return any(k in t for k in self.escalate_keywords)

    def hear(self, u: Utterance) -> Decision:
        self.history.append(u)
        self.history = self.history[-60:]
        if not self.addressed(u.text):
            return Decision(None, reason="not addressed")
        if self.needs_escalation(u.text):
            self.followups.append(f"{u.speaker}: {u.text}")
            return Decision(
                f"Good question, I'll make sure {self.first} sees that and gets back to you directly.",
                escalate=True, reason="escalation keyword",
            )
        if self.llm is None:
            return Decision(f"Thanks, I've noted that for {self.first}.", reason="no llm")
        msgs = [{"role": "user", "content": "\n".join(f"{h.speaker}: {h.text}" for h in self.history[-20:])
                 + "\n\nReply as the AI twin, or reply exactly SKIP if no reply is needed."}]
        out = self.llm(SYSTEM.format(owner=self.owner, first=self.first, notes=self.notes or "(none)"), msgs).strip()
        return Decision(None if out == "SKIP" else out, reason="llm")


def load_notes(path: str) -> str:
    if not path:
        return ""
    p = Path(path).expanduser()
    files = [p] if p.is_file() else sorted(p.glob("**/*.md")) + sorted(p.glob("**/*.txt"))
    text = "\n\n".join(f.read_text(errors="ignore") for f in files)
    return text[:60_000]


def anthropic_llm(model: str) -> Callable[[str, list[dict]], str]:
    import anthropic
    client = anthropic.Anthropic()

    def call(system: str, messages: list[dict]) -> str:
        r = client.messages.create(model=model, max_tokens=300, system=system, messages=messages)
        return "".join(b.text for b in r.content if getattr(b, "type", "") == "text")

    return call
