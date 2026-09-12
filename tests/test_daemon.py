from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from blair.adapters.models import NormalizedEvent
from blair.config import BlairConfig, save_config
from blair.daemon import (
    _SENTINEL,
    BlairDaemon,
    EventLedger,
    daemon_pid,
    enqueue_event,
    start_daemon,
    stop_daemon,
)
from blair.models import AgentResult, SpeechArtifact
from blair.pipeline import PipelineOutcome
from blair.state import StateStore


def event(event_id: str = "one", text: str = "Completed.") -> NormalizedEvent:
    return NormalizedEvent(
        event_id=event_id,
        provider="codex",
        session_id="session",
        text=text,
        event_name="agent-turn-complete",
    )


def test_ledger_deduplicates_event_ids_without_persisting_content(tmp_path: Path) -> None:
    ledger = EventLedger(tmp_path)

    assert ledger.seen_or_add(event(), now=100.0) is False
    assert ledger.seen_or_add(event(), now=101.0) is True
    assert "Completed" not in ledger.path.read_text(encoding="utf-8")


def test_ledger_suppresses_immediate_claude_style_redelivery(tmp_path: Path) -> None:
    ledger = EventLedger(tmp_path, duplicate_window=8.0)

    assert ledger.seen_or_add(event("transport-1"), now=100.0) is False
    assert ledger.seen_or_add(event("transport-2"), now=105.0) is True
    assert ledger.seen_or_add(event("transport-3"), now=120.0) is False


def test_pending_queue_keeps_only_the_newest_completion(tmp_path: Path) -> None:
    daemon = BlairDaemon(tmp_path)

    daemon._enqueue_latest(event("old", "Old completion."))
    daemon._enqueue_latest(event("new", "New completion."))
    sequence, pending = daemon.events.get_nowait()

    assert sequence == 2
    assert pending.event_id == "new"


def test_global_mute_blocks_all_sessions_then_resumes_only_enabled(tmp_path: Path) -> None:
    daemon = BlairDaemon(tmp_path)
    state = daemon.pipeline.state
    for session_id, enabled in [("session", True), ("declined", False)]:
        state.ensure_session(session_id, "codex")
        state.set_enabled(enabled, session_id)
    daemon.pipeline.playback.set_muted(True)
    for session_id in ("session", "declined", "unknown"):
        completion = event(f"muted-{session_id}", f"Completed {session_id}.")
        completion.session_id = session_id
        daemon._enqueue_latest(completion)
    assert daemon.events.empty()
    assert daemon.latest_sequence == 0
    assert state.get("unknown") is None
    daemon.pipeline.playback.set_muted(False)
    declined = event("declined-after", "New declined completion.")
    declined.session_id = "declined"
    daemon._enqueue_latest(declined)
    assert daemon.events.empty()
    daemon._enqueue_latest(event("enabled-after", "New enabled completion."))
    assert daemon.events.get_nowait()[1].event_id == "enabled-after"
    assert state.get("session").enabled is True
    assert state.get("declined").enabled is False


def test_global_mute_during_daemon_synthesis_blocks_final_playback(tmp_path: Path, monkeypatch):
    save_config(BlairConfig(backend="windows", hotkeys_enabled=False), tmp_path)
    daemon = BlairDaemon(tmp_path)
    daemon.pipeline.state.ensure_session("session", "codex")
    daemon.pipeline.state.set_enabled(True, "session")
    backend = _fake_backend()
    original = backend.synthesize.side_effect

    def synthesize(*args, **kwargs):
        daemon.pipeline.playback.set_muted(True)
        return original(*args, **kwargs)

    backend.synthesize.side_effect = synthesize
    monkeypatch.setattr("blair.pipeline.select_backend", Mock(return_value=backend))
    spawn = Mock()
    monkeypatch.setattr("blair.playback.subprocess.Popen", spawn)
    _process_one(daemon, event())
    spawn.assert_not_called()
    assert "briefing-speech-muted" in (tmp_path / "logs" / "blair.log").read_text()


@pytest.mark.parametrize("duplicate_id", ["first", "different-transport-id"])
def test_duplicate_does_not_interrupt_or_replace_pending_briefing(
    tmp_path: Path, monkeypatch, duplicate_id: str
) -> None:
    daemon = BlairDaemon(tmp_path)
    daemon.pipeline.state.ensure_session("session", provider="codex")
    daemon.pipeline.state.set_enabled(True, "session")
    stop = Mock()
    monkeypatch.setattr(daemon.pipeline.playback, "stop", stop)
    daemon._enqueue_latest(event("first", "Original completion."))
    stop.reset_mock()

    daemon._enqueue_latest(event(duplicate_id, "Original completion."))

    stop.assert_not_called()
    assert daemon.latest_sequence == 1
    assert daemon.events.qsize() == 1
    sequence, pending = daemon.events.get_nowait()
    assert sequence == 1 and pending.event_id == "first"


