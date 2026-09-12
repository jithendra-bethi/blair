from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from . import __version__
from .config import load_config, save_config
from .errors import BlairError, TtsError
from .integrations import (
    install_claude,
    install_codex,
    integration_status,
    uninstall_claude,
    uninstall_codex,
)
from .models import AgentResult
from .paths import ensure_layout
from .pipeline import BriefingPipeline
from .playback import PlaybackController
from .state import StateStore
from .tts.kokoro import ensure_models, model_directory, models_ready
from .tts.windows import WindowsSapiBackend, installed_voices


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="blair",
        description="BLAIR — local spoken briefings for terminal AI agents",
    )
    parser.add_argument("--version", action="version", version=f"BLAIR {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("on", "off", "toggle", "status", "replay"):
        command = subparsers.add_parser(name)
        command.add_argument("--session")
    subparsers.add_parser("sessions")
    subparsers.add_parser("stop")
    subparsers.add_parser("mute", help="mute all Blair speech")
    subparsers.add_parser("unmute", help="unmute speech for enabled sessions")
    subparsers.add_parser("doctor")

    daemon = subparsers.add_parser("daemon")
    daemon.add_argument("action", choices=("start", "stop", "status"))

    install = subparsers.add_parser("install", help="install safe Codex and Claude hooks")
    install.add_argument("providers", nargs="*", choices=("codex", "claude"))
    uninstall = subparsers.add_parser("uninstall", help="remove BLAIR-managed agent hooks")
    uninstall.add_argument("providers", nargs="*", choices=("codex", "claude"))

    run = subparsers.add_parser("run", help="launch an agent with session briefing consent")
    run.add_argument("provider", choices=("codex", "claude"))
    run.add_argument("--briefings", choices=("ask", "on", "off"), default="ask")

    setup = subparsers.add_parser("setup")
    setup.add_argument("--skip-models", action="store_true")
    setup.add_argument("--yes", action="store_true", help="approve the ~354 MB model download")

    demo = subparsers.add_parser("demo")
    demo.add_argument("--no-play", action="store_true")
    demo.add_argument("--wait", action="store_true")

    brief = subparsers.add_parser("brief")
    brief.add_argument("text", nargs="?")
    brief.add_argument("--file", type=Path)
    brief.add_argument("--stdin", action="store_true")
    brief.add_argument("--session", default="manual")
    brief.add_argument("--provider", default="generic")
    brief.add_argument("--no-play", action="store_true")
    brief.add_argument("--wait", action="store_true")

    config = subparsers.add_parser("config")
    config_subparsers = config.add_subparsers(dest="config_command", required=True)
    config_subparsers.add_parser("show")
    set_config = config_subparsers.add_parser("set")
    set_config.add_argument("key")
    set_config.add_argument("value")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = list(argv) if argv is not None else sys.argv[1:]
    if arguments[:1] == ["hook"]:
        from .hook_entry import run_hook

        kind = arguments[1] if len(arguments) > 1 else ""
        payload = arguments[2] if len(arguments) > 2 else None
        return run_hook(kind, payload)
    if arguments[:1] == ["_daemon"]:
        from .daemon import main as daemon_main

        return daemon_main(arguments[1:])
    parser = build_parser()
    args, extra_arguments = parser.parse_known_args(arguments)
    if args.command != "run" and extra_arguments:
        parser.error(f"unrecognized arguments: {' '.join(extra_arguments)}")
    if args.command == "run":
        if extra_arguments[:1] == ["--"]:
            extra_arguments = extra_arguments[1:]
        args.agent_args = extra_arguments
    home = ensure_layout()
    try:
        return _dispatch(args, home)
    except (BlairError, RuntimeError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"BLAIR: {exc}", file=sys.stderr)
        return 1


def _dispatch(args: argparse.Namespace, home: Path) -> int:
    state = StateStore(home)
    session_id = getattr(args, "session", None) or os.environ.get("BLAIR_SESSION_ID")
    if args.command in {"mute", "unmute"}:
        muted = PlaybackController(home).set_muted(args.command == "mute")
        print(
            "Blair speech is muted everywhere."
            if muted
            else "Blair speech is unmuted. Enabled sessions can speak."
        )
        return 0
    if args.command in {"on", "off", "toggle"}:
        existing = state.get(session_id)
        if existing is None:
            session_id = session_id or "manual"
            existing = state.ensure_session(session_id)
        enabled = args.command == "on" or (
            args.command == "toggle" and existing.enabled is not True
        )
        state.set_enabled(enabled, existing.session_id)
        if not enabled:
            PlaybackController(home).stop()
        print(
            f"Briefing Protocol {'enabled' if enabled else 'disabled'} for {existing.session_id}."
        )
        return 0
    if args.command == "status":
        print("Blair speech: " + ("muted globally" if state.is_speech_muted() else "unmuted"))
        existing = state.get(session_id)
        if not existing:
            print("Briefing Protocol has no active session.")
        else:
            status = (
                "enabled"
                if existing.enabled
                else "disabled"
                if existing.enabled is False
                else "not answered"
            )
            print(f"{existing.provider}:{existing.session_id} — {status}")
        return 0
    if args.command == "sessions":
        sessions = state.sessions()
        if not sessions:
            print("No BLAIR sessions have been seen.")
        for item in sessions:
            status = "on" if item.enabled else "off" if item.enabled is False else "ask"
            print(f"{item.provider}:{item.session_id}\t{status}\t{item.updated_at}")
        return 0
    if args.command == "stop":
        stopped = PlaybackController(home).stop()
        print("Speech stop requested." if stopped else "No BLAIR speech is playing.")
        return 0
    if args.command == "replay":
        existing = state.get(session_id)
        if not existing or not existing.last_audio or not Path(existing.last_audio).exists():
            raise BlairError("No briefing is available for this session")
        if PlaybackController(home).play(Path(existing.last_audio)) is None:
            print("Blair speech is muted. Run 'blair unmute' to resume speech.")
            return 0
        print(existing.last_briefing or "Replaying the last briefing.")
        return 0
    if args.command == "doctor":
        return _doctor(home)
    if args.command == "daemon":
        return _daemon_command(args.action, home)
    if args.command in {"install", "uninstall"}:
        return _integration_command(args.command, args.providers)
    if args.command == "run":
        return _run_agent(args.provider, args.briefings, args.agent_args)
    if args.command == "setup":
        return _setup(home, skip_models=args.skip_models, assume_yes=args.yes)
    if args.command == "demo":
        text = (
            "Implemented the Windows briefing pipeline and updated the session controls.\n\n"
            "| Check | Result |\n"
            "| --- | --- |\n"
            "| Unit tests | Passed |\n"
            "| Privacy | Local only |\n\n"
            "All tests passed successfully."
        )
        return _speak_text(text, "blair-demo", "demo", home, args.no_play, args.wait)
    if args.command == "brief":
        text = _read_brief_text(args)
        return _speak_text(text, args.session, args.provider, home, args.no_play, args.wait)
    if args.command == "config":
        return _config_command(args, home)
    raise BlairError(f"Unknown command: {args.command}")


def _speak_text(
    text: str,
    session_id: str,
    provider: str,
    home: Path,
    no_play: bool,
    wait: bool,
) -> int:
    outcome = BriefingPipeline(home=home).handle(
        AgentResult(session_id=session_id, text=text, provider=provider),
        explicit=True,
        play=not no_play,
        wait=wait,
    )
    if outcome.reason == "speech-muted":
        print("Blair speech is muted. Run 'blair unmute' to resume speech.")
        return 0
    if outcome.briefing:
        print(outcome.briefing.text)
    if outcome.artifact:
        print(
            f"Audio: {outcome.artifact.path} [{outcome.artifact.backend}, {outcome.artifact.voice}]"
        )
    return 0


def _read_brief_text(args: argparse.Namespace) -> str:
    choices = sum(bool(value) for value in (args.text, args.file, args.stdin))
    if choices != 1:
        raise BlairError("Provide exactly one of text, --file, or --stdin")
    if args.file:
        return args.file.read_text(encoding="utf-8")
    if args.stdin:
        return sys.stdin.read()
    return str(args.text)


def _doctor(home: Path) -> int:
    from .daemon import daemon_pid

    config = load_config(home)
    model_dir = model_directory(home)
    adapters = integration_status()
    voices = installed_voices()
    checks = {
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "home": str(home),
        "home_writable": os.access(home, os.W_OK),
        "codex": shutil.which("codex") or "missing",
        "claude": shutil.which("claude") or "missing",
        "windows_sapi": WindowsSapiBackend().available(),
        "windows_voices": "; ".join(voices) if voices else "none detected",
        "kokoro_package": importlib.util.find_spec("kokoro_onnx") is not None,
        "kokoro_models": models_ready(model_dir),
        "selected_backend": config.backend,
        "voice": config.voice,
        "codex_hook": adapters["codex"],
        "claude_hooks": adapters["claude"],
        "daemon_pid": daemon_pid(home) or "stopped",
    }
    for key, value in checks.items():
        print(f"{key}: {value}")
    essential = checks["home_writable"] and (checks["windows_sapi"] or checks["kokoro_package"])
    return 0 if essential else 1


def _daemon_command(action: str, home: Path) -> int:
    from .daemon import daemon_pid, start_daemon, stop_daemon

    if action == "start":
        pid = start_daemon(home)
        print(f"BLAIR background service is starting (PID {pid}).")
        return 0
    if action == "stop":
        stopped = stop_daemon(home)
        print("BLAIR background service stopped." if stopped else "BLAIR service was not running.")
        return 0
    pid = daemon_pid(home)
    print(
        f"BLAIR background service is running (PID {pid})." if pid else "BLAIR service is stopped."
    )
    return 0


def _integration_command(action: str, providers: list[str]) -> int:
    selected = providers or ["codex", "claude"]
    operations = {
        ("install", "codex"): install_codex,
        ("install", "claude"): install_claude,
        ("uninstall", "codex"): uninstall_codex,
        ("uninstall", "claude"): uninstall_claude,
    }
    failures = 0
    for provider in selected:
        try:
            result = operations[(action, provider)]()
        except BlairError as exc:
            print(f"{provider}: {exc}", file=sys.stderr)
            failures += 1
            continue
        changed = "changed" if result.changed else "unchanged"
        print(f"{provider}: {result.detail} ({changed}) — {result.path}")
        if result.backup:
            print(f"  backup: {result.backup}")
    if not failures:
        from .daemon import start_daemon, stop_daemon

        if action == "install":
            pid = start_daemon()
            print(f"BLAIR background service is ready (PID {pid}); it has no microphone access.")
        else:
            stop_daemon()
    return 1 if failures else 0


def _run_agent(provider: str, briefings: str, agent_args: list[str]) -> int:
    installed = integration_status()[provider]
    if not installed:
        raise BlairError(
            f"{provider} hooks are not installed; run 'blair install {provider}' first"
        )
    executable = shutil.which(provider)
    if not executable:
        raise BlairError(f"{provider} executable was not found on PATH")

    if agent_args[:1] == ["--"]:
        agent_args = agent_args[1:]
    selection = briefings
    if selection == "ask":
        if sys.stdin.isatty():
            answer = input(
                f"BLAIR: Speak concise completion briefings for this {provider} session? [y/N] "
            )
            selection = "on" if answer.strip().casefold() in {"y", "yes"} else "off"
        else:
            selection = "off"
    environment = os.environ.copy()
    environment["BLAIR_CONSENT_RESPONSE"] = "yes" if selection == "on" else "no"
    environment["BLAIR_LAUNCH_ID"] = str(uuid4())
    completed = subprocess.run([executable, *agent_args], env=environment, check=False)
    return completed.returncode


def _setup(home: Path, *, skip_models: bool, assume_yes: bool) -> int:
    config = load_config(home)
    save_config(config, home)
    if skip_models:
        print(f"BLAIR configuration ready at {home}.")
        return 0
    if importlib.util.find_spec("kokoro_onnx") is None:
        raise TtsError(
            "Kokoro package is missing. Install with: pip install 'blair-briefing[kokoro]'"
        )
    model_dir = model_directory(home)
    if not models_ready(model_dir) and not assume_yes:
        if not sys.stdin.isatty():
            raise TtsError("Kokoro setup needs download approval; rerun with 'blair setup --yes'")
        answer = input("Download and verify about 354 MB of local Kokoro voice files? [y/N] ")
        if answer.strip().casefold() not in {"y", "yes"}:
            print("Kokoro download cancelled. Windows speech remains available.")
            return 0
    ensure_models(model_dir, print)
    print("BLAIR is ready. Run 'blair demo --wait'.")
    return 0


def _config_command(args: argparse.Namespace, home: Path) -> int:
    config = load_config(home)
    if args.config_command == "show":
        print(
            json.dumps({key: getattr(config, key) for key in config.__dataclass_fields__}, indent=2)
        )
        return 0
    if not hasattr(config, args.key):
        raise BlairError(f"Unknown configuration key: {args.key}")
    current = getattr(config, args.key)
    value: object = args.value
    if isinstance(current, bool):
        value = args.value.casefold() in {"true", "1", "yes", "on"}
    elif isinstance(current, int):
        value = int(args.value)
    elif isinstance(current, float):
        value = float(args.value)
    setattr(config, args.key, value)
    save_config(config, home)
    print(f"{args.key} = {value}")
    if args.key == "hotkeys_enabled" or args.key.startswith("hotkey_"):
        print("Saved. Restart hotkeys with 'blair daemon stop' then 'blair daemon start'.")
    else:
        print("Saved. Applies when the next briefing starts; current speech is unchanged.")
    return 0
