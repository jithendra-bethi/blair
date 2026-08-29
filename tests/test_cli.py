from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from blair import cli, daemon


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
