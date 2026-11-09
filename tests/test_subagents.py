from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import Mock

import pytest

from blair.adapters.models import NormalizedEvent
from blair.config import BlairConfig, save_config
from blair.daemon import _SENTINEL, BlairDaemon
from blair.hook_entry import run_hook
from blair.state import StateStore
from blair.subagents import should_skip_briefing


def codex_index(home: Path, source: object, session: str = "child") -> None:
    home.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(home / "state_5.sqlite") as db:
        db.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, source TEXT)")
        db.execute("INSERT INTO threads VALUES (?, ?)", (session, json.dumps(source)))


@pytest.mark.parametrize("provider", ["codex", "claude"])
@pytest.mark.parametrize("previously_enabled", [False, True])
def test_subagent_hook_never_reaches_consent_or_audio(
    tmp_path, monkeypatch, provider, previously_enabled
):
    agent_home = tmp_path / "codex"
    monkeypatch.setenv("CODEX_HOME", str(agent_home))
    monkeypatch.setenv("BLAIR_LAUNCH_ID", "approved-wrapper")
    monkeypatch.setenv("BLAIR_CONSENT_RESPONSE", "yes")
    codex_index(agent_home, {"subagent": {"thread_spawn": {"parent_thread_id": "parent"}}})
    if provider == "codex":
        payload = json.dumps(
            {
                "type": "agent-turn-complete",
                "thread-id": "child",
                "turn-id": "one",
                "last-assistant-message": "Finished child work.",
            }
        )
        kind = "codex-notify"
    else:
        payload = json.dumps(
            {
                "hook_event_name": "Stop",
                "session_id": "parent",
                "agent_id": "child",
                "last_assistant_message": "Finished child work.",
            }
        )
        monkeypatch.setattr("blair.hook_entry._read_stdin_bounded", lambda: payload)
        kind = "claude-stop"
    enqueue = Mock()
    monkeypatch.setattr("blair.hook_entry.enqueue_event", enqueue)
    state = StateStore(tmp_path / "blair")
    if previously_enabled:
        state.ensure_session("parent", provider)
        state.set_enabled(True, "parent")
        state.ensure_session("child", provider)
        state.set_enabled(True, "child")
    assert run_hook(kind, payload, home=tmp_path / "blair") == 0
    enqueue.assert_not_called()
    if previously_enabled:
        assert state.get("parent").enabled is True
    else:
        assert not (tmp_path / "blair/sessions.json").exists()


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_main_session_with_custom_agent_or_fork_is_still_delivered(tmp_path, monkeypatch, provider):
    agent_home = tmp_path / "codex"
    monkeypatch.setenv("CODEX_HOME", str(agent_home))
    codex_index(agent_home, "cli", "parent")
    if provider == "codex":
        payload = json.dumps(
            {
                "type": "agent-turn-complete",
                "thread-id": "parent",
                "turn-id": "two",
                "last-assistant-message": "Parent complete.",
                "forked_from_id": "older-chat",
            }
        )
        kind = "codex-notify"
    else:
        payload = json.dumps(
            {
                "hook_event_name": "Stop",
                "session_id": "parent",
                "agent_type": "custom-reviewer",
                "last_assistant_message": "Parent complete.",
            }
        )
        monkeypatch.setattr("blair.hook_entry._read_stdin_bounded", lambda: payload)
        kind = "claude-stop"
    enqueue = Mock()
    monkeypatch.setattr("blair.hook_entry.enqueue_event", enqueue)
    assert run_hook(kind, payload, home=tmp_path / "blair") == 0
    enqueue.assert_called_once()


@pytest.mark.parametrize("broken_index", [False, True])
@pytest.mark.parametrize("source,expected", [("cli", False), ({"subagent": "review"}, True)])
def test_codex_rollout_fallback_uses_metadata_not_fork_or_message_content(
    tmp_path, monkeypatch, broken_index, source, expected
):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    session = "12345678-1234-1234-1234-123456789abc"
    if broken_index:
        (tmp_path / "state_5.sqlite").write_bytes(b"unreadable index")
    directory = tmp_path / "sessions/2026/09/16"
    directory.mkdir(parents=True)
    path = directory / f"rollout-2026-09-16-{session}.jsonl"
    path.write_text(
        json.dumps(
            {
                "type": "session_meta",
                "payload": {"id": session, "source": source, "forked_from_id": "parent"},
            }
        )
        + "\nprivate non-JSON conversation"
    )
    event = NormalizedEvent(
        "one", "codex", session, "subagent mentioned in normal prose", "agent-turn-complete"
    )
    assert should_skip_briefing(event) is expected


