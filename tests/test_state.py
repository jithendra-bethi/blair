from pathlib import Path

import pytest

from blair.state import StateStore


def test_sessions_are_isolated_and_active_session_tracks_latest(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    first = store.ensure_session("one", provider="codex", cwd="C:/one")
    assert first.enabled is None

    store.set_enabled(True, "one")
    store.ensure_session("two", provider="claude")
    store.set_enabled(False, "two")

    assert store.get("one").enabled is True
    assert store.get("two").enabled is False
    assert store.get().session_id == "two"


def test_unknown_session_never_defaults_to_enabled(tmp_path: Path) -> None:
    state = StateStore(tmp_path).ensure_session("new")
    assert state.enabled is None
    assert state.asked is False


def test_state_survives_new_store_instance(tmp_path: Path) -> None:
    first = StateStore(tmp_path)
    first.ensure_session("persisted")
    first.set_enabled(True, "persisted")

    second = StateStore(tmp_path)
    assert second.get("persisted").enabled is True


def test_set_enabled_requires_active_session(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="No BLAIR session"):
        StateStore(tmp_path).set_enabled(True)


def test_global_mute_persists_without_changing_session_permissions(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    store.ensure_session("enabled")
    store.set_enabled(True, "enabled")
    store.ensure_session("disabled")
    store.set_enabled(False, "disabled")
    store.ensure_session("unknown")

    assert store.is_speech_muted() is False
    assert store.toggle_speech_muted() is True
    assert StateStore(tmp_path).is_speech_muted() is True
    store.record_briefing("enabled", "Background completion.", None)
    assert store.toggle_speech_muted() is False

    assert store.get("enabled").enabled is True
    assert store.get("disabled").enabled is False
    assert store.get("unknown").enabled is None


def test_global_mute_works_before_any_session_exists(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    store.set_speech_muted(True)
    assert store.is_speech_muted() is True
    assert store.sessions() == []
    store.ensure_session("new")
    assert store.is_speech_muted() is True
    assert store.get("new").enabled is None
