from __future__ import annotations

import json
from pathlib import Path

import pytest

from blair.errors import BlairError
from blair.integrations import (
    install_claude,
    install_codex,
    integration_status,
    uninstall_claude,
    uninstall_codex,
)


def test_codex_install_preserves_config_and_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    original = 'model = "gpt-5"\n\n[features]\nweb_search = true\n'
    path.write_text(original, encoding="utf-8")

    installed = install_codex(path)
    text = path.read_text(encoding="utf-8")

    assert installed.changed is True
    assert installed.backup and installed.backup.read_text(encoding="utf-8") == original
    assert "notify =" in text
    assert text.index("notify =") < text.index("[features]")
    assert install_codex(path).changed is False
    assert integration_status(path, tmp_path / "missing.json")["codex"] is True

    removed = uninstall_codex(path)
    assert removed.changed is True
    assert path.read_text(encoding="utf-8").strip() == original.strip()


def test_codex_managed_command_is_updated_without_duplicate_block(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    install_codex(path)
    changed = path.read_text(encoding="utf-8")
    changed = changed.replace("notify = [", 'notify = ["old-launcher", ', 1)
    path.write_text(changed, encoding="utf-8")

    result = install_codex(path)

    assert result.changed is True
    assert result.detail == "updated"
    assert path.read_text(encoding="utf-8").count("BLAIR managed notify >>>") == 1
    assert "old-launcher" not in path.read_text(encoding="utf-8")


def test_codex_existing_notify_is_never_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    original = 'notify = ["existing.exe"]\n'
    path.write_text(original, encoding="utf-8")

    with pytest.raises(BlairError, match="will not overwrite"):
        install_codex(path)

    assert path.read_text(encoding="utf-8") == original


def test_claude_hooks_merge_and_remove_without_touching_existing(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    existing = {
        "permissions": {"allow": ["Read"]},
        "hooks": {
            "Stop": [
                {
                    "matcher": "legacy",
                    "hooks": [{"type": "command", "command": "existing.exe"}],
                }
            ]
        },
    }
    path.write_text(json.dumps(existing), encoding="utf-8")

    installed = install_claude(path)
    assert installed.changed is True
    generated = json.loads(path.read_text(encoding="utf-8"))
    blair_stop = generated["hooks"]["Stop"][-1]["hooks"][0]
    assert blair_stop["args"][-2:] == ["hook", "claude-stop"]
    assert "async" not in blair_stop
    assert install_claude(path).changed is False
    assert integration_status(tmp_path / "missing.toml", path)["claude"] is True

    removed = uninstall_claude(path)
    restored = json.loads(path.read_text(encoding="utf-8"))
    assert removed.changed is True
    assert restored == existing


def test_claude_managed_commands_are_updated_in_place(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    install_claude(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["hooks"]["Stop"][-1]["hooks"][0]["command"] = "C:\\old-python.exe"
    path.write_text(json.dumps(data), encoding="utf-8")

    result = install_claude(path)
    updated = json.loads(path.read_text(encoding="utf-8"))

    assert result.changed is True
    assert result.detail == "installed"
    assert updated["hooks"]["Stop"][-1]["hooks"][0]["command"] != "C:\\old-python.exe"
    assert len(updated["hooks"]["Stop"]) == 1