def test_missing_codex_metadata_skips_event_without_creating_index(tmp_path, monkeypatch):
    home = tmp_path / "missing-codex-home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    event = NormalizedEvent("one", "codex", "unknown-session", "Complete.", "agent-turn-complete")
    assert should_skip_briefing(event) is True
    assert not home.exists()


@pytest.mark.parametrize("source", [None, "unknown", "", {"future_background_job": {}}])
def test_unrecognized_source_does_not_count_as_main_chat(tmp_path, monkeypatch, source):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    codex_index(tmp_path, source)
    event = NormalizedEvent("one", "codex", "child", "Complete.", "agent-turn-complete")
    assert should_skip_briefing(event) is True


def test_main_chat_persisted_during_retry_is_delivered(tmp_path, monkeypatch):
    home = tmp_path / "codex"
    monkeypatch.setenv("CODEX_HOME", str(home))
    retry = Mock(side_effect=lambda delay: codex_index(home, "cli", "parent"))
    monkeypatch.setattr("blair.subagents.time.sleep", retry)
    enqueue = Mock()
    monkeypatch.setattr("blair.hook_entry.enqueue_event", enqueue)
    payload = json.dumps(
        {
            "type": "agent-turn-complete",
            "thread-id": "parent",
            "turn-id": "one",
            "last-assistant-message": "Complete.",
        }
    )
    assert run_hook("codex-notify", payload, home=tmp_path / "blair") == 0
    retry.assert_called_once_with(0.15)
    enqueue.assert_called_once()


def test_unreadable_provider_metadata_skips_without_enqueue(tmp_path, monkeypatch):
    monkeypatch.setattr("blair.subagents._codex_subagent", Mock(side_effect=PermissionError))
    retry = Mock()
    monkeypatch.setattr("blair.subagents.time.sleep", retry)
    enqueue = Mock()
    monkeypatch.setattr("blair.hook_entry.enqueue_event", enqueue)
    payload = json.dumps(
        {
            "type": "agent-turn-complete",
            "thread-id": "unknown",
            "turn-id": "one",
            "last-assistant-message": "Complete.",
        }
    )
    assert run_hook("codex-notify", payload, home=tmp_path) == 0
    retry.assert_called_once_with(0.15)
    enqueue.assert_not_called()


