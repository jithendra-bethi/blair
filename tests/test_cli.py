from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from blair import cli, daemon
from blair.state import StateStore


@pytest.mark.parametrize(
    "arguments,expected",
    [
        (["run", "codex", "--model", "test-model"], ["--model", "test-model"]),
        (
            ["run", "codex", "--briefings", "on", "--", "--model", "test-model"],
            ["--model", "test-model"],
        ),
    ],
)
def test_run_forwards_agent_arguments_without_separator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
    expected: list[str],
) -> None:
    captured: list[argparse.Namespace] = []
    monkeypatch.setattr(cli, "ensure_layout", lambda: tmp_path)

    def dispatch(args: argparse.Namespace, _home: Path) -> int:
        captured.append(args)
        return 0

    monkeypatch.setattr(cli, "_dispatch", dispatch)

    assert cli.main(arguments) == 0
    assert captured[0].agent_args == expected


def test_doctor_survives_transient_empty_windows_voice_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "installed_voices", lambda: [])
    monkeypatch.setattr(cli.WindowsSapiBackend, "available", lambda _self: True)
    monkeypatch.setattr(cli, "integration_status", lambda: {"codex": False, "claude": False})
    monkeypatch.setattr(cli, "models_ready", lambda _path: False)
    monkeypatch.setattr(cli.importlib.util, "find_spec", lambda _name: None)
    monkeypatch.setattr(daemon, "daemon_pid", lambda _home: None)

    assert cli._doctor(tmp_path) == 0
    assert "windows_voices: none detected" in capsys.readouterr().out


def test_global_mute_commands_preserve_session_permissions(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ensure_layout", lambda: tmp_path)
    state = StateStore(tmp_path)
    state.ensure_session("one", "codex")
    state.set_enabled(True, "one")
    assert cli.main(["mute"]) == 0
    assert cli.main(["status", "--session", "one"]) == 0
    assert "muted globally" in capsys.readouterr().out
    assert state.is_speech_muted()
    assert state.get("one").enabled is True
    assert cli.main(["unmute"]) == 0
    assert not state.is_speech_muted()
    assert state.get("one").enabled is True


def test_manual_brief_explains_global_mute(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ensure_layout", lambda: tmp_path)
    StateStore(tmp_path).set_speech_muted(True)
    assert cli.main(["brief", "Completed successfully."]) == 0
    assert "blair unmute" in capsys.readouterr().out
