from __future__ import annotations

from pathlib import Path

from blair.adapters.models import NormalizedEvent
from blair.daemon import BlairDaemon, EventLedger


def event(event_id: str = "one", text: str = "Completed.") -> NormalizedEvent:
    return NormalizedEvent(
        event_id=event_id,
        provider="codex",
        session_id="session",
        text=text,
        event_name="agent-turn-complete",
    )


def test_ledger_deduplicates_event_ids_without_persisting_content(tmp_path: Path) -> None:
    ledger = EventLedger(tmp_path)

    assert ledger.seen_or_add(event(), now=100.0) is False
    assert ledger.seen_or_add(event(), now=101.0) is True
    assert "Completed" not in ledger.path.read_text(encoding="utf-8")


def test_ledger_suppresses_immediate_claude_style_redelivery(tmp_path: Path) -> None:
    ledger = EventLedger(tmp_path, duplicate_window=8.0)

    assert ledger.seen_or_add(event("transport-1"), now=100.0) is False
    assert ledger.seen_or_add(event("transport-2"), now=105.0) is True
    assert ledger.seen_or_add(event("transport-3"), now=120.0) is False


def test_pending_queue_keeps_only_the_newest_completion(tmp_path: Path) -> None:
    daemon = BlairDaemon(tmp_path)

    daemon._enqueue_latest(event("old", "Old completion."))
    daemon._enqueue_latest(event("new", "New completion."))
    sequence, pending = daemon.events.get_nowait()

    assert sequence == 2
    assert pending.event_id == "new"
