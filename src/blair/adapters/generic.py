from __future__ import annotations

from typing import Any
from uuid import uuid4

from ._json import load_json_object, optional_object, optional_string, required_string
from .errors import InvalidPayloadError
from .models import NormalizedEvent


def parse_generic_event(payload: str) -> NormalizedEvent:
    """Normalize BLAIR's provider-neutral JSON integration format."""

    decoded = load_json_object(payload, source="Generic")
    session_id = required_string(decoded, "session_id", source="Generic", strip=True)
    text = required_string(decoded, "text", source="Generic")

    provider_value = decoded.get("provider", "generic")
    if not isinstance(provider_value, str) or not provider_value.strip():
        raise InvalidPayloadError("Generic field 'provider' must be a non-empty string")
    provider = provider_value.strip()

    event_name_value = decoded.get("event_name")
    legacy_event_value = decoded.get("event")
    if (
        event_name_value is not None
        and legacy_event_value is not None
        and event_name_value != legacy_event_value
    ):
        raise InvalidPayloadError("Generic fields 'event_name' and 'event' conflict")
    selected_event = event_name_value if event_name_value is not None else legacy_event_value
    if selected_event is None:
        event_name = "agent-turn-complete"
    elif not isinstance(selected_event, str) or not selected_event.strip():
        raise InvalidPayloadError("Generic event name must be a non-empty string")
    else:
        event_name = selected_event.strip()

    event_id_value = decoded.get("event_id")
    if event_id_value is None:
        event_id = str(uuid4())
    elif not isinstance(event_id_value, str) or not event_id_value.strip():
        raise InvalidPayloadError("Generic field 'event_id' must be a non-empty string")
    else:
        event_id = event_id_value.strip()

    cwd = optional_string(decoded, "cwd", source="Generic")
    metadata = dict(optional_object(decoded, "metadata", source="Generic") or {})
    _copy_semantics(decoded, metadata)

    return NormalizedEvent(
        event_id=event_id,
        provider=provider,
        session_id=session_id,
        text=text,
        event_name=event_name,
        cwd=cwd,
        metadata=metadata,
    )


def _copy_semantics(decoded: dict[str, Any], metadata: dict[str, Any]) -> None:
    if "background_pending" in decoded:
        background_pending = decoded["background_pending"]
        if background_pending is not None and not isinstance(background_pending, bool):
            raise InvalidPayloadError(
                "Generic field 'background_pending' must be a boolean or null"
            )
        metadata.setdefault("background_pending", background_pending)

    if "failed" in decoded:
        failed = decoded["failed"]
        if not isinstance(failed, bool):
            raise InvalidPayloadError("Generic field 'failed' must be a boolean")
        metadata.setdefault("failed", failed)

    for key in ("error", "details", "message", "error_details"):
        if key not in decoded:
            continue
        value = decoded[key]
        if value is not None and not isinstance(value, str):
            raise InvalidPayloadError(f"Generic field {key!r} must be a string or null")
        metadata.setdefault(key, value)

    background_pending = metadata.get("background_pending")
    if background_pending is not None and not isinstance(background_pending, bool):
        raise InvalidPayloadError("Generic metadata 'background_pending' must be a boolean or null")
    if "failed" in metadata and not isinstance(metadata["failed"], bool):
        raise InvalidPayloadError("Generic metadata 'failed' must be a boolean")
    for key in ("error", "details", "message", "error_details"):
        value = metadata.get(key)
        if value is not None and not isinstance(value, str):
            raise InvalidPayloadError(f"Generic metadata {key!r} must be a string or null")