def test_latest_index_is_read_only_and_lookup_uses_parameters(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    codex_index(tmp_path, {"subagent": "review"})
    before = (tmp_path / "state_5.sqlite").read_bytes()
    event = NormalizedEvent("one", "codex", "' OR 1=1 --", "Complete.", "agent-turn-complete")
    assert should_skip_briefing(event) is True
    assert before == (tmp_path / "state_5.sqlite").read_bytes()


@pytest.mark.parametrize(
    "path,expected",
    [
        (r"C:\project\subagents\agent-123.jsonl", True),
        ("/project/subagents/agent-123.jsonl", True),
        ("/project/subagents/main-session.jsonl", False),
        ("/project/session.jsonl", False),
    ],
)
def test_claude_legacy_child_transcript_path(tmp_path, path, expected):
    event = NormalizedEvent(
        "one", "claude", "parent", "Complete.", "Stop", metadata={"transcript_path": path}
    )
    assert should_skip_briefing(event) is expected


def test_claude_subagent_failure_is_also_ignored(tmp_path, monkeypatch):
    payload = json.dumps(
        {
            "hook_event_name": "StopFailure",
            "session_id": "parent",
            "agent_id": "child",
            "error": "execution_failed",
        }
    )
    monkeypatch.setattr("blair.hook_entry._read_stdin_bounded", lambda: payload)
    enqueue = Mock()
    monkeypatch.setattr("blair.hook_entry.enqueue_event", enqueue)
    assert run_hook("claude-failure", home=tmp_path) == 0
    enqueue.assert_not_called()


def test_parent_and_subagents_through_real_hook_and_worker_prompt_only_for_parent(
    tmp_path, monkeypatch
):
    agent_home = tmp_path / "codex"
    monkeypatch.setenv("CODEX_HOME", str(agent_home))
    monkeypatch.delenv("BLAIR_LAUNCH_ID", raising=False)
    codex_index(agent_home, {"subagent": {"thread_spawn": {"parent_thread_id": "parent"}}})
    with sqlite3.connect(agent_home / "state_5.sqlite") as db:
        db.execute("INSERT INTO threads VALUES (?, ?)", ("parent", "cli"))
    home = tmp_path / "blair"
    save_config(BlairConfig(backend="none", hotkeys_enabled=False), home)
    daemon = BlairDaemon(home)
    prompt = Mock(return_value=True)
    daemon.pipeline.consent.ask = prompt
    monkeypatch.setattr(
        "blair.hook_entry.enqueue_event", lambda event, root: daemon._enqueue_latest(event)
    )
    for turn, session in enumerate(("parent", "child", "parent", "child")):
        payload = json.dumps(
            {
                "type": "agent-turn-complete",
                "thread-id": session,
                "turn-id": str(turn),
                "last-assistant-message": f"Completed step {turn}.",
            }
        )
        assert run_hook("codex-notify", payload, home=home) == 0
        daemon.events.put(_SENTINEL)
        daemon._work()
    prompt.assert_called_once_with("codex", "parent")
    assert daemon.pipeline.state.get("parent").enabled is True
    assert daemon.pipeline.state.get("child") is None


@pytest.mark.parametrize("recap_previously_enabled", [False, True])
def test_switching_chats_and_recaps_only_prompts_for_real_chats(
    tmp_path, monkeypatch, recap_previously_enabled
):
    agent_home = tmp_path / "codex"
    monkeypatch.setenv("CODEX_HOME", str(agent_home))
    monkeypatch.delenv("BLAIR_LAUNCH_ID", raising=False)
    codex_index(agent_home, "cli", "chat-a")
    with sqlite3.connect(agent_home / "state_5.sqlite") as db:
        db.execute("INSERT INTO threads VALUES (?, ?)", ("chat-b", "vscode"))
    home = tmp_path / "blair"
    save_config(BlairConfig(backend="none", hotkeys_enabled=False), home)
    daemon = BlairDaemon(home)
    prompt = Mock(return_value=True)
    daemon.pipeline.consent.ask = prompt
    if recap_previously_enabled:
        daemon.pipeline.state.ensure_session("recap-a", "codex")
        daemon.pipeline.state.set_enabled(True, "recap-a")
    enqueue = Mock(side_effect=lambda event, root: daemon._enqueue_latest(event))
    monkeypatch.setattr("blair.hook_entry.enqueue_event", enqueue)
    for turn, session in enumerate(("chat-a", "chat-b", "recap-a", "chat-a", "recap-b", "chat-b")):
        payload = json.dumps(
            {
                "type": "agent-turn-complete",
                "thread-id": session,
                "turn-id": str(turn),
                # The visible heading is not a reliable distinction: real chats
                # can discuss recaps, and background output can omit the heading.
                "last-assistant-message": (
                    "Conversation recap\nUpdated the parser."
                    if session.startswith("chat")
                    else '{"recap":"Updated the parser."}'
                ),
            }
        )
        assert run_hook("codex-notify", payload, home=home) == 0
        daemon.events.put(_SENTINEL)
        daemon._work()
    assert [call.args for call in prompt.call_args_list] == [
        ("codex", "chat-a"),
        ("codex", "chat-b"),
    ]
    assert [call.args[0].session_id for call in enqueue.call_args_list] == [
        "chat-a",
        "chat-b",
        "chat-a",
        "chat-b",
    ]
    assert daemon.pipeline.state.get("recap-b") is None
    if recap_previously_enabled:
        assert daemon.pipeline.state.get("recap-a").last_briefing is None
    else:
        assert daemon.pipeline.state.get("recap-a") is None
