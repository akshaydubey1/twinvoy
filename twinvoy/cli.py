"""twinvoy command line."""

from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

import click
import yaml

from twinvoy.config import DEFAULT_HOME, TwinConfig, load_config

CONFIG = DEFAULT_HOME / "config.yaml"


def _cfg(path: str | None) -> TwinConfig:
    p = Path(path) if path else CONFIG
    if not p.exists():
        raise click.ClickException(f"no config at {p}; run `twinvoy init` first")
    return load_config(p)


@click.group()
@click.version_option()
def main() -> None:
    """Your disclosed AI meeting twin."""


@main.command()
@click.option("--name", prompt="Your full name")
@click.option("--email", prompt="Your email", default="")
def init(name: str, email: str) -> None:
    """Create ~/.twinvoy/config.yaml."""
    DEFAULT_HOME.mkdir(parents=True, exist_ok=True)
    cfg = TwinConfig.model_validate({"owner": {"full_name": name, "email": email}})
    data = cfg.model_dump(mode="json", exclude={"home"})
    CONFIG.write_text(yaml.safe_dump(data, sort_keys=False))
    click.echo(f"Wrote {CONFIG}. Meeting name will be: {cfg.resolved_display_name()}")


@main.command()
@click.option("--config", "config_path", default=None)
@click.option("--camera", default=0, show_default=True)
@click.option("--clip-seconds", default=30, show_default=True)
def enroll(config_path: str | None, camera: int, clip_seconds: int) -> None:
    """Consent + guided multi-angle face capture with liveness checks."""
    from twinvoy.camera import LiveCamera, ensure_landmarker_model, record_talking_clip
    from twinvoy.enroll import CONSENT_TEMPLATE, EnrollmentFailed, EnrollmentSession

    cfg = _cfg(config_path)
    statement = CONSENT_TEMPLATE.format(name=cfg.owner.full_name)
    click.echo("\nType this consent statement exactly:\n\n  " + statement + "\n")
    typed = click.prompt("Consent")
    sess = EnrollmentSession(cfg.owner.full_name, cfg.enrollment_dir)
    try:
        sess.record_consent(typed)
    except ValueError as e:
        raise click.ClickException(str(e))
    cam = LiveCamera(ensure_landmarker_model(cfg.home), index=camera)
    try:
        res = sess.run(cam, on_prompt=cam.set_prompt)
    except EnrollmentFailed as e:
        raise click.ClickException(f"Enrollment failed: {e}. Try again in good, even light.")
    finally:
        cam.close()
    click.echo("Now recording a short talking clip for lip-sync models.")
    record_talking_clip(cfg.enrollment_dir / "talking_clip.mp4", clip_seconds, camera)
    click.echo(f"Done. {sum(len(v) for v in res.captures.values())} reference images, "
               f"manifest {res.manifest_sha256[:12]}")


def _build_twin(cfg: TwinConfig):
    from twinvoy.avatar import make_renderer
    from twinvoy.brain import Brain, anthropic_llm, load_notes
    from twinvoy.enroll import load_manifest
    from twinvoy.orchestrator import Twin
    from twinvoy.voice import make_tts
    import os

    load_manifest(cfg.enrollment_dir)  # refuses to run without a valid, consented enrollment
    llm = anthropic_llm(cfg.brain.model) if os.environ.get("ANTHROPIC_API_KEY") else None
    brain = Brain(cfg.owner.full_name, cfg.brain.escalate_keywords,
                  load_notes(cfg.brain.knowledge_dir), llm)
    return Twin(cfg.owner.full_name, make_renderer(cfg), make_tts(cfg), brain)


@main.command()
@click.argument("meeting_url")
@click.option("--config", "config_path", default=None)
@click.option("--port", default=8765, show_default=True)
@click.option("--public-url", default=None, help="HTTPS URL that tunnels to --port (e.g. cloudflared)")
def join(meeting_url: str, config_path: str | None, port: int, public_url: str | None) -> None:
    """Send your AI twin into a Zoom / Meet / Teams meeting via Recall.ai."""
    import uvicorn
    from twinvoy.meeting.recall import RecallClient
    from twinvoy.meeting.server import create_app

    cfg = _cfg(config_path)
    base = (public_url or cfg.meeting.public_base_url).rstrip("/")
    if not base.startswith("https://"):
        raise click.ClickException("need --public-url https://... (run `cloudflared tunnel --url "
                                   f"http://localhost:{port}`)")
    twin = _build_twin(cfg)
    app = create_app(twin)
    page = f"{base}/camera?token={app.state.token}"

    async def go() -> None:
        server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning"))
        task = asyncio.create_task(server.serve())
        await asyncio.sleep(1.5)
        bot = await asyncio.to_thread(RecallClient(cfg.meeting.recall_region).join,
                                      meeting_url, cfg.resolved_display_name(), page)
        click.echo(f"Twin joining as '{cfg.resolved_display_name()}' (bot {bot.get('id')}). Ctrl+C to stop.")
        await task

    asyncio.run(go())


