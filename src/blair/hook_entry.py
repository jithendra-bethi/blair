from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from .adapters import (
    MAX_PAYLOAD_BYTES,
    parse_claude_hook,
    parse_codex_notification,
    parse_generic_event,
)
from .daemon import enqueue_event
from .paths import blair_home, ensure_layout


def run_hook(kind: str, argument: str | None = None, *, home: Path | None = None) -> int:
    """Provider hook entry point. It deliberately never emits output or fails the agent."""

    root = home or blair_home()
    try:
        ensure_layout(root)
        if kind == "codex-notify":
            if argument is None:
                raise ValueError("missing Codex payload")
            event = parse_codex_notification(argument)
        elif kind in {"claude-stop", "claude-failure", "claude"}:
            event = parse_claude_hook(_read_stdin_bounded())
        elif kind == "generic":
            event = parse_generic_event(_read_stdin_bounded())
        else:
            raise ValueError("unknown hook kind")
        event.metadata.pop("consent_override", None)
        event.metadata.pop("launch_id", None)
        forced = os.environ.get("BLAIR_CONSENT_RESPONSE", "").strip().casefold()
        launch_id = os.environ.get("BLAIR_LAUNCH_ID", "").strip()
        if launch_id and forced in {"yes", "y", "true", "1", "on", "no", "n", "false", "0", "off"}:
            event.metadata["launch_id"] = launch_id
            event.metadata["consent_override"] = forced in {"yes", "y", "true", "1", "on"}
        enqueue_event(event, root)
    except Exception as exc:  # Provider integrations must always fail open.
        _record_failure(root, kind, exc)
    return 0


def _read_stdin_bounded() -> str:
    payload = sys.stdin.buffer.read(MAX_PAYLOAD_BYTES + 1)
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise ValueError("hook payload is too large")
    return payload.decode("utf-8")


def _record_failure(home: Path, kind: str, error: BaseException) -> None:
    record = {
        "time": datetime.now(UTC).isoformat(),
        "action": "hook-failed-open",
        "kind": kind,
        "error_type": type(error).__name__,
    }
    try:
        with (home / "logs" / "blair.log").open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError:
        pass