def test_muted_completion_does_not_interrupt_or_replace_pending_briefing(
    tmp_path: Path, monkeypatch
):
    daemon = BlairDaemon(tmp_path)
    state = daemon.pipeline.state
    state.ensure_session("session", provider="codex")
    state.set_enabled(True, "session")
    state.ensure_session("muted", provider="claude")
    state.set_enabled(False, "muted")
    stop = Mock()
    monkeypatch.setattr(daemon.pipeline.playback, "stop", stop)
    daemon._enqueue_latest(event("first", "Original completion."))
    stop.reset_mock()
    muted = event("muted-event", "Muted completion.")
    muted.session_id = "muted"

    daemon._enqueue_latest(muted)

    stop.assert_not_called()
    assert daemon.latest_sequence == 1
    assert daemon.events.qsize() == 1
    assert daemon.events.get_nowait()[1].event_id == "first"


@pytest.mark.parametrize("ignored", ["duplicate", "muted"])
def test_ignored_arrival_during_synthesis_does_not_cancel_current_briefing(
    tmp_path: Path, monkeypatch, ignored: str
) -> None:
    save_config(BlairConfig(backend="windows", hotkeys_enabled=False), tmp_path)
    daemon = BlairDaemon(tmp_path)
    state = daemon.pipeline.state
    state.ensure_session("session", provider="codex")
    state.set_enabled(True, "session")
    state.ensure_session("muted", provider="claude")
    state.set_enabled(False, "muted")
    first = event("first", "Original completion.")
    incoming = (
        event("different-transport", first.text)
        if ignored == "duplicate"
        else event("muted-event", "Muted completion.")
    )
    if ignored == "muted":
        incoming.session_id = "muted"
    backend = _fake_backend()
    original_synthesize = backend.synthesize.side_effect

    def synthesize(*args, **kwargs):
        daemon._enqueue_latest(incoming)
        return original_synthesize(*args, **kwargs)

    backend.synthesize.side_effect = synthesize
    monkeypatch.setattr("blair.pipeline.select_backend", Mock(return_value=backend))
    stop, play = Mock(), Mock()
    monkeypatch.setattr(daemon.pipeline.playback, "stop", stop)
    monkeypatch.setattr(daemon.pipeline.playback, "play", play)
    # Stop after the current outcome even if the broken enqueue clears the sentinel.
    original_log = daemon._log

    def log(action, completion=None, error=None):
        original_log(action, completion, error)
        if action.startswith("briefing-"):
            daemon.stop_event.set()

    monkeypatch.setattr(daemon, "_log", log)
    _process_one(daemon, first)

    play.assert_called_once()
    stop.assert_called_once()
    assert daemon.latest_sequence == 1


@pytest.mark.parametrize("enabled", [True, False])
def test_new_wrapper_choice_is_applied_before_interruption(
    tmp_path: Path, monkeypatch, enabled: bool
):
    daemon = BlairDaemon(tmp_path)
    state = daemon.pipeline.state
    state.ensure_session("session", provider="codex")
    state.set_enabled(not enabled, "session")
    completion = event()
    completion.metadata.update(launch_id="new-launch", consent_override=enabled)
    stop = Mock()
    monkeypatch.setattr(daemon.pipeline.playback, "stop", stop)

    daemon._enqueue_latest(completion)

    assert state.get("session").enabled is enabled
    assert state.get("session").launch_id == "new-launch"
    assert stop.call_count == (1 if enabled else 0)
    assert daemon.events.qsize() == (1 if enabled else 0)


def test_manual_mute_is_not_overridden_by_same_launch(tmp_path: Path, monkeypatch) -> None:
    daemon = BlairDaemon(tmp_path)
    state = daemon.pipeline.state
    state.ensure_session("session", provider="codex")
    state.begin_launch("session", "same-launch", True)
    state.set_enabled(False, "session")
    completion = event()
    completion.metadata.update(launch_id="same-launch", consent_override=True)
    stop = Mock()
    monkeypatch.setattr(daemon.pipeline.playback, "stop", stop)

    daemon._enqueue_latest(completion)

    stop.assert_not_called()
    assert daemon.events.empty()
    assert state.get("session").enabled is False


