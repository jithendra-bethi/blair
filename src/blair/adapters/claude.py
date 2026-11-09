from __future__ import annotations

from typing import Any
from uuid import uuid4

from ._json import (
    load_json_object,
    optional_bool,
    optional_list,
    optional_string,
    required_string,
)
from .errors import UnsupportedEventError
from .models import NormalizedEvent

CLAUDE_STOP_EVENT = "Stop"
CLAUDE_FAILURE_EVENT = "StopFailure"
_SUPPORTED_EVENTS = {CLAUDE_STOP_EVENT, CLAUDE_FAILURE_EVENT}


def parse_claude_hook(payload: str) -> NormalizedEvent:
    """Normalize a Claude Code Stop or StopFailure JSON stdin payload."""

    decoded = load_json_object(payload, source="Claude")
    event_name = required_string(decoded, "hook_event_name", source="Claude", strip=True)
    if event_name not in _SUPPORTED_EVENTS:
        raise UnsupportedEventError("unsupported Claude hook event")

    session_id = required_string(decoded, "session_id", source="Claude", strip=True)
    cwd = optional_string(decoded, "cwd", source="Claude")
    metadata = _common_metadata(decoded)

    if event_name == CLAUDE_STOP_EVENT:
        text = required_string(decoded, "last_assistant_message", source="Claude")
        metadata.update(_background_metadata(decoded))
        metadata["failed"] = False
    else:
        text = _failure_text(decoded)
        metadata.update(_failure_metadata(decoded))
        metadata["background_pending"] = None
        metadata["failed"] = True

    return NormalizedEvent(
        event_id=str(uuid4()),
        provider="claude",
        session_id=session_id,
        text=text,
        event_name=event_name,
        cwd=cwd,
        metadata=metadata,
    )


def _common_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in ("transcript_path", "permission_mode", "agent_id"):
        value = optional_string(payload, key, source="Claude")
        if value is not None:
            metadata[key] = value

    stop_hook_active = optional_bool(payload, "stop_hook_active", source="Claude")
    if stop_hook_active is not None:
        metadata["stop_hook_active"] = stop_hook_active
    return metadata


def _background_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    tasks_value = optional_list(payload, "background_tasks", source="Claude")
    crons_value = optional_list(payload, "session_crons", source="Claude")
    tasks = list(tasks_value or [])
    crons = list(crons_value or [])

    if tasks or crons:
        pending: bool | None = True
    elif tasks_value is not None and crons_value is not None:
        pending = False
    else:
        pending = None

    return {
        "background_tasks": tasks,
        "session_crons": crons,
        "background_pending": pending,
    }


def _failure_text(payload: dict[str, Any]) -> str:
    error = required_string(payload, "error", source="Claude", strip=True)
    message = optional_string(payload, "message", source="Claude")
    details = optional_string(payload, "details", source="Claude")
    legacy_message = optional_string(payload, "last_assistant_message", source="Claude")
    legacy_details = optional_string(payload, "error_details", source="Claude")
    explanation = next(
        (
            value.strip()
            for value in (message, details, legacy_message, legacy_details)
            if value is not None and value.strip()
        ),
        None,
    )
    error_label = error.replace("_", " ")
    if explanation is not None:
        return f"Agent turn failed ({error_label}): {explanation}"
    return f"Agent turn failed: {error_label}."


def _failure_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    error = required_string(payload, "error", source="Claude", strip=True)
    metadata: dict[str, Any] = {"error": error}
    for key in ("details", "message", "error_details", "last_assistant_message"):
        value = optional_string(payload, key, source="Claude")
        if value is not None:
            metadata[key] = value
    return metadata
