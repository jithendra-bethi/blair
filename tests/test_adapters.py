import json
from uuid import UUID

import pytest

from blair.adapters import (
    MAX_PAYLOAD_BYTES,
    InvalidPayloadError,
    PayloadTooLargeError,
    UnsupportedEventError,
    parse_claude_hook,
    parse_codex_notification,
    parse_generic_event,
)
from blair.errors import AdapterError


def dump(payload: object) -> str:
    return json.dumps(payload)


def codex_payload(**overrides: object) -> str:
    payload: dict[str, object] = {
        "type": "agent-turn-complete",
        "thread-id": "thread-123",
        "turn-id": "turn-456",
        "cwd": "C:\\work",
        "input-messages": ["Implement the adapter"],
        "last-assistant-message": "Implemented and verified the adapter.",
    }
    payload.update(overrides)
    return dump(payload)


def claude_payload(**overrides: object) -> str:
    payload: dict[str, object] = {
        "session_id": "session-123",
        "transcript_path": "C:\\tmp\\session.jsonl",
        "cwd": "C:\\work",
        "permission_mode": "default",
        "hook_event_name": "Stop",
        "stop_hook_active": False,
        "last_assistant_message": "The requested work is complete.",
        "background_tasks": [],
        "session_crons": [],
    }
    payload.update(overrides)
    return dump(payload)


def test_codex_notification_normalizes_completion_and_converts_to_agent_result() -> None:
    event = parse_codex_notification(codex_payload())

    assert event.event_id == "codex:thread-123:turn-456"
    assert event.provider == "codex"
    assert event.session_id == "thread-123"
    assert event.text == "Implemented and verified the adapter."
    assert event.event_name == "agent-turn-complete"
    assert event.cwd == "C:\\work"
    assert event.metadata == {
        "turn_id": "turn-456",
        "input_messages": ["Implement the adapter"],
        "failed": False,
    }

    result = event.to_agent_result()
    assert result.session_id == event.session_id
    assert result.text == event.text
    assert result.provider == "codex"
    assert result.event == event.event_name
    assert result.metadata["event_id"] == event.event_id
    assert "event_id" not in event.metadata


def test_codex_event_id_is_stable_for_retried_payload() -> None:
    first = parse_codex_notification(codex_payload())
    second = parse_codex_notification(codex_payload())

    assert first.event_id == second.event_id


def test_codex_rejects_non_completion_events_and_invalid_input_messages() -> None:
    with pytest.raises(UnsupportedEventError, match="unsupported Codex event"):
        parse_codex_notification(codex_payload(type="approval-requested"))

    with pytest.raises(InvalidPayloadError, match="input-messages"):
        parse_codex_notification(codex_payload(**{"input-messages": ["valid", 3]}))


def test_claude_stop_preserves_known_idle_background_state() -> None:
    event = parse_claude_hook(claude_payload())

    UUID(event.event_id)
    assert event.provider == "claude"
    assert event.session_id == "session-123"
    assert event.event_name == "Stop"
    assert event.metadata["failed"] is False
    assert event.metadata["background_pending"] is False
    assert event.metadata["background_tasks"] == []
    assert event.metadata["session_crons"] == []
    assert event.metadata["stop_hook_active"] is False


def test_claude_stop_preserves_pending_and_unknown_background_state() -> None:
    pending = parse_claude_hook(
        claude_payload(background_tasks=[{"id": "task-1", "status": "running"}])
    )
    assert pending.metadata["background_pending"] is True
    assert pending.metadata["background_tasks"] == [{"id": "task-1", "status": "running"}]

    decoded = json.loads(claude_payload())
    del decoded["background_tasks"]
    del decoded["session_crons"]
    unknown = parse_claude_hook(dump(decoded))
    assert unknown.metadata["background_pending"] is None


def test_claude_event_ids_are_uuid_per_delivery() -> None:
    first = parse_claude_hook(claude_payload())
    second = parse_claude_hook(claude_payload())

    assert first.event_id != second.event_id
    UUID(first.event_id)
    UUID(second.event_id)