def test_duplicate_after_playback_starts_does_not_stop_or_replay_audio(tmp_path: Path, monkeypatch):
    save_config(BlairConfig(backend="windows", hotkeys_enabled=False), tmp_path)
    daemon = BlairDaemon(tmp_path)
    daemon.pipeline.state.ensure_session("session", provider="codex")
    daemon.pipeline.state.set_enabled(True, "session")
    backend = _fake_backend()
    monkeypatch.setattr("blair.pipeline.select_backend", Mock(return_value=backend))
    stop, play = Mock(), Mock()
    monkeypatch.setattr(daemon.pipeline.playback, "stop", stop)
    monkeypatch.setattr(daemon.pipeline.playback, "play", play)
    _process_one(daemon, event("first", "Original completion."))

    _process_one(daemon, event("first", "Original completion."))

    stop.assert_called_once()
    play.assert_called_once()
    backend.synthesize.assert_called_once()


def test_new_enabled_completion_still_replaces_pending_briefing(
    tmp_path: Path, monkeypatch
) -> None:
    daemon = BlairDaemon(tmp_path)
    daemon.pipeline.state.ensure_session("session", provider="codex")
    daemon.pipeline.state.set_enabled(True, "session")
    stop = Mock()
    monkeypatch.setattr(daemon.pipeline.playback, "stop", stop)
    daemon._enqueue_latest(event("first", "First completion."))

    daemon._enqueue_latest(event("second", "Second completion."))

    assert stop.call_count == 2
    assert daemon.latest_sequence == 2
    assert daemon.events.qsize() == 1
    assert daemon.events.get_nowait()[1].event_id == "second"


def _process_one(daemon: BlairDaemon, completion: NormalizedEvent) -> None:
    daemon._enqueue_latest(completion)
    daemon.events.put(_SENTINEL)
    daemon._work()


def _fake_backend() -> Mock:
    backend = Mock()

    def synthesize(text, output_path, *, voice, language, speed):
        output_path.write_bytes(b"synthetic audio")
        return SpeechArtifact(output_path, "test", voice)

    backend.synthesize.side_effect = synthesize
    return backend


def test_worker_applies_saved_speech_settings_before_next_briefing(
    tmp_path: Path, monkeypatch
) -> None:
    config = BlairConfig(backend="windows", hotkeys_enabled=False)
    save_config(config, tmp_path)
    daemon = BlairDaemon(tmp_path)
    daemon.pipeline.state.ensure_session("session", provider="codex")
    daemon.pipeline.state.set_enabled(True, "session")
    backend = _fake_backend()
    select = Mock(return_value=backend)
    monkeypatch.setattr("blair.pipeline.select_backend", select)
    play = Mock()
    monkeypatch.setattr(daemon.pipeline.playback, "play", play)
    monkeypatch.setattr(daemon.pipeline.playback, "stop", Mock())
    _process_one(daemon, event("first", "Updated the interface."))
    assert play.call_count == 1

    config.play_audio = False
    config.max_words = 20
    config.voice = "af_heart"
    config.language = "en-us"
    config.speed = 1.5
    config.honorific = ""
    config.keep_audio_files = 1
    save_config(config, tmp_path)
    _process_one(daemon, event("second", "Updated the documentation.\n| Item | Result |"))

    assert play.call_count == 1
    assert backend.synthesize.call_count == 2
    args = backend.synthesize.call_args
    assert args.kwargs == {"voice": "af_heart", "language": "en-us", "speed": 1.5}
    assert len(args.args[0].split()) <= 20
    assert "sir" not in args.args[0]
    assert len(list((tmp_path / "audio").glob("*.wav"))) == 1
    select.assert_called_once()


def test_worker_reselects_backend_when_saved_backend_changes(tmp_path: Path, monkeypatch) -> None:
    config = BlairConfig(backend="windows", play_audio=False, hotkeys_enabled=False)
    save_config(config, tmp_path)
    daemon = BlairDaemon(tmp_path)
    daemon.pipeline.state.ensure_session("session", provider="codex")
    daemon.pipeline.state.set_enabled(True, "session")
    old_backend, new_backend = _fake_backend(), _fake_backend()
    select = Mock(side_effect=[old_backend, new_backend])
    monkeypatch.setattr("blair.pipeline.select_backend", select)
    monkeypatch.setattr(daemon.pipeline.playback, "stop", Mock())
    _process_one(daemon, event("first", "Updated the interface."))

    config.backend = "kokoro"
    save_config(config, tmp_path)
    _process_one(daemon, event("second", "Updated the documentation."))

    old_backend.synthesize.assert_called_once()
    new_backend.synthesize.assert_called_once()
    assert select.call_args.args[0].backend == "kokoro"

    config.backend = "none"
    save_config(config, tmp_path)
    _process_one(daemon, event("third", "Updated the tests."))
    assert daemon.pipeline.state.get("session").last_audio is None
    assert select.call_count == 2


