from __future__ import annotations

from pathlib import Path

import pytest

from blair.hotkeys import HotkeyActions, parse_hotkey
from blair.state import StateStore


class FakePlayback:
    def __init__(self) -> None:
        self.played: list[Path] = []
        self.stop_calls = 0

    def play(self, path: Path, *, wait: bool = False) -> int:
        del wait
        self.played.append(path)
        return 1

    def stop(self) -> bool:
        self.stop_calls += 1
        return True


def test_hotkey_parser_supports_documented_bindings() -> None:
    assert parse_hotkey("ctrl+alt+b")[1] == ord("B")
    assert parse_hotkey("win+shift+F12")[1] == 0x7B
    with pytest.raises(ValueError, match="modifier"):
        parse_hotkey("meta+b")


def test_actions_toggle_and_replay_active_session(tmp_path: Path) -> None:
    state = StateStore(tmp_path)
    state.ensure_session("one")
    state.set_enabled(True, "one")
    audio = tmp_path / "last.wav"
    audio.write_bytes(b"RIFF")
    state.record_briefing("one", "Complete.", audio)
    playback = FakePlayback()
    actions = HotkeyActions(tmp_path, state=state, playback=playback)

    assert actions.toggle() == "hotkey-disabled"
    assert state.get("one").enabled is False
    assert playback.stop_calls == 1
    assert actions.toggle() == "hotkey-enabled"
    assert actions.replay() == "hotkey-replayed"
    assert playback.played == [audio]
