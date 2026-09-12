from pathlib import Path
from unittest.mock import Mock

import pytest

from blair.config import BlairConfig, save_config
from blair.feedback import announcement_audio
from blair.playback import PlaybackController, main


def fake_backend(monkeypatch):
    backend = Mock()
    backend.synthesize.side_effect = lambda text, output, **kwargs: output.write_bytes(b"RIFF")
    monkeypatch.setattr("blair.feedback.select_backend", Mock(return_value=backend))
    return backend


def test_confirmation_cache_uses_fixed_text_and_configured_voice(tmp_path, monkeypatch):
    backend = fake_backend(monkeypatch)
    config = BlairConfig(voice="bf_emma", speed=1.1)
    save_config(config, tmp_path)
    first = announcement_audio(tmp_path, "muted")
    assert announcement_audio(tmp_path, "muted") == first
    backend.synthesize.assert_called_once()
    assert backend.synthesize.call_args.args[0] == "Blair muted."
    assert backend.synthesize.call_args.kwargs["voice"] == "bf_emma"
    assert backend.synthesize.call_args.kwargs["speed"] == 1.1
    second = announcement_audio(tmp_path, "unmuted")
    assert second != first
    assert backend.synthesize.call_args.args[0] == "Blair unmuted."
    config.speed = 1.2
    save_config(config, tmp_path)
    assert announcement_audio(tmp_path, "muted") != first
    assert not (tmp_path / "sessions.json").exists()
    assert list((tmp_path / "audio").glob("*.wav")) == []


@pytest.mark.parametrize("config", [BlairConfig(backend="none"), BlairConfig(play_audio=False)])
def test_explicit_config_silence_also_disables_confirmations(tmp_path, monkeypatch, config):
    backend = fake_backend(monkeypatch)
    save_config(config, tmp_path)
    assert announcement_audio(tmp_path, "muted") is None
    backend.synthesize.assert_not_called()


def test_failed_synthesis_is_not_cached(tmp_path, monkeypatch):
    backend = fake_backend(monkeypatch)

    def fail(text, output, **kwargs):
        output.write_bytes(b"partial")
        raise OSError("synthesis failed")

    backend.synthesize.side_effect = fail
    with pytest.raises(OSError, match="synthesis failed"):
        announcement_audio(tmp_path, "muted")
    assert list((tmp_path / "runtime" / "control-audio").glob("*.wav")) == []


def test_muted_confirmation_plays_once_without_enabling_briefings(tmp_path, monkeypatch):
    controller = PlaybackController(tmp_path)
    controller.sessions.ensure_session("one", "codex")
    controller.sessions.set_enabled(False, "one")
    launch = Mock(return_value=Mock(pid=12345))
    monkeypatch.setattr("blair.playback.subprocess.Popen", launch)
    assert controller.toggle_muted(announce=True)
    command = launch.call_args.args[0]
    audio = tmp_path / "control.wav"
    audio.write_bytes(b"RIFF")
    monkeypatch.setattr("blair.feedback.announcement_audio", Mock(return_value=audio))
    play = Mock(return_value=0)
    monkeypatch.setattr("blair.playback._play_sync", play)
    assert main(command[3:]) == 0
    play.assert_called_once()
    assert not controller.state_path.exists()
    assert controller.sessions.is_speech_muted()
    assert controller.sessions.get("one").enabled is False
    assert controller.play(audio) is None
    launch.assert_called_once()


@pytest.mark.parametrize("next_action", ["toggle", "stop", "cli-unmute"])
def test_stale_confirmation_does_not_speak(tmp_path, monkeypatch, next_action):
    controller = PlaybackController(tmp_path)
    launch = Mock(return_value=Mock(pid=12345))
    monkeypatch.setattr("blair.playback.subprocess.Popen", launch)
    controller.toggle_muted(announce=True)
    old_command = launch.call_args.args[0]

    def synthesize(home, announcement):
        if next_action == "toggle":
            controller.toggle_muted(announce=True)
        elif next_action == "stop":
            controller.stop()
        else:
            controller.set_muted(False)
        return Path(home) / "unused.wav"

    monkeypatch.setattr("blair.feedback.announcement_audio", synthesize)
    play = Mock()
    monkeypatch.setattr("blair.playback._play_sync", play)
    assert main(old_command[3:]) == 0
    play.assert_not_called()
    if next_action == "toggle":
        assert controller._state()["announcement"] == "unmuted"
    else:
        assert not controller.state_path.exists()


def test_feedback_spawn_failure_does_not_undo_mute(tmp_path, monkeypatch):
    controller = PlaybackController(tmp_path)
    monkeypatch.setattr("blair.playback.subprocess.Popen", Mock(side_effect=OSError("failed")))
    with pytest.raises(OSError, match="failed"):
        controller.toggle_muted(announce=True)
    assert controller.sessions.is_speech_muted()
    assert not controller.state_path.exists()
