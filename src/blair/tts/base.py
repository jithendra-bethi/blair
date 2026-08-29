from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..models import SpeechArtifact


class TtsBackend(Protocol):
    name: str

    def available(self) -> bool: ...

    def synthesize(
        self,
        text: str,
        output_path: Path,
        *,
        voice: str,
        language: str,
        speed: float,
    ) -> SpeechArtifact: ...