def test_worker_recovers_after_invalid_saved_settings(tmp_path: Path, monkeypatch) -> None:
    config = BlairConfig(backend="none", hotkeys_enabled=False)
    save_config(config, tmp_path)
    daemon = BlairDaemon(tmp_path)
    prompt = Mock(return_value=False)
    daemon.pipeline.consent.callback = prompt
    monkeypatch.setattr(daemon.pipeline.playback, "stop", Mock())
    (tmp_path / "config.json").write_text("{invalid", encoding="utf-8")

    _process_one(daemon, event("bad", "First completion."))

    prompt.assert_not_called()
    assert daemon.pipeline.state.get("session") is None
    records = [json.loads(line) for line in (tmp_path / "logs/blair.log").read_text().splitlines()]
    assert records[-1]["action"] == "briefing-error"

    config.prompt_new_sessions = False
    save_config(config, tmp_path)
    _process_one(daemon, event("recovered", "Second completion."))
    prompt.assert_not_called()
    assert daemon.pipeline.state.get("session").enabled is None
    records = [json.loads(line) for line in (tmp_path / "logs/blair.log").read_text().splitlines()]
    assert records[-1]["action"] == "briefing-session-consent-unknown"


@pytest.mark.parametrize("enabled", [True, False], ids=["wrapper-yes", "wrapper-no"])
def test_wrapper_consent_does_not_answer_for_an_unrelated_session(
    tmp_path: Path, monkeypatch, enabled: bool
) -> None:
    monkeypatch.setenv("BLAIR_CONSENT_RESPONSE", "yes" if enabled else "no")
    monkeypatch.setenv("BLAIR_LAUNCH_ID", "wrapper-launch")
    # Simulate the Windows dialog without showing a real prompt on any platform.
    monkeypatch.setattr("blair.consent.os", SimpleNamespace(name="nt", environ=os.environ))
    prompt = Mock(return_value=not enabled)
    monkeypatch.setattr("blair.consent._windows_prompt", prompt)
    save_config(BlairConfig(backend="none", hotkeys_enabled=False), tmp_path)
    daemon = BlairDaemon(tmp_path)
    wrapped = AgentResult(
        "wrapped-session",
        "Completed.",
        "codex",
        metadata={"launch_id": "wrapper-launch", "consent_override": enabled},
    )

    daemon.pipeline.handle(wrapped)
    prompt.assert_not_called()
    assert daemon.pipeline.state.get("wrapped-session").enabled is enabled

    unrelated = AgentResult("unrelated-session", "Completed.", "claude")
    daemon.pipeline.handle(unrelated)
    prompt.assert_called_once_with("claude")
    assert daemon.pipeline.state.get("unrelated-session").enabled is not enabled
    daemon.pipeline.handle(unrelated)
    prompt.assert_called_once_with("claude")
    assert daemon.pipeline.state.get("wrapped-session").enabled is enabled


def test_start_daemon_does_not_inherit_wrapper_consent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BLAIR_CONSENT_RESPONSE", "yes")
    monkeypatch.setenv("BLAIR_LAUNCH_ID", "wrapper-launch")
    monkeypatch.setenv("BLAIR_TEST_KEEP", "preserved")
    monkeypatch.setattr("blair.daemon.daemon_pid", Mock(side_effect=[None, 123]))
    launch = Mock()
    monkeypatch.setattr("blair.daemon.subprocess.Popen", launch)

    assert start_daemon(tmp_path) == 123

    child_environment = launch.call_args.kwargs["env"]
    child_keys = {name for name in child_environment if name.startswith("BLAIR_")}
    assert "BLAIR_CONSENT_RESPONSE" not in child_keys
    assert "BLAIR_LAUNCH_ID" not in child_keys
    assert child_environment["BLAIR_TEST_KEEP"] == "preserved"
    assert child_environment["BLAIR_HOME"] == str(tmp_path)
    assert os.environ["BLAIR_CONSENT_RESPONSE"] == "yes"
    assert os.environ["BLAIR_LAUNCH_ID"] == "wrapper-launch"


