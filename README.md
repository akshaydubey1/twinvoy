# Twinvoy

**Your face. Your voice. Clearly labeled.**

Twinvoy is an AI envoy that looks and sounds like you, attends meetings on your behalf, and always says it is your AI twin.

An AI twin of **you** that can join Zoom, Google Meet and Microsoft Teams
meetings with your face and voice. It always identifies itself as an AI twin.

```
curl -fsSL <your-host>/install.sh | bash     # or: pip install .
twinvoy init        # your name -> meeting name "Akshay D (AI twin)"
twinvoy enroll      # consent + guided face capture from all angles
twinvoy preview     # render a sample clip of the twin talking
twinvoy doctor      # what's still missing
twinvoy join https://zoom.us/j/123... --public-url https://<tunnel>
```

## What it does

1. **Enrollment** (`twinvoy enroll`): you type a consent statement, then the
   camera guides you through front, left, right, up and down poses in a random
   order and asks you to blink. Random order + blink = liveness, so it only
   works with the live person at the camera, never with someone's photos.
   The best frames per angle and a 30 s talking clip become the avatar's
   reference material. A tamper-evident `manifest.json` records all of it.
2. **Avatar**: renders your face lip-synced to speech.
   * `placeholder` (default, CPU): proves the pipeline works end to end.
   * `musetalk` (NVIDIA GPU): realistic real-time lip-sync. Run
     `scripts/setup_musetalk.sh`.
   * Tavus (hosted): see `docs/ARCHITECTURE.md`, Option B.
3. **Voice**: any OpenAI-compatible `/v1/audio/speech` server running a voice
   cloned from *your* enrollment sample (e.g. MOSS-TTS, Qwen3-TTS).
4. **Brain**: Claude, grounded in your notes folder. Speaks only when
   addressed, never commits you to anything (approvals, budgets, offers) and
   logs those as follow-ups for you at `/followups`.
5. **Joining**: Recall.ai's Output Media bot renders Twinvoy's camera page
   as its webcam and mic. `twinvoy local` instead feeds a virtual webcam.

## Disclosure is built in

These are enforced in code and covered by tests:

| Where | What |
|---|---|
| Meeting name | always ends in "(AI twin)" |
| Video | every frame stamped with an "AI TWIN" badge and border, plus a second badge on the camera page |
| Speech | the first thing it says is that it's your AI twin; it can't speak before that, and any reply claiming to be human is replaced |
| Provenance | hash-chained, machine-readable log marking output as AI-generated |
| Enrollment | live camera only, consent required, no photo import |

This lines up with Zoom/Teams/Meet bot norms and with EU AI Act Article 50,
which has required AI-interaction and deepfake disclosure since 2 Aug 2026.

## Environment

| Variable | Needed for |
|---|---|
| `RECALL_API_KEY` | `join` |
| `ANTHROPIC_API_KEY` | the twin answering questions (otherwise it only takes notes) |
| `TWINVOY_HOME` | optional, defaults to `~/.twinvoy` |

Run tests with `pip install .[dev] && pytest`.
