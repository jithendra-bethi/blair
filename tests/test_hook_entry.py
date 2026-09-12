from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from blair.hook_entry import run_hook
from blair.paths import ensure_layout


def test_malformed_hook_always_fails_open_and_does_not_echo_payload(tmp_path: Path, capsys) -> None:
    secret = "sk-this-must-never-be-logged-or-printed"

    assert run_hook("codex-notify", secret, home=tmp_path) == 0
    captured = capsys.readouterr()

    assert captured.out == ""
    assert captured.err == ""
    assert secret not in (tmp_path / "logs" / "blair.log").read_text(encoding="utf-8")


@pytest.mark.parametrize("kind", ["codex-notify", "claude-stop"])
def test_hook_fails_open_when_home_is_a_file(
    tmp_path: Path, capsys, monkeypatch, kind: str
) -> None:
    home = tmp_path / "blocked-home"
    home.write_text("Keep this file.", encoding="utf-8")
    enqueue = Mock()
    monkeypatch.setattr("blair.hook_entry.enqueue_event", enqueue)

    assert run_hook(kind, "private payload", home=home) == 0

    enqueue.assert_not_called()
    assert home.read_text(encoding="utf-8") == "Keep this file."
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


@pytest.mark.parametrize("kind", ["codex-notify", "claude-stop"])
def test_hook_logs_only_error_type_when_layout_is_denied(
    tmp_path: Path, capsys, monkeypatch, kind: str
) -> None:
    ensure_layout(tmp_path)
    private_detail = "private-path-and-payload"
    monkeypatch.setattr(
        "blair.hook_entry.ensure_layout", Mock(side_effect=PermissionError(private_detail))
    )
    enqueue = Mock()
    monkeypatch.setattr("blair.hook_entry.enqueue_event", enqueue)

    assert run_hook(kind, private_detail, home=tmp_path) == 0

    enqueue.assert_not_called()
    log = (tmp_path / "logs" / "blair.log").read_text(encoding="utf-8")
    assert private_detail not in log
    record = json.loads(log)
    assert record["action"] == "hook-failed-open"
    assert record["error_type"] == "PermissionError"
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("has_launch", [True, False])
def test_hook_only_attaches_consent_with_a_wrapper_launch(
    tmp_path: Path, monkeypatch, enabled: bool, has_launch: bool
) -> None:
    monkeypatch.setenv("BLAIR_CONSENT_RESPONSE", "yes" if enabled else "no")
    monkeypatch.delenv("BLAIR_LAUNCH_ID", raising=False)
    if has_launch:
        monkeypatch.setenv("BLAIR_LAUNCH_ID", "synthetic-launch")
    enqueue = Mock()
    monkeypatch.setattr("blair.hook_entry.enqueue_event", enqueue)
    payload = json.dumps(
        {
            "type": "agent-turn-complete",
            "thread-id": "synthetic-session",
            "turn-id": "synthetic-turn",
            "last-assistant-message": "Completed.",
        }
    )

    assert run_hook("codex-notify", payload, home=tmp_path) == 0

    enqueue.assert_called_once()
    metadata = enqueue.call_args.args[0].metadata
    if has_launch:
        assert metadata["launch_id"] == "synthetic-launch"
        assert metadata["consent_override"] is enabled
    else:
        assert "launch_id" not in metadata
        assert "consent_override" not in metadata
