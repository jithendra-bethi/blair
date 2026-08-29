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
