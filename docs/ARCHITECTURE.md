# Twinvoy architecture and research notes

_October 2026_

## 1. Goal

A one-command install that produces an AI twin of the owner which can attend
meetings with the owner's face and voice, look and sound high quality, and
always be disclosed as an AI twin.

## 2. System overview

```
            enrollment (once)                         meeting (each call)
 ┌───────────────────────────────┐        ┌───────────────────────────────────────────┐
 │ consent ─► liveness challenges│        │ Recall bot (Zoom/Meet/Teams)              │
 │ (random pose order + blinks)  │        │   camera+mic = Twinvoy /camera page       │
 │ ─► best frames per angle      │        │        ▲ frames/audio      │ transcript    │
 │ ─► 30 s talking clip          │        │        │ (WebSocket)       ▼               │
 │ ─► voice sample               │        │  Twinvoy server ◄────── Brain (Claude)   │
 │ ─► signed manifest            │        │   Avatar renderer ◄─ TTS (cloned voice)   │
 └───────────────────────────────┘        │   └► DisclosedVideoSink (badge+provenance)│
                                          └───────────────────────────────────────────┘
```

## 3. Component choices (research summary)

### Talking-head / avatar

| Option | Notes | Fit |
|---|---|---|
| **MuseTalk 1.5** (open, MIT code) | Real-time lip-sync in VAE latent space; 30 fps+ on a V100, 256×256 face region, pasted back into your talking clip. Runs on modest GPUs. | **Default realistic backend** (local, private) |
| daVinci-MagiHuman (Apache 2.0, 15B) | Full generative talking head, ~2 s per clip on an H100. Too heavy for live calls today. | Future / offline |
| LiveTalking, Linly-Talker-Stream | Open WebRTC digital-human stacks bundling MuseTalk/Wav2Lip/ER-NeRF. | Reference implementations to borrow from |
| Gaussian-splat avatars (e.g. 2026 3DGS dyadic heads) | Best for true multi-angle identity from the enrollment poses; listening/nodding behaviour. Research-grade. | Phase 3 upgrade |
| **Tavus CVI** (hosted) | Replica trained from ~2 min of video; bundles turn-taking (Sparrow), perception (Raven) and rendering (Phoenix). Requires verbal consent from the person. | **Option B**: fastest route to high quality, no GPU |

Why capture all angles: lip-sync models like MuseTalk choose reference frames
whose head pose matches the target, so a range of poses improves identity
consistency when the head turns. 3D/Gaussian avatars need the multi-view data
directly.

### Voice (owner's own voice, cloned from enrollment)

| Model | Latency | License |
|---|---|---|
| Qwen3-TTS | streaming, ~97 ms synthesis | open |
| MOSS-TTS-Realtime | multi-turn streaming, OpenAI-compatible API | open |
| FlashTTS | ~325 ms first packet, zero-shot cloning | open |
| Voxtral TTS | ~100 ms TTFA | CC BY-NC (non-commercial) |

Twinvoy talks to any `/v1/audio/speech` server, so the model is swappable.

### Getting into meetings

| Option | Notes |
|---|---|
| **Recall.ai Output Media** | One API for Zoom, Meet, Teams, Webex. Renders a web page as the bot's camera + mic and exposes the live transcript to that page. Use the `web_4_core` variant to avoid choppy output. **Default.** |
| Attendee (open source) | Self-hostable meeting-bot API; Google Meet needs a full headless Chrome. Good if you want no vendor. |
| Virtual webcam (`pyvirtualcam`) | Owner is in the meeting; twin presents/answers. Name set to "(AI twin)". |

## 4. MuseTalk integration

`twinvoy/avatar/musetalk.py` loads a local MuseTalk checkout. To finish:
1. Prepare the avatar once from `enrollment/talking_clip.mp4` (MuseTalk's
   `Avatar(..., preparation=True)`), caching latents in `~/.twinvoy/musetalk`.
2. In `speak()`, port the batch loop from MuseTalk's
   `scripts/realtime_inference.py` (`Avatar.inference`) and `yield` each
   composed frame instead of writing it to disk.
3. Add GFPGAN/CodeFormer face restoration if 256×256 looks soft at 720p.

## 5. Option B: Tavus

Create a replica from the enrollment talking clip (Tavus also requires its own
consent video), create a persona with the Twinvoy system prompt, then create a
conversation. Point the Recall bot's camera page at the conversation URL
instead of `/camera`. Disclosure still applies: name, intro line and page badge.

## 6. Disclosure and legal

* EU AI Act Article 50: AI-interaction disclosure and deepfake labelling
  apply from 2 Aug 2026; machine-readable marking for existing systems by
  2 Dec 2026. Fines up to EUR 15M or 3% of turnover.
* Many organisations require bots to announce themselves and use a name
  traceable to a specific person; Twinvoy does both.
* Undisclosed use in interviews, approvals or anything where people rely on
  you being present live would be misrepresentation; the escalation rules in
  `brain.py` keep the twin out of those decisions.

## 7. Roadmap

| Phase | Deliverable |
|---|---|
| 1 (this repo) | Enrollment + liveness + consent, disclosure layer, Recall join, placeholder renderer, Claude brain, tests |
| 2 | MuseTalk real-time renderer, cloned-voice TTS server, streaming TTS → frame sync, barge-in (stop talking when interrupted) |
| 3 | Gaussian-splat avatar from multi-angle enrollment, listening behaviour (nods, gaze), calendar auto-join, post-meeting summary to owner |
| 4 | Desktop app wrapper (Tauri) with tray icon and one-click "send my twin" |

## 8. Latency budget (target < 1.5 s from end of question to first frame)

| Stage | Target |
|---|---|
| Transcript final (Recall) | 300–500 ms |
| LLM first sentence | 400–600 ms |
| TTS first audio | 100–300 ms |
| Lip-sync first frame | 50–150 ms |
| Network to page | 50–100 ms |
