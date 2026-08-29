from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from blair.errors import TtsError
from blair.tts import windows


def _timeout(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
    del args, kwargs
    raise subprocess.TimeoutExpired("powershell", 1)


def test_voice_diagnostics_degrade_gracefully_when_sapi_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(windows.os, "name", "nt")
    monkeypatch.setattr(windows.WindowsSapiBackend, "executable", staticmethod(lambda: "pwsh"))
    monkeypatch.setattr(windows.subprocess, "run", _timeout)

    assert windows.installed_voices() == []


def test_sapi_timeout_becomes_tts_error_and_removes_partial_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(windows.os, "name", "nt")
    monkeypatch.setattr(windows.WindowsSapiBackend, "executable", staticmethod(lambda: "pwsh"))
    monkeypatch.setattr(windows.subprocess, "run", _timeout)
    output = tmp_path / "partial.wav"
    output.write_bytes(b"partial")

    with pytest.raises(TtsError, match="timed out"):
        windows.WindowsSapiBackend().synthesize(
            "Safe synthetic briefing.",
            output,
            voice="",
            language="en-gb",
            speed=1.0,
        )

    assert not output.exists()
