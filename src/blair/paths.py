from __future__ import annotations

import os
from pathlib import Path


def blair_home() -> Path:
    override = os.environ.get("BLAIR_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "BLAIR"
    state_home = os.environ.get("XDG_STATE_HOME")
    return (
        Path(state_home).expanduser() / "blair"
        if state_home
        else Path.home() / ".local" / "state" / "blair"
    )


def ensure_layout(home: Path | None = None) -> Path:
    root = home or blair_home()
    root.mkdir(parents=True, exist_ok=True)
    for child in ("audio", "models", "logs"):
        (root / child).mkdir(exist_ok=True)
    return root
