from __future__ import annotations

import json
import re
import shutil
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import _atomic_json_write
from .errors import BlairError
from .runtime import self_command

CODEX_BEGIN = "# >>> BLAIR managed notify >>>"
CODEX_END = "# <<< BLAIR managed notify <<<"


@dataclass(frozen=True, slots=True)
class IntegrationResult:
    provider: str
    changed: bool
    path: Path
    detail: str
    backup: Path | None = None


def default_codex_config() -> Path:
    return Path.home() / ".codex" / "config.toml"


def default_claude_settings() -> Path:
    return Path.home() / ".claude" / "settings.json"


def install_codex(config_path: Path | None = None) -> IntegrationResult:
    path = config_path or default_codex_config()
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    command = self_command("hook", "codex-notify")
    encoded = ", ".join(json.dumps(part) for part in command)
    block = f"{CODEX_BEGIN}\nnotify = [{encoded}]\n{CODEX_END}\n\n"
    if CODEX_BEGIN in original or CODEX_END in original:
        if CODEX_BEGIN in original and CODEX_END in original:
            pattern = _codex_block_pattern()
            match = pattern.search(original)
            if not match:
                raise BlairError(f"Malformed BLAIR block in {path}; repair it before installing")
            if match.group(0) == block:
                return IntegrationResult("codex", False, path, "already installed")
            backup = _backup(path)
            _write_text_atomic(path, original[: match.start()] + block + original[match.end() :])
            return IntegrationResult("codex", True, path, "updated", backup)
        raise BlairError(f"Incomplete BLAIR block in {path}; repair it before installing")

    if original.strip():
        try:
            parsed = tomllib.loads(original)
        except tomllib.TOMLDecodeError as exc:
            raise BlairError(f"Codex configuration is invalid and was not changed: {exc}") from exc
        if "notify" in parsed:
            raise BlairError(
                "Codex already has a notify command. BLAIR will not overwrite it; "
                f"see {path} and the manual integration guide."
            )

    header = re.search(r"(?m)^\s*\[", original)
    position = header.start() if header else len(original)
    prefix = original[:position]
    suffix = original[position:]
    updated = prefix + block + suffix
    backup = _backup(path) if path.exists() else None
    _write_text_atomic(path, updated)
    return IntegrationResult("codex", True, path, "installed", backup)


def uninstall_codex(config_path: Path | None = None) -> IntegrationResult:
    path = config_path or default_codex_config()
    if not path.exists():
        return IntegrationResult("codex", False, path, "not installed")
    original = path.read_text(encoding="utf-8")
    pattern = _codex_block_pattern()
    updated, count = pattern.subn("", original, count=1)
    if not count:
        return IntegrationResult("codex", False, path, "not installed")
    backup = _backup(path)
    _write_text_atomic(path, updated)
    return IntegrationResult("codex", True, path, "removed", backup)


def install_claude(settings_path: Path | None = None) -> IntegrationResult:
    path = settings_path or default_claude_settings()
    data = _read_json_object(path)
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise BlairError(f"Claude 'hooks' must be an object in {path}; nothing was changed")

    changed = False
    for event, argument in (("Stop", "claude-stop"), ("StopFailure", "claude-failure")):
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            raise BlairError(f"Claude hooks.{event} must be a list in {path}; nothing was changed")
        command = self_command("hook", argument)
        hook = {
            "type": "command",
            "command": command[0],
            "args": command[1:],
            "timeout": 5,
            "statusMessage": "BLAIR is preparing a local completion briefing",
        }
        if _contains_blair_hook(groups, argument):
            changed = _update_blair_hooks(groups, argument, hook) or changed
        else:
            groups.append({"hooks": [hook]})
            changed = True

    if not changed:
        return IntegrationResult("claude", False, path, "already installed")
    backup = _backup(path) if path.exists() else None
    _atomic_json_write(path, data)
    return IntegrationResult("claude", True, path, "installed", backup)


def uninstall_claude(settings_path: Path | None = None) -> IntegrationResult:
    path = settings_path or default_claude_settings()
    if not path.exists():
        return IntegrationResult("claude", False, path, "not installed")
    data = _read_json_object(path)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return IntegrationResult("claude", False, path, "not installed")

    changed = False
    for event, argument in (("Stop", "claude-stop"), ("StopFailure", "claude-failure")):
        groups = hooks.get(event)
        if not isinstance(groups, list):
            continue
        retained = [group for group in groups if not _group_has_blair_hook(group, argument)]
        if len(retained) != len(groups):
            changed = True
            if retained:
                hooks[event] = retained
            else:
                hooks.pop(event, None)
    if not changed:
        return IntegrationResult("claude", False, path, "not installed")
    if not hooks:
        data.pop("hooks", None)
    backup = _backup(path)
    _atomic_json_write(path, data)
    return IntegrationResult("claude", True, path, "removed", backup)


def integration_status(
    codex_path: Path | None = None, claude_path: Path | None = None
) -> dict[str, bool]:
    codex = codex_path or default_codex_config()
    claude = claude_path or default_claude_settings()
    codex_installed = codex.exists() and CODEX_BEGIN in codex.read_text(
        encoding="utf-8", errors="replace"
    )
    claude_installed = False
    if claude.exists():
        try:
            data = _read_json_object(claude)
            hooks = data.get("hooks", {})
            claude_installed = isinstance(hooks, dict) and all(
                _contains_blair_hook(hooks.get(event, []), argument)
                for event, argument in (
                    ("Stop", "claude-stop"),
                    ("StopFailure", "claude-failure"),
                )
            )
        except BlairError:
            claude_installed = False
    return {"codex": codex_installed, "claude": claude_installed}


def _contains_blair_hook(groups: object, argument: str) -> bool:
    return isinstance(groups, list) and any(
        _group_has_blair_hook(group, argument) for group in groups
    )


def _update_blair_hooks(groups: list[object], argument: str, replacement: dict[str, Any]) -> bool:
    changed = False
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
            continue
        for index, hook in enumerate(group["hooks"]):
            if not isinstance(hook, dict):
                continue
            args = hook.get("args", [])
            if (
                hook.get("type") == "command"
                and isinstance(args, list)
                and "hook" in args
                and argument in args
                and hook != replacement
            ):
                group["hooks"][index] = replacement
                changed = True
    return changed


def _codex_block_pattern() -> re.Pattern[str]:
    return re.compile(
        rf"(?m)^{re.escape(CODEX_BEGIN)}\r?\n"
        rf"notify = [^\r\n]*\r?\n{re.escape(CODEX_END)}\r?\n\r?\n"
    )


def _group_has_blair_hook(group: object, argument: str) -> bool:
    if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
        return False
    for hook in group["hooks"]:
        if not isinstance(hook, dict) or hook.get("type") != "command":
            continue
        args = hook.get("args", [])
        if isinstance(args, list) and "hook" in args and argument in args:
            return True
    return False


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BlairError(f"Invalid JSON in {path}; nothing was changed: {exc}") from exc
    if not isinstance(value, dict):
        raise BlairError(f"Expected a JSON object in {path}; nothing was changed")
    return value


def _backup(path: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.name}.blair-backup-{stamp}")
    counter = 1
    while backup.exists():
        backup = path.with_name(f"{path.name}.blair-backup-{stamp}-{counter}")
        counter += 1
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup)
    return backup


def _write_text_atomic(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.blair.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        temporary.write_text(text, encoding="utf-8", newline="\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
