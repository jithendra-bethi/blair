from __future__ import annotations

from typing import Any

from ._json import load_json_object, optional_list, optional_string, required_string
from .errors import InvalidPayloadError, UnsupportedEventError
from .models import NormalizedEvent

CODEX_COMPLETION_EVENT = "agent-turn-complete"


def parse_codex_notification(payload: str) -> NormalizedEvent:
    """Normalize the single JSON argv value emitted by Codex ``notify``."""

    decoded = load_json_object(payload, source="Codex")
    event_name = required_string(decoded, "type", source="Codex", strip=True)
    if event_name != CODEX_COMPLETION_EVENT:
        raise UnsupportedEventError("unsupported Codex event")

    session_id = required_string(decoded, "thread-id", source="Codex", strip=True)
    turn_id = required_string(decoded, "turn-id", source="Codex", strip=True)
    text = required_string(decoded, "last-assistant-message", source="Codex")
    cwd = optional_string(decoded, "cwd", source="Codex")
    input_messages = optional_list(decoded, "input-messages", source="Codex")
    if input_messages is None:
        input_messages = []
    if any(not isinstance(message, str) for message in input_messages):
        raise InvalidPayloadError("Codex field 'input-messages' must contain only strings")

    metadata: dict[str, Any] = {
        "turn_id": turn_id,
        "input_messages": list(input_messages),
        "failed": False,
    }
    return NormalizedEvent(
        event_id=f"codex:{session_id}:{turn_id}",
        provider="codex",
        session_id=session_id,
        text=text,
        event_name=event_name,
        cwd=cwd,
        metadata=metadata,
    )
