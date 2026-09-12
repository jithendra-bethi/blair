from __future__ import annotations

from pathlib import Path

import pytest

from blair.hotkeys import HotkeyActions, parse_hotkey
from blair.state import StateStore


class FakePlayback:
    def __init__(self, state: StateStore) -> None:
        self.state = state
        self.played: list[Path] = []
        self.stop_calls = 0

    def play(self, path: Path, *, wait: bool = False) -> int:
        del wait
        self.played.append(path)
        return 1

    def stop(self) -> bool:
        self.stop_calls += 1
        return True

    def toggle_muted(self, *, announce: bool = False) -> bool:
        assert announce is True
        muted = self.state.toggle_speech_muted()
        if muted:
            self.stop()
        return muted


def test_hotkey_parser_supports_documented_bindings() -> None:
    assert parse_hotkey("ctrl+alt+b")[1] == ord("B")
    assert parse_hotkey("win+shift+F12")[1] == 0x7B
    with pytest.raises(ValueError, match="modifier"):
        parse_hotkey("meta+b")


def test_global_toggle_ignores_active_session_and_preserves_permissions(tmp_path: Path) -> None:
    state = StateStore(tmp_path)
    state.ensure_session("one")
    state.set_enabled(True, "one")
    audio = tmp_path / "last.wav"
    audio.write_bytes(b"RIFF")
    state.record_briefing("one", "Complete.", audio)
    state.ensure_session("two", "claude")
    state.set_enabled(False, "two")
    playback = FakePlayback(state)
    actions = HotkeyActions(tmp_path, state=state, playback=playback)

    assert actions.toggle() == "hotkey-speech-muted"
    assert actions.replay() == "hotkey-speech-muted"
    assert playback.played == []
    assert playback.stop_calls == 1
    state.record_briefing("one", "Complete.", audio)
    assert actions.toggle() == "hotkey-speech-unmuted"
    assert state.get("one").enabled is True
    assert state.get("two").enabled is False
    assert actions.replay() == "hotkey-replayed"
    assert playback.played == [audio]


def test_global_toggle_works_without_a_chat(tmp_path: Path, monkeypatch) -> None:
    from unittest.mock import Mock

    monkeypatch.setattr("blair.playback.subprocess.Popen", Mock(return_value=Mock(pid=12345)))
    actions = HotkeyActions(tmp_path)
    assert actions.toggle() == "hotkey-speech-muted"
    assert StateStore(tmp_path).is_speech_muted()
    assert actions.toggle() == "hotkey-speech-unmuted"
