from __future__ import annotations

import json
from typing import Any

from .errors import InvalidPayloadError, PayloadTooLargeError

MAX_PAYLOAD_BYTES = 1_048_576


class _DuplicateKeyError(ValueError):
    pass


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(key)
        result[key] = value
    return result


def _reject_non_finite(value: str) -> None:
    raise ValueError(value)


def load_json_object(payload: str, *, source: str) -> dict[str, Any]:
    """Decode a bounded, standards-compliant JSON object.

    Adapter exceptions deliberately contain no payload excerpts: hook responses can
    contain source code, credentials, or other terminal-session data.
    """

    if not isinstance(payload, str):
        raise InvalidPayloadError(f"{source} payload must be text")

    # Every valid Unicode code point needs at least one UTF-8 byte, so this cheap
    # character check avoids encoding an already-oversized input.
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise PayloadTooLargeError(f"{source} payload exceeds the {MAX_PAYLOAD_BYTES}-byte limit")

    try:
        payload_size = len(payload.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise InvalidPayloadError(f"{source} payload is not valid Unicode") from exc
    if payload_size > MAX_PAYLOAD_BYTES:
        raise PayloadTooLargeError(f"{source} payload exceeds the {MAX_PAYLOAD_BYTES}-byte limit")
    if not payload.strip():
        raise InvalidPayloadError(f"{source} payload is empty")

    try:
        decoded = json.loads(
            payload,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except _DuplicateKeyError as exc:
        raise InvalidPayloadError(f"{source} payload contains a duplicate JSON key") from exc
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise InvalidPayloadError(f"{source} payload is not valid JSON") from exc

    if not isinstance(decoded, dict):
        raise InvalidPayloadError(f"{source} payload must be a JSON object")
    return decoded


def required_string(payload: dict[str, Any], key: str, *, source: str, strip: bool = False) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvalidPayloadError(f"{source} field {key!r} must be a non-empty string")
    return value.strip() if strip else value


def optional_string(payload: dict[str, Any], key: str, *, source: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidPayloadError(f"{source} field {key!r} must be a string or null")
    return value


def optional_bool(payload: dict[str, Any], key: str, *, source: str) -> bool | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise InvalidPayloadError(f"{source} field {key!r} must be a boolean or null")
    return value


def optional_list(payload: dict[str, Any], key: str, *, source: str) -> list[Any] | None:
    value = payload.get(key)
    if value is None and key not in payload:
        return None
    if not isinstance(value, list):
        raise InvalidPayloadError(f"{source} field {key!r} must be an array")
    return value


def optional_object(payload: dict[str, Any], key: str, *, source: str) -> dict[str, Any] | None:
    value = payload.get(key)
    if value is None and key not in payload:
        return None
    if not isinstance(value, dict):
        raise InvalidPayloadError(f"{source} field {key!r} must be an object")
    return value