def test_claude_stop_failure_preserves_official_error_fields_and_failure_semantics() -> None:
    failure = parse_claude_hook(
        dump(
            {
                "session_id": "failed-session",
                "cwd": "C:\\work",
                "hook_event_name": "StopFailure",
                "error": "rate_limit",
                "details": "Usage limit reached for this account.",
                "message": "Please retry later.",
            }
        )
    )

    assert failure.event_name == "StopFailure"
    assert failure.text == "Agent turn failed (rate limit): Please retry later."
    assert failure.metadata["failed"] is True
    assert failure.metadata["error"] == "rate_limit"
    assert failure.metadata["details"] == "Usage limit reached for this account."
    assert failure.metadata["message"] == "Please retry later."
    assert failure.metadata["background_pending"] is None


def test_claude_stop_failure_accepts_legacy_message_fields() -> None:
    failure = parse_claude_hook(
        dump(
            {
                "session_id": "failed-session",
                "hook_event_name": "StopFailure",
                "error": "server_error",
                "error_details": "Please retry later.",
            }
        )
    )

    assert failure.text == "Agent turn failed (server error): Please retry later."
    assert failure.metadata["error_details"] == "Please retry later."


def test_claude_rejects_other_hooks_and_invalid_background_shape() -> None:
    with pytest.raises(UnsupportedEventError, match="unsupported Claude hook event"):
        parse_claude_hook(claude_payload(hook_event_name="SubagentStop"))

    with pytest.raises(InvalidPayloadError, match="background_tasks"):
        parse_claude_hook(claude_payload(background_tasks={"id": "not-an-array"}))


def test_generic_event_accepts_explicit_contract_and_preserves_semantics() -> None:
    event = parse_generic_event(
        dump(
            {
                "event_id": "source-event-42",
                "provider": "custom-agent",
                "session_id": "generic-session",
                "text": "Completed with a remaining blocker.",
                "event_name": "turn-failed",
                "cwd": "C:\\repo",
                "background_pending": True,
                "failed": True,
                "metadata": {"blocker": "approval required"},
            }
        )
    )

    assert event.event_id == "source-event-42"
    assert event.provider == "custom-agent"
    assert event.event_name == "turn-failed"
    assert event.metadata == {
        "blocker": "approval required",
        "background_pending": True,
        "failed": True,
    }


def test_generic_event_defaults_and_generates_uuid() -> None:
    event = parse_generic_event(dump({"session_id": "session", "text": "Done."}))

    UUID(event.event_id)
    assert event.provider == "generic"
    assert event.event_name == "agent-turn-complete"
    assert event.cwd is None
    assert event.metadata == {}


def test_generic_event_validates_normalized_semantic_fields() -> None:
    with pytest.raises(InvalidPayloadError, match="background_pending"):
        parse_generic_event(
            dump(
                {
                    "session_id": "session",
                    "text": "Done.",
                    "background_pending": "yes",
                }
            )
        )

    with pytest.raises(InvalidPayloadError, match="failed"):
        parse_generic_event(dump({"session_id": "session", "text": "Done.", "failed": 1}))

    with pytest.raises(InvalidPayloadError, match="metadata 'failed'"):
        parse_generic_event(
            dump(
                {
                    "session_id": "session",
                    "text": "Done.",
                    "metadata": {"failed": "yes"},
                }
            )
        )


@pytest.mark.parametrize(
    "parser",
    [parse_codex_notification, parse_claude_hook, parse_generic_event],
)
def test_all_adapters_bound_input_before_parsing(parser: object) -> None:
    with pytest.raises(PayloadTooLargeError, match="byte limit"):
        parser("x" * (MAX_PAYLOAD_BYTES + 1))  # type: ignore[operator]


def test_utf8_byte_limit_is_enforced_not_only_character_count() -> None:
    payload = '"' + ("\u00e9" * (MAX_PAYLOAD_BYTES // 2)) + '"'

    with pytest.raises(PayloadTooLargeError):
        parse_generic_event(payload)


@pytest.mark.parametrize(
    "payload",
    ["", "[]", "{not-json}", '{"session_id":"one","session_id":"two"}', '{"x":NaN}'],
)
def test_malformed_inputs_raise_fail_open_friendly_adapter_errors(payload: str) -> None:
    with pytest.raises(AdapterError) as caught:
        parse_generic_event(payload)

    if payload:
        assert payload not in str(caught.value)
