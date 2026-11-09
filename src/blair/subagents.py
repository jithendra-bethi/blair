from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import closing, suppress
from pathlib import Path, PurePosixPath
from uuid import UUID

from .adapters.models import NormalizedEvent


def should_skip_briefing(event: NormalizedEvent) -> bool:
    """Reject child or unidentified Codex events before consent and playback."""
    if event.provider == "claude":
        if event.metadata.get("agent_id"):
            return True
        transcript = event.metadata.get("transcript_path", "")
        if isinstance(transcript, str):
            parts = PurePosixPath(transcript.replace("\\", "/")).parts
            return "subagents" in parts and parts[-1].startswith("agent-")
        return False
    if event.provider != "codex":
        return False
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
    for attempt in range(2):
        try:
            background = _codex_subagent(home, event.session_id)
        except OSError:
            background = None
        if background is not None:
            return background
        if attempt == 0:
            # Give newly persisted main chats a chance to appear. Recap jobs
            # have no persisted origin and must never trigger new consent.
            time.sleep(0.15)
    return True


def _child_source(source: object) -> bool | None:
    if isinstance(source, str):
        with suppress(ValueError):
            source = json.loads(source)
    if (isinstance(source, dict) and "subagent" in source) or source == "subagent":
        return True
    if isinstance(source, str) and source in {"cli", "vscode", "exec", "appServer"}:
        return False
    return None


def _codex_subagent(home: Path, session_id: str) -> bool | None:
    databases = [p for p in home.glob("state_*.sqlite") if p.stem[6:].isdigit()]
    for path in sorted(databases, key=lambda p: int(p.stem[6:]), reverse=True):
        try:
            with closing(
                sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.05)
            ) as db:
                row = db.execute(
                    "SELECT source FROM threads WHERE id = ?", (session_id,)
                ).fetchone()
            if row and row[0] is not None:
                background = _child_source(row[0])
                if background is not None:
                    return background
        except sqlite3.Error:
            continue

    # Older installations or a temporarily unavailable index: read only the
    # matching rollout's bounded session_meta header, never its conversation.
    try:
        UUID(session_id)
    except ValueError:
        return None
    for directory in (home / "sessions", home / "archived_sessions"):
        for path in directory.rglob(f"*-{session_id}.jsonl"):
            try:
                with path.open("rb") as stream:
                    line = stream.readline(1_048_577)
                if len(line) > 1_048_576:
                    continue
                record = json.loads(line)
                if not isinstance(record, dict) or record.get("type") != "session_meta":
                    continue
                metadata = record.get("payload", {})
                if isinstance(metadata, dict) and metadata.get("id") == session_id:
                    return _child_source(metadata.get("source"))
            except (OSError, ValueError):
                continue
    return None
