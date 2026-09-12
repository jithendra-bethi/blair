from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from blair.config import _atomic_json_write
from blair.daemon import _pid_alive
from blair.errors import BlairError
from blair.locking import file_lock
from blair.playback import PlaybackController, _play_sync, main


def test_stop_never_signals_a_pid_from_disk(tmp_path: Path, monkeypatch) -> None:
    controller = PlaybackController(tmp_path)
    _atomic_json_write(controller.state_path, {"pid": 12345, "token": "stale-token"})
    kill = Mock()
    monkeypatch.setattr(os, "kill", kill)

    controller.stop()

    kill.assert_not_called()
    assert not controller.state_path.exists()


def test_worker_removes_its_record_after_natural_completion(tmp_path: Path, monkeypatch) -> None:
    controller = PlaybackController(tmp_path)
    _atomic_json_write(controller.state_path, {"pid": 12345, "token": "owned-token"})
    monkeypatch.setenv("BLAIR_HOME", str(tmp_path))
    play = Mock(return_value=0)
    monkeypatch.setattr("blair.playback._play_sync", play)

    assert main(["--worker", str(tmp_path / "audio.wav"), "--token", "owned-token"]) == 0

    play.assert_called_once()
    assert not controller.state_path.exists()


def test_old_worker_cannot_remove_a_new_playback_record(tmp_path: Path, monkeypatch) -> None:
    controller = PlaybackController(tmp_path)
    _atomic_json_write(controller.state_path, {"pid": 12345, "token": "old-token"})
    monkeypatch.setenv("BLAIR_HOME", str(tmp_path))

    def play(*args, **kwargs):
        _atomic_json_write(controller.state_path, {"pid": 67890, "token": "new-token"})
        return 0

    monkeypatch.setattr("blair.playback._play_sync", play)
    assert main(["--worker", str(tmp_path / "audio.wav"), "--token", "old-token"]) == 0
    assert json.loads(controller.state_path.read_text())["token"] == "new-token"


def test_cancelled_worker_never_starts_sound(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BLAIR_HOME", str(tmp_path))
    play = Mock()
    monkeypatch.setattr("blair.playback._play_sync", play)

    assert main(["--worker", str(tmp_path / "audio.wav"), "--token", "cancelled-token"]) == 0

    play.assert_not_called()


def test_failed_worker_clears_only_its_own_record(tmp_path: Path, monkeypatch) -> None:
    controller = PlaybackController(tmp_path)
    _atomic_json_write(controller.state_path, {"pid": 12345, "token": "owned-token"})
    monkeypatch.setenv("BLAIR_HOME", str(tmp_path))
    monkeypatch.setattr("blair.playback._play_sync", Mock(side_effect=OSError("Synthetic failure")))

    with pytest.raises(OSError, match="Synthetic failure"):
        main(["--worker", str(tmp_path / "audio.wav"), "--token", "owned-token"])

    assert not controller.state_path.exists()


def test_waiting_parent_preserves_replacement_playback(tmp_path: Path, monkeypatch) -> None:
    controller = PlaybackController(tmp_path)
    audio = tmp_path / "fake.wav"
    audio.write_bytes(b"synthetic")

    def wait(timeout):
        _atomic_json_write(controller.state_path, {"token": "replacement", "pid": 67890})
        return 0

    process = Mock(pid=12345)
    process.wait.side_effect = wait
    monkeypatch.setattr("blair.playback.subprocess.Popen", Mock(return_value=process))

    assert controller.play(audio, wait=True) == 12345
    assert controller._state()["token"] == "replacement"


def test_spawn_failure_does_not_leave_a_playback_record(tmp_path: Path, monkeypatch) -> None:
    controller = PlaybackController(tmp_path)
    audio = tmp_path / "fake.wav"
    audio.write_bytes(b"synthetic")
    monkeypatch.setattr(
        "blair.playback.subprocess.Popen", Mock(side_effect=OSError("spawn failed"))
    )

    with pytest.raises(OSError, match="spawn failed"):
        controller.play(audio)

    assert not controller.state_path.exists()


def test_global_mute_cancels_current_token_and_prevents_new_playback(tmp_path: Path, monkeypatch):
    controller = PlaybackController(tmp_path)
    _atomic_json_write(controller.state_path, {"token": "playing", "pid": 12345})
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"synthetic")
    launch = Mock(return_value=Mock(pid=12345))
    monkeypatch.setattr("blair.playback.subprocess.Popen", launch)

    assert controller.set_muted(True) is True
    assert not controller.state_path.exists()
    assert controller.play(audio) is None
    launch.assert_not_called()

    assert controller.toggle_muted() is False
    assert controller.play(audio) == 12345
    launch.assert_called_once()


