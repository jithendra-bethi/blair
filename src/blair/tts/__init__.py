from __future__ import annotations

from pathlib import Path

from ..config import BlairConfig
from ..errors import TtsError
from .base import TtsBackend
from .kokoro import KokoroBackend, model_directory
from .windows import WindowsSapiBackend


def select_backend(config: BlairConfig, home: Path) -> TtsBackend:
    kokoro = KokoroBackend(model_directory(home))
    windows = WindowsSapiBackend()
    if config.backend == "none":
        raise TtsError("Speech is disabled in BLAIR configuration")
    if config.backend == "kokoro":
        if not kokoro.available():
            raise TtsError("Kokoro is selected but is not ready; run 'blair setup'")
        return kokoro
    if config.backend == "windows":
        if not windows.available():
            raise TtsError("Windows SAPI is selected but unavailable")
        return windows
    if kokoro.available():
        return kokoro
    if windows.available():
        return windows
    raise TtsError("No local speech backend is available")


__all__ = ["TtsBackend", "select_backend"]
