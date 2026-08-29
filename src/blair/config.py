from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from .paths import blair_home, ensure_layout

_VOICE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_LANGUAGE_PATTERN = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z]{2,4})?$")


@dataclass(slots=True)
class BlairConfig:
    backend: str = "auto"
    voice: str = "bf_emma"
    language: str = "en-gb"
    speed: float = 1.03
    honorific: str = "sir"
    max_words: int = 58
    prompt_new_sessions: bool = True
    play_audio: bool = True
    keep_audio_files: int = 10
    hotkeys_enabled: bool = True
    hotkey_toggle: str = "ctrl+alt+b"
    hotkey_replay: str = "ctrl+alt+r"
    hotkey_stop: str = "ctrl+alt+s"

    def validate(self) -> None:
        if self.backend not in {"auto", "kokoro", "windows", "none"}:
            raise ValueError(f"Unsupported backend: {self.backend}")
        if not isinstance(self.voice, str) or _VOICE_PATTERN.fullmatch(self.voice) is None:
            raise ValueError("voice must be a local Kokoro voice identifier")
        if not isinstance(self.language, str) or _LANGUAGE_PATTERN.fullmatch(self.language) is None:
            raise ValueError("language must be a short language tag such as en-gb")
        if (
            isinstance(self.speed, bool)
            or not isinstance(self.speed, (int, float))
            or not 0.5 <= self.speed <= 2.0
        ):
            raise ValueError("speed must be between 0.5 and 2.0")
        if (
            isinstance(self.max_words, bool)
            or not isinstance(self.max_words, int)
            or not 20 <= self.max_words <= 120
        ):
            raise ValueError("max_words must be between 20 and 120")
        if (
            isinstance(self.keep_audio_files, bool)
            or not isinstance(self.keep_audio_files, int)
            or not 1 <= self.keep_audio_files <= 100
        ):
            raise ValueError("keep_audio_files must be between 1 and 100 so replay remains safe")


def config_path(home: Path | None = None) -> Path:
    return (home or blair_home()) / "config.json"


def load_config(home: Path | None = None) -> BlairConfig:
    path = config_path(home)
    if not path.exists():
        config = BlairConfig()
        config.validate()
        return config
    raw = json.loads(path.read_text(encoding="utf-8"))
    allowed = {item.name for item in fields(BlairConfig)}
    config = BlairConfig(**{key: value for key, value in raw.items() if key in allowed})
    config.validate()
    return config


def save_config(config: BlairConfig, home: Path | None = None) -> Path:
    config.validate()
    root = ensure_layout(home)
    path = root / "config.json"
    _atomic_json_write(path, asdict(config))
    return path


def _atomic_json_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