@main.command()
@click.option("--config", "config_path", default=None)
@click.option("--port", default=8765, show_default=True)
def serve(config_path: str | None, port: int) -> None:
    """Local test: watch your twin in a browser and type questions to it."""
    import uvicorn
    import webbrowser
    from twinvoy.meeting.server import create_app

    cfg = _cfg(config_path)
    app = create_app(_build_twin(cfg))
    url = f"http://localhost:{port}/camera?token={app.state.token}&test=1"
    click.echo(f"Open {url}\nType as a participant at the bottom of the page. Ctrl+C to stop.")
    webbrowser.open(url)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


@main.command()
@click.option("--config", "config_path", default=None)
def local(config_path: str | None) -> None:
    """Stream the twin to a virtual webcam on this computer."""
    from twinvoy.meeting.virtualcam import main as vc

    cfg = _cfg(config_path)
    click.echo(f"Set your meeting display name to: {cfg.resolved_display_name()}")
    vc(_build_twin(cfg))


@main.command()
@click.option("--config", "config_path", default=None)
@click.option("--out", default="twin_preview.mp4", show_default=True)
@click.option("--text", default=None)
def preview(config_path: str | None, out: str, text: str | None) -> None:
    """Render a short preview video of the twin speaking (with disclosure)."""
    import cv2
    from twinvoy.avatar import make_renderer
    from twinvoy.disclosure import DisclosedVideoSink, intro_line
    from twinvoy.voice import make_tts

    cfg = _cfg(config_path)
    r, tts = make_renderer(cfg), make_tts(cfg)
    text = text or intro_line(cfg.owner.full_name)
    pcm = tts.synthesize(text)
    frames = []
    sink = DisclosedVideoSink(frames.append, cfg.owner.full_name, r.name)
    for f in r.speak(pcm, tts.sample_rate):
        sink.write(f)
    h, w = frames[0].shape[:2]
    vw = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*"mp4v"), r.fps, (w, h))
    for f in frames:
        vw.write(f)
    vw.release()
    Path(out).with_suffix(".provenance.jsonl").write_text(sink.provenance.dumps())
    click.echo(f"Wrote {out} ({len(frames)} frames)")


@main.command()
@click.option("--config", "config_path", default=None)
def doctor(config_path: str | None) -> None:
    """Check that everything needed is installed and configured."""
    import importlib
    import os

    def row(ok: bool, label: str, hint: str = "") -> None:
        click.echo(f"  [{'ok' if ok else '!!'}] {label}" + (f"  -> {hint}" if hint and not ok else ""))

    click.echo("Twinvoy doctor")
    row(sys.version_info >= (3, 10), f"Python {sys.version.split()[0]}", "need 3.10+")
    for mod in ("cv2", "mediapipe", "fastapi", "uvicorn", "httpx"):
        try:
            importlib.import_module(mod)
            row(True, mod)
        except ImportError:
            row(False, mod, "pip install twinvoy")
    row(shutil.which("cloudflared") is not None, "cloudflared (public tunnel for `join`)",
        "install cloudflared, or set meeting.public_base_url")
    row(bool(os.environ.get("RECALL_API_KEY")), "RECALL_API_KEY", "needed for `join`")
    row(bool(os.environ.get("ANTHROPIC_API_KEY")), "ANTHROPIC_API_KEY", "twin will only take notes without it")
    if CONFIG.exists() or config_path:
        cfg = _cfg(config_path)
        row(True, f"config ({cfg.resolved_display_name()})")
        try:
            from twinvoy.enroll import load_manifest
            load_manifest(cfg.enrollment_dir)
            row(True, "enrollment")
        except Exception as e:
            row(False, "enrollment", f"run `twinvoy enroll` ({e})")
        if cfg.avatar.backend == "musetalk":
            try:
                from twinvoy.avatar import make_renderer
                make_renderer(cfg)
                row(True, "MuseTalk")
            except Exception as e:
                row(False, "MuseTalk", str(e))
    else:
        row(False, "config", "run `twinvoy init`")


if __name__ == "__main__":
    main()
