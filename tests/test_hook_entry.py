from __future__ import annotations

from pathlib import Path

from blair.hook_entry import run_hook


def test_malformed_hook_always_fails_open_and_does_not_echo_payload(tmp_path: Path, capsys) -> None:
    secret = "sk-this-must-never-be-logged-or-printed"

    assert run_hook("codex-notify", secret, home=tmp_path) == 0
    captured = capsys.readouterr()

    assert captured.out == ""
    assert captured.err == ""
    assert secret not in (tmp_path / "logs" / "blair.log").read_text(encoding="utf-8")
