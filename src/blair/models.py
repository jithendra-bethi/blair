from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class AgentResult:
    """Provider-neutral representation of one completed agent turn."""

    session_id: str
    text: str
    provider: str = "generic"
    cwd: str | None = None
    event: str = "agent-turn-complete"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Briefing:
    """Short, speech-safe report derived from an agent result."""

    text: str
    status: str
    had_table: bool = False
    had_code: bool = False
    source: str = "deterministic"


@dataclass(slots=True)
class SpeechArtifact:
    """A synthesized local audio file."""

    path: Path
    backend: str
    voice: str
    sample_rate: int | None = None
    duration_seconds: float | None = None
