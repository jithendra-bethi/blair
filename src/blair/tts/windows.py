from __future__ import annotations

import base64
import os
import shutil
import subprocess
import wave
from pathlib import Path

from ..errors import TtsError
from ..models import SpeechArtifact

SAPI_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$text = [Environment]::GetEnvironmentVariable('BLAIR_TTS_TEXT')
$output = [Environment]::GetEnvironmentVariable('BLAIR_TTS_OUTPUT')
$preferred = [Environment]::GetEnvironmentVariable('BLAIR_TTS_WINDOWS_VOICE')
$synth = [System.Speech.Synthesis.SpeechSynthesizer]::new()
try {
    $voices = @($synth.GetInstalledVoices() | Where-Object { $_.Enabled })
    $selected = $null
    if ($preferred) {
        $selected = $voices |
            Where-Object { $_.VoiceInfo.Name -eq $preferred } |
            Select-Object -First 1
    }
    if (-not $selected) {
        $selected = $voices | Where-Object {
            $_.VoiceInfo.Culture.Name -eq 'en-GB' -and $_.VoiceInfo.Gender.ToString() -eq 'Female'
        } | Select-Object -First 1
    }
    if ($selected) { $synth.SelectVoice($selected.VoiceInfo.Name) }
    $synth.Volume = 100
    $synth.Rate = 0
    $synth.SetOutputToWaveFile($output)
    $synth.Speak($text)
    $synth.SetOutputToNull()
    Write-Output $synth.Voice.Name
}
finally {
    $synth.Dispose()
}
"""

VOICE_LIST_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$synth = [System.Speech.Synthesis.SpeechSynthesizer]::new()
try {
    $synth.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object {
        "{0}`t{1}`t{2}" -f $_.VoiceInfo.Name, $_.VoiceInfo.Culture.Name, $_.VoiceInfo.Gender
    }
}
finally { $synth.Dispose() }
"""


class WindowsSapiBackend:
    """Always-local Windows speech fallback using the installed SAPI voices."""

    name = "windows-sapi"

    def __init__(self, preferred_voice: str = "") -> None:
        self.preferred_voice = preferred_voice

    @staticmethod
    def executable() -> str | None:
        system_root = Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
        candidate = system_root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        if candidate.exists():
            return str(candidate)
        return shutil.which("powershell.exe") or shutil.which("powershell")

    def available(self) -> bool:
        return os.name == "nt" and self.executable() is not None

    def synthesize(
        self,
        text: str,
        output_path: Path,
        *,
        voice: str,
        language: str,
        speed: float,
    ) -> SpeechArtifact:
        del voice, language, speed
        executable = self.executable()
        if os.name != "nt" or not executable:
            raise TtsError("Windows SAPI is unavailable on this system")
        if not text.strip():
            raise TtsError("Cannot synthesize an empty briefing")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        environment.update(
            {
                "BLAIR_TTS_TEXT": text,
                "BLAIR_TTS_OUTPUT": str(output_path.resolve()),
                "BLAIR_TTS_WINDOWS_VOICE": self.preferred_voice,
            }
        )
        encoded = base64.b64encode(SAPI_SCRIPT.encode("utf-16-le")).decode("ascii")
        try:
            completed = subprocess.run(
                [
                    executable,
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-EncodedCommand",
                    encoded,
                ],
                env=environment,
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exc:
            output_path.unlink(missing_ok=True)
            raise TtsError("Windows speech synthesis timed out") from exc
        except (OSError, UnicodeError) as exc:
            output_path.unlink(missing_ok=True)
            raise TtsError("Windows speech synthesis could not start") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise TtsError(f"Windows speech synthesis failed: {detail or 'unknown error'}")
        if not output_path.exists() or output_path.stat().st_size <= 44:
            raise TtsError("Windows speech synthesis did not produce a valid WAV file")

        duration, sample_rate = _wave_metadata(output_path)
        selected_voice = (
            completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else "SAPI"
        )
        return SpeechArtifact(
            path=output_path,
            backend=self.name,
            voice=selected_voice,
            sample_rate=sample_rate,
            duration_seconds=duration,
        )


def installed_voices() -> list[str]:
    executable = WindowsSapiBackend.executable()
    if os.name != "nt" or not executable:
        return []
    encoded = base64.b64encode(VOICE_LIST_SCRIPT.encode("utf-16-le")).decode("ascii")
    try:
        completed = subprocess.run(
            [
                executable,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-EncodedCommand",
                encoded,
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return []
    if completed.returncode != 0:
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def _wave_metadata(path: Path) -> tuple[float | None, int | None]:
    try:
        with wave.open(str(path), "rb") as stream:
            rate = stream.getframerate()
            duration = stream.getnframes() / rate if rate else None
            return duration, rate
    except (OSError, wave.Error):
        return None, None
