from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import _atomic_json_write
from .locking import file_lock
from .paths import blair_home, ensure_layout


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class SessionState:
    session_id: str
    provider: str = "generic"
    cwd: str | None = None
    enabled: bool | None = None
    asked: bool = False
    updated_at: str = ""
    last_briefing: str | None = None
    last_audio: str | None = None
    launch_id: str | None = None

    @classmethod
    def from_dict(cls, session_id: str, value: dict[str, Any]) -> SessionState:
        return cls(
            session_id=session_id,
            provider=str(value.get("provider", "generic")),
            cwd=value.get("cwd"),
            enabled=value.get("enabled"),
            asked=bool(value.get("asked", False)),
            updated_at=str(value.get("updated_at", "")),
            last_briefing=value.get("last_briefing"),
            last_audio=value.get("last_audio"),
            launch_id=value.get("launch_id"),
        )


class StateStore:
    """Small atomic JSON store shared by hooks and CLI commands."""

    def __init__(self, home: Path | None = None) -> None:
        self.home = home or blair_home()
        self.path = self.home / "sessions.json"
        self.lock_path = self.home / "runtime" / "sessions.lock"

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "active_session": None, "sessions": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"BLAIR state is unreadable: {self.path}: {exc}") from exc
        if data.get("version") != 1 or not isinstance(data.get("sessions"), dict):
            raise RuntimeError(f"Unsupported BLAIR state format: {self.path}")
        return data

    def _write(self, data: dict[str, Any]) -> None:
        ensure_layout(self.home)
        _atomic_json_write(self.path, data)

    def ensure_session(
        self, session_id: str, provider: str = "generic", cwd: str | None = None
    ) -> SessionState:
        if not session_id.strip():
            raise ValueError("session_id must not be empty")
        with file_lock(self.lock_path):
            data = self._read()
            raw = data["sessions"].get(session_id, {})
            state = SessionState.from_dict(session_id, raw)
            state.provider = provider or state.provider
            state.cwd = cwd or state.cwd
            state.updated_at = _now()
            data["sessions"][session_id] = self._serialize(state)
            data["active_session"] = session_id
            self._write(data)
            return state

    def get(self, session_id: str | None = None) -> SessionState | None:
        with file_lock(self.lock_path):
            data = self._read()
            target = session_id or data.get("active_session")
            if not target:
                return None
            raw = data["sessions"].get(target)
            return SessionState.from_dict(target, raw) if raw else None

    def set_enabled(
        self, enabled: bool, session_id: str | None = None, *, asked: bool = True
    ) -> SessionState:
        with file_lock(self.lock_path):
            data = self._read()
            target = session_id or data.get("active_session")
            if not target:
                raise RuntimeError("No BLAIR session is active")
            raw = data["sessions"].get(target, {})
            state = SessionState.from_dict(target, raw)
            state.enabled = enabled
            state.asked = asked
            state.updated_at = _now()
            data["sessions"][target] = self._serialize(state)
            data["active_session"] = target
            self._write(data)
            return state

    def record_briefing(self, session_id: str, text: str, audio: Path | None) -> SessionState:
        with file_lock(self.lock_path):
            data = self._read()
            raw = data["sessions"].get(session_id, {})
            state = SessionState.from_dict(session_id, raw)
            state.last_briefing = text
            state.last_audio = str(audio) if audio else None
            state.updated_at = _now()
            data["sessions"][session_id] = self._serialize(state)
            data["active_session"] = session_id
            self._write(data)
            return state

    def begin_launch(self, session_id: str, launch_id: str, enabled: bool) -> SessionState:
        if not launch_id.strip():
            raise ValueError("launch_id must not be empty")
        with file_lock(self.lock_path):
            data = self._read()
            raw = data["sessions"].get(session_id, {})
            state = SessionState.from_dict(session_id, raw)
            state.launch_id = launch_id
            state.enabled = enabled
            state.asked = True
            state.updated_at = _now()
            data["sessions"][session_id] = self._serialize(state)
            data["active_session"] = session_id
            self._write(data)
            return state

    def sessions(self) -> list[SessionState]:
        with file_lock(self.lock_path):
            data = self._read()
            return [
                SessionState.from_dict(session_id, raw)
                for session_id, raw in data["sessions"].items()
            ]

    @staticmethod
    def _serialize(state: SessionState) -> dict[str, Any]:
        value = asdict(state)
        value.pop("session_id")
        return value
