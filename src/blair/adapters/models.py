from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from blair.models import AgentResult


@dataclass(slots=True)
class NormalizedEvent:
    """Provider-neutral completion event produced by a BLAIR adapter."""

    event_id: str
    provider: str
    session_id: str
    text: str
    event_name: str
    cwd: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_agent_result(self) -> AgentResult:
        """Convert to the core pipeline type without losing the dedupe identifier."""

        metadata = dict(self.metadata)
        metadata["event_id"] = self.event_id
        return AgentResult(
            session_id=self.session_id,
            text=self.text,
            provider=self.provider,
            cwd=self.cwd,
            event=self.event_name,
            metadata=metadata,
        )
