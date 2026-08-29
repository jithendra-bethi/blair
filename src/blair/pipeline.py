from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .briefing import compose_briefing
from .config import BlairConfig, load_config
from .consent import ConsentPrompter
from .models import AgentResult, Briefing, SpeechArtifact
from .paths import blair_home, ensure_layout
from .playback import PlaybackController
from .state import StateStore
from .tts import TtsBackend, select_backend


@dataclass(slots=True)
class PipelineOutcome:
    spoken: bool
    reason: str
    briefing: Briefing | None = None
    artifact: SpeechArtifact | None = None


class BriefingPipeline:
    def __init__(
        self,
        *,
        home: Path | None = None,
        config: BlairConfig | None = None,
        state: StateStore | None = None,
        backend: TtsBackend | None = None,
        playback: PlaybackController | None = None,
        consent: ConsentPrompter | None = None,
    ) -> None:
        self.home = home or blair_home()
        self.config = config or load_config(self.home)
        self.state = state or StateStore(self.home)
        self.backend = backend
        self.playback = playback or PlaybackController(self.home)
        self.consent = consent or ConsentPrompter()

    def handle(
        self,
        result: AgentResult,
        *,
        explicit: bool = False,
        allow_prompt: bool = True,
        play: bool | None = None,
        wait: bool = False,
    ) -> PipelineOutcome:
        session = self.state.ensure_session(result.session_id, result.provider, result.cwd)
        launch_id = result.metadata.get("launch_id")
        consent_override = result.metadata.get("consent_override")
        if (
            isinstance(launch_id, str)
            and launch_id
            and session.launch_id != launch_id
            and isinstance(consent_override, bool)
        ):
            session = self.state.begin_launch(result.session_id, launch_id, consent_override)
        if explicit and session.enabled is None:
            session = self.state.set_enabled(True, result.session_id)
        elif session.enabled is None:
            if allow_prompt and self.config.prompt_new_sessions:
                enabled = self.consent.ask(result.provider, result.session_id)
                session = self.state.set_enabled(enabled, result.session_id)
            else:
                return PipelineOutcome(False, "session-consent-unknown")
        if session.enabled is not True:
            return PipelineOutcome(False, "session-disabled")

        briefing = compose_briefing(
            result,
            honorific=self.config.honorific,
            max_words=self.config.max_words,
        )
        if self.config.backend == "none":
            self.state.record_briefing(result.session_id, briefing.text, None)
            return PipelineOutcome(False, "speech-disabled", briefing=briefing)

        should_play = self.config.play_audio if play is None else play
        if should_play:
            self.playback.stop()

        root = ensure_layout(self.home)
        safe_session = re.sub(r"[^A-Za-z0-9_.-]+", "-", result.session_id)[:60] or "session"
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        output_path = root / "audio" / f"{safe_session}-{stamp}.wav"
        backend = self.backend or select_backend(self.config, root)
        self.backend = backend
        artifact = backend.synthesize(
            briefing.text,
            output_path,
            voice=self.config.voice,
            language=self.config.language,
            speed=self.config.speed,
        )
        self.state.record_briefing(result.session_id, briefing.text, artifact.path)
        self._prune_audio()

        if should_play:
            self.playback.play(artifact.path, wait=wait)
            return PipelineOutcome(True, "spoken", briefing=briefing, artifact=artifact)
        return PipelineOutcome(False, "synthesized", briefing=briefing, artifact=artifact)

    def _prune_audio(self) -> None:
        keep = self.config.keep_audio_files
        files = sorted(
            (self.home / "audio").glob("*.wav"), key=lambda item: item.stat().st_mtime, reverse=True
        )
        for stale in files[keep:]:
            stale.unlink(missing_ok=True)
