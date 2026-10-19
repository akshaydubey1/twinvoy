import numpy as np
import pytest

from twinvoy.config import TwinConfig
from twinvoy.disclosure import (
    DisclosedVideoSink, DisclosureError, SpeechGate, enforce_display_name, stamp_frame,
)
from twinvoy.meeting.recall import bot_payload


def test_display_name_always_disclosed():
    assert enforce_display_name("Akshay D") == "Akshay D (AI twin)"
    assert enforce_display_name("Akshay (AI twin)") == "Akshay (AI twin)"
    with pytest.raises(DisclosureError):
        enforce_display_name("   ")


def test_config_cannot_set_undisclosed_name():
    cfg = TwinConfig.model_validate({"owner": {"full_name": "Akshay D"},
                                     "meeting": {"display_name": "Akshay D"}})
    assert cfg.resolved_display_name() == "Akshay D (AI twin)"


def test_recall_payload_forces_marker():
    p = bot_payload("https://zoom.us/j/1", "Akshay D", "https://x/camera")
    assert p["bot_name"].endswith("(AI twin)")
    assert p["output_media"]["camera"]["kind"] == "webpage"


def test_every_frame_is_stamped():
    out = []
    sink = DisclosedVideoSink(out.append, "Akshay D", "test", log_every=1)
    blank = np.zeros((360, 640, 3), np.uint8)
    for _ in range(3):
        sink.write(blank.copy())
    assert len(out) == 3
    for f in out:
        assert f[20:40, 20:60].any(), "badge area should not be blank"
        assert f[0, 320].any(), "border should be drawn"
    assert len(sink.provenance.entries) == 3
    assert all(e["ai_generated"] for e in sink.provenance.entries)


def test_stamp_rejects_bad_shape():
    with pytest.raises(ValueError):
        stamp_frame(np.zeros((10, 10), np.uint8), "x")


def test_speech_gate():
    g = SpeechGate("Akshay D")
    with pytest.raises(DisclosureError):
        g.check("hello")
    intro = g.first_utterance()
    assert "AI twin" in intro
    assert g.check("Sounds good.") == "Sounds good."
    with pytest.raises(DisclosureError):
        g.check("Don't worry, I'm a real person.")