def _silent_wav(path: Path, duration: float) -> Path:
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b"\0\0" * int(16000 * duration))
    return path


@pytest.mark.skipif(os.name != "nt", reason="Real Windows sound worker")
@pytest.mark.parametrize("wait", [True, False])
def test_windows_playback_cleans_up_after_silent_audio(tmp_path: Path, wait: bool) -> None:
    controller = PlaybackController(tmp_path)
    try:
        controller.play(_silent_wav(tmp_path / "silence.wav", 0.15), wait=wait)
        deadline = time.monotonic() + 5
        while controller.state_path.exists() and time.monotonic() < deadline:
            time.sleep(0.025)
        assert not controller.state_path.exists()
    finally:
        controller.stop()


@pytest.mark.skipif(os.name != "nt", reason="Real Windows sound worker")
def test_windows_stop_cancels_own_worker_and_leaves_recorded_unrelated_pid_alive(tmp_path: Path):
    controller = PlaybackController(tmp_path)
    unrelated = subprocess.Popen(
        [sys._base_executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        controller.play(_silent_wav(tmp_path / "silence.wav", 10))
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = controller._state()
            if state and state.get("ready"):
                break
            time.sleep(0.025)
        else:
            pytest.fail("Playback worker did not become ready")
        worker_pid = state["pid"]
        assert _pid_alive(worker_pid)
        state["pid"] = unrelated.pid
        with file_lock(controller.lock_path):
            _atomic_json_write(controller.state_path, state)

        assert controller.stop()

        deadline = time.monotonic() + 2
        while _pid_alive(worker_pid) and time.monotonic() < deadline:
            time.sleep(0.025)
        assert not _pid_alive(worker_pid)
        assert unrelated.poll() is None
        assert not controller.state_path.exists()
    finally:
        controller.stop()
        unrelated.terminate()
        unrelated.wait(timeout=5)


@pytest.mark.skipif(os.name != "nt", reason="Real Windows sound worker")
def test_windows_invalid_audio_reports_failure_and_cleans_state(tmp_path: Path) -> None:
    controller = PlaybackController(tmp_path)
    invalid = tmp_path / "invalid.wav"
    invalid.write_bytes(b"not a WAV")

    with pytest.raises(BlairError, match="Audio playback failed"):
        controller.play(invalid, wait=True)

    assert not controller.state_path.exists()


@pytest.mark.parametrize("mac_player_available", [True, False])
def test_posix_cancellation_only_terminates_the_owned_player(
    tmp_path: Path, monkeypatch, mac_player_available: bool
) -> None:
    monkeypatch.setattr("blair.playback.os", SimpleNamespace(name="posix"))
    player = Mock()
    player.poll.side_effect = [None, 0]
    launch = Mock(side_effect=[player] if mac_player_available else [FileNotFoundError(), player])
    monkeypatch.setattr("blair.playback.subprocess.Popen", launch)
    cancelled = Mock(side_effect=[False, True])

    assert _play_sync(tmp_path / "audio.wav", cancelled) == 0

    player.terminate.assert_called_once()
    player.wait.assert_called_once_with(timeout=1)
    player.kill.assert_not_called()


@pytest.mark.skipif(os.name != "nt", reason="Real Windows sound worker")
def test_windows_replacement_stops_old_worker_without_losing_new_record(tmp_path: Path) -> None:
    controller = PlaybackController(tmp_path)
    try:
        audio = _silent_wav(tmp_path / "silence.wav", 10)
        controller.play(audio)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            old = controller._state()
            if old and old.get("ready"):
                break
            time.sleep(0.025)
        else:
            pytest.fail("First worker did not become ready")

        controller.play(audio)
        replacement = controller._state()["token"]
        assert replacement != old["token"]
        deadline = time.monotonic() + 2
        while _pid_alive(old["pid"]) and time.monotonic() < deadline:
            time.sleep(0.025)

        assert not _pid_alive(old["pid"])
        assert controller._state()["token"] == replacement
    finally:
        controller.stop()
