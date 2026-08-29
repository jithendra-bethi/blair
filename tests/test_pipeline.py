from pathlib import Path

from blair.config import BlairConfig
from blair.consent import ConsentPrompter
from blair.models import AgentResult, SpeechArtifact
from blair.pipeline import BriefingPipeline
from blair.state import StateStore


class FakeBackend:
    name = "fake"

    def available(self) -> bool:
        return True

    def synthesize(
        self,
        text: str,
        output_path: Path,
        *,
        voice: str,
        language: str,
        speed: float,
    ) -> SpeechArtifact:
        del text, language, speed
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"RIFF" + b"0" * 100)
        return SpeechArtifact(output_path, self.name, voice, 24_000, 1.0)


class FakePlayback:
    def __init__(self) -> None:
        self.played: list[Path] = []
        self.stop_calls = 0

    def play(self, audio: Path, *, wait: bool = False) -> int:
        del wait
        self.played.append(audio)
        return 123

    def stop(self) -> bool:
        self.stop_calls += 1
        return True


def pipeline(tmp_path: Path, answer: bool) -> tuple[BriefingPipeline, FakePlayback]:
    playback = FakePlayback()
    config = BlairConfig(backend="auto")
    instance = BriefingPipeline(
        home=tmp_path,
        config=config,
        state=StateStore(tmp_path),
        backend=FakeBackend(),
        playback=playback,
        consent=ConsentPrompter(lambda provider, session: answer),
    )
    return instance, playback


def test_unknown_session_that_declines_never_speaks(tmp_path: Path) -> None:
    instance, playback = pipeline(tmp_path, answer=False)
    outcome = instance.handle(AgentResult("session", "Completed successfully.", "codex"))

    assert outcome.spoken is False
    assert outcome.reason == "session-disabled"
    assert playback.played == []


def test_consent_is_asked_once_and_subsequent_turn_speaks(tmp_path: Path) -> None:
    answers: list[tuple[str, str]] = []
    playback = FakePlayback()
    instance = BriefingPipeline(
        home=tmp_path,
        config=BlairConfig(),
        state=StateStore(tmp_path),
        backend=FakeBackend(),
        playback=playback,
        consent=ConsentPrompter(lambda provider, session: not answers.append((provider, session))),
    )

    first = instance.handle(AgentResult("session", "Implemented the feature.", "claude"))
    second = instance.handle(AgentResult("session", "All tests passed.", "claude"))

    assert first.spoken is True
    assert second.spoken is True
    assert answers == [("claude", "session")]
    assert len(playback.played) == 2


def test_sessions_remain_independent(tmp_path: Path) -> None:
    instance, playback = pipeline(tmp_path, answer=True)
    instance.state.ensure_session("off", "codex")
    instance.state.set_enabled(False, "off")
    instance.state.ensure_session("on", "codex")
    instance.state.set_enabled(True, "on")

    off = instance.handle(AgentResult("off", "Completed.", "codex"))
    on = instance.handle(AgentResult("on", "Completed.", "codex"))

    assert off.spoken is False
    assert on.spoken is True
    assert len(playback.played) == 1


def test_explicit_brief_implies_consent(tmp_path: Path) -> None:
    instance, playback = pipeline(tmp_path, answer=False)
    outcome = instance.handle(
        AgentResult("manual", "Completed and verified."),
        explicit=True,
        play=False,
    )

    assert outcome.reason == "synthesized"
    assert instance.state.get("manual").enabled is True
    assert playback.played == []


def test_new_wrapper_launch_applies_consent_once_then_allows_manual_toggle(tmp_path: Path) -> None:
    instance, playback = pipeline(tmp_path, answer=True)
    instance.state.ensure_session("resumed", "codex")
    instance.state.set_enabled(True, "resumed")

    first = AgentResult(
        "resumed",
        "This turn should stay silent.",
        "codex",
        metadata={"launch_id": "new-process", "consent_override": False},
    )
    assert instance.handle(first).reason == "session-disabled"

    instance.state.set_enabled(True, "resumed")
    second = instance.handle(first)
    assert second.reason == "spoken"
    assert len(playback.played) == 1