def test_worker_continues_after_playback_start_fails(tmp_path: Path, monkeypatch) -> None:
    daemon = BlairDaemon(tmp_path)
    daemon.pipeline.state.ensure_session("session", provider="codex")
    daemon.pipeline.state.set_enabled(True, "session")
    artifact = SpeechArtifact(path=tmp_path / "synthetic.wav", backend="test", voice="test")
    handle = Mock(return_value=PipelineOutcome(False, "synthesized", artifact=artifact))
    play = Mock(side_effect=[OSError("Synthetic playback-start failure"), 123])
    monkeypatch.setattr(daemon.pipeline, "handle", handle)
    monkeypatch.setattr(daemon.pipeline.playback, "play", play)
    monkeypatch.setattr(daemon.pipeline.playback, "stop", Mock())

    first_finished = threading.Event()
    second_spoken = threading.Event()
    escaped: list[Exception] = []
    original_log = daemon._log

    def log(action, event=None, error=None):
        original_log(action, event, error)
        if action == "briefing-error":
            first_finished.set()
        elif action == "briefing-spoken":
            second_spoken.set()

    def work():
        try:
            daemon._work()
        except Exception as exc:
            escaped.append(exc)
        finally:
            first_finished.set()

    monkeypatch.setattr(daemon, "_log", log)
    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    try:
        daemon._enqueue_latest(event("first", "First completion."))
        assert first_finished.wait(timeout=3)
        assert not escaped, escaped
        assert worker.is_alive()

        daemon._enqueue_latest(event("second", "Second completion."))
        assert second_spoken.wait(timeout=3)
        assert worker.is_alive()
        assert handle.call_count == play.call_count == 2
        records = [
            json.loads(line) for line in (tmp_path / "logs/blair.log").read_text().splitlines()
        ]
        assert [record["action"] for record in records] == ["briefing-error", "briefing-spoken"]
        assert records[0]["error_type"] == "OSError"
        assert records[0]["event_hash"] != records[1]["event_hash"]
    finally:
        daemon.stop_event.set()
        daemon._signal_worker_stop()
        worker.join(timeout=3)
    assert not worker.is_alive()


@pytest.mark.skipif(os.name != "nt", reason="Windows console attachment behavior")
@pytest.mark.parametrize("auto_start", [False, True], ids=["direct", "event-auto-start"])
def test_windows_daemon_processes_events_without_a_window(tmp_path: Path, auto_start: bool) -> None:
    save_config(
        BlairConfig(backend="none", hotkeys_enabled=False, prompt_new_sessions=False), tmp_path
    )
    state = StateStore(tmp_path)
    state.ensure_session("session", provider="codex")
    state.set_enabled(True, "session")

    # Probe from a separate, windowless process so detaching its console cannot
    # affect pytest. Inspect the actual service PID, including the venv child.
    probe = """
import ctypes
import json
import sys
from ctypes import wintypes
from pathlib import Path

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.FreeConsole.argtypes = []
kernel32.FreeConsole.restype = wintypes.BOOL
kernel32.AttachConsole.argtypes = [wintypes.DWORD]
kernel32.AttachConsole.restype = wintypes.BOOL
kernel32.GetConsoleWindow.argtypes = []
kernel32.GetConsoleWindow.restype = wintypes.HWND
kernel32.FreeConsole()
attached = bool(kernel32.AttachConsole(int(sys.argv[1])))
error = ctypes.get_last_error() if not attached else 0
window = int(kernel32.GetConsoleWindow() or 0) if attached else 0
if attached:
    kernel32.FreeConsole()
Path(sys.argv[2]).write_text(json.dumps({"attached": attached, "error": error, "window": window}))
"""
    try:
        if not auto_start:
            start_daemon(tmp_path)
        enqueue_event(event(), tmp_path)
        pid = daemon_pid(tmp_path)
        assert pid is not None
        assert start_daemon(tmp_path) == pid
        result_path = tmp_path / "console-probe.json"
        subprocess.run(
            [sys.executable, "-c", probe, str(pid), str(result_path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=True,
            timeout=10,
        )
        console = json.loads(result_path.read_text())
        # A windowless console may still allow attachment. Require no HWND,
        # including the hidden message HWND used by a Windows Terminal console.
        assert console["window"] == 0, console
        assert console["attached"] or console["error"] == 6, console
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            session = state.get("session")
            if session and session.last_briefing and "Completed." in session.last_briefing:
                break
            time.sleep(0.05)
        else:
            pytest.fail("The windowless daemon did not process its completion event")
        assert daemon_pid(tmp_path) == pid
    finally:
        stopped = stop_daemon(tmp_path)
    assert stopped
    assert daemon_pid(tmp_path) is None
