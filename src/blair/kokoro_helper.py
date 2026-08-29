"""Persistent, offline Kokoro worker used by the Windows briefing process.

The worker deliberately has a small JSON-lines boundary.  It imports Kokoro only
after removing environment overrides and accepts model files supplied by the
caller; it has no model download or other network code.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import threading
import wave
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TextIO

import numpy as np
from numpy.typing import ArrayLike

VOICE = "bf_emma"
LANGUAGE = "en-gb"
SPEED = 1.03
_UNTRUSTED_ENVIRONMENT = ("ONNX_PROVIDER", "PHONEMIZER_ESPEAK_LIBRARY")
_VOICE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_LANGUAGE_PATTERN = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z]{2,4})?$")


class KokoroEngine(Protocol):
    """The subset of ``kokoro_onnx.Kokoro`` used by this process."""

    def create(
        self,
        text: str,
        *,
        voice: str,
        speed: float,
        lang: str,
        trim: bool,
        continuous: bool,
    ) -> tuple[ArrayLike, int]: ...


EngineFactory = Callable[[str, str], KokoroEngine]


@dataclass(frozen=True, slots=True)
class WavMetrics:
    sample_rate: int
    frames: int
    duration: float
    rms: float


class ProtocolError(Exception):
    """A safe, pre-authored protocol error that contains no request content."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _local_path(value: str | os.PathLike[str]) -> Path:
    """Return a filesystem path while rejecting explicit network locations."""

    raw = os.fspath(value)
    if not raw or raw.startswith(("\\\\", "//")) or "://" in raw:
        raise ValueError("A local filesystem path is required")
    return Path(raw)


def write_wav(
    output_path: str | os.PathLike[str], samples: ArrayLike, sample_rate: int
) -> WavMetrics:
    """Atomically encode finite, one-dimensional samples as mono PCM16 WAV.

    Samples outside ``[-1.0, 1.0]`` are clipped.  Metrics are calculated from
    that clipped floating-point signal, before integer quantization.
    """

    if isinstance(sample_rate, bool) or not isinstance(sample_rate, (int, np.integer)):
        raise ValueError("sample_rate must be a positive integer")
    rate = int(sample_rate)
    if rate <= 0:
        raise ValueError("sample_rate must be a positive integer")

    try:
        signal = np.asarray(samples, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError("samples must be a numeric mono signal") from exc
    if signal.ndim != 1 or signal.size == 0:
        raise ValueError("samples must be a non-empty mono signal")
    if not np.isfinite(signal).all():
        raise ValueError("samples must contain only finite values")

    clipped = np.clip(signal, -1.0, 1.0)
    scaled = np.where(clipped < 0.0, clipped * 32768.0, clipped * 32767.0)
    pcm = np.rint(scaled).astype("<i2")
    frames = int(pcm.size)
    rms = float(np.sqrt(np.mean(np.square(clipped), dtype=np.float64)))

    destination = _local_path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as raw_stream:
            with wave.open(raw_stream, "wb") as wav_stream:
                wav_stream.setnchannels(1)
                wav_stream.setsampwidth(2)
                wav_stream.setframerate(rate)
                wav_stream.writeframes(pcm.tobytes(order="C"))
            raw_stream.flush()
            os.fsync(raw_stream.fileno())
        os.replace(temporary_path, destination)
    except BaseException:
        with suppress(OSError):
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)
        raise

    return WavMetrics(
        sample_rate=rate,
        frames=frames,
        duration=frames / rate,
        rms=rms,
    )


def sanitize_environment() -> None:
    """Remove caller-controlled native-library/provider overrides."""

    for name in _UNTRUSTED_ENVIRONMENT:
        os.environ.pop(name, None)


def _default_engine_factory(model_path: str, voices_path: str) -> KokoroEngine:
    # Keep this import inside the sanitized, optional worker process.
    from kokoro_onnx import Kokoro

    return Kokoro(model_path, voices_path)


class KokoroWorker:
    """Own one Kokoro instance and serialize all access to it."""

    def __init__(
        self,
        model_path: str | os.PathLike[str],
        voices_path: str | os.PathLike[str],
        *,
        engine_factory: EngineFactory | None = None,
    ) -> None:
        model = _local_path(model_path)
        voices = _local_path(voices_path)
        sanitize_environment()
        factory = engine_factory or _default_engine_factory
        self._engine = factory(str(model), str(voices))
        self._lock = threading.Lock()

    def process(self, request: object) -> dict[str, object]:
        if not isinstance(request, dict):
            raise ProtocolError("invalid_request", "Request must be a JSON object.")

        operation = request.get("op", "synthesize")
        if operation != "synthesize":
            raise ProtocolError("unsupported_operation", "Unsupported worker operation.")

        text = request.get("text")
        output_path = request.get("output_path")
        if not isinstance(text, str) or not text.strip():
            raise ProtocolError("invalid_request", "Request text must be a non-empty string.")
        if not isinstance(output_path, str) or not output_path:
            raise ProtocolError("invalid_request", "Request output_path must be a local path.")

        voice = request.get("voice", VOICE)
        language = request.get("language", LANGUAGE)
        speed = request.get("speed", SPEED)
        if not isinstance(voice, str) or _VOICE_PATTERN.fullmatch(voice) is None:
            raise ProtocolError("invalid_request", "Request voice is invalid.")
        if not isinstance(language, str) or _LANGUAGE_PATTERN.fullmatch(language) is None:
            raise ProtocolError("invalid_request", "Request language is invalid.")
        if isinstance(speed, bool) or not isinstance(speed, (int, float)):
            raise ProtocolError("invalid_request", "Request speed is invalid.")
        normalized_speed = float(speed)
        if not 0.5 <= normalized_speed <= 2.0:
            raise ProtocolError("invalid_request", "Request speed is invalid.")
        try:
            destination = _local_path(output_path)
        except (TypeError, ValueError) as exc:
            raise ProtocolError(
                "invalid_request", "Request output_path must be a local path."
            ) from exc

        try:
            with self._lock:
                samples, sample_rate = self._engine.create(
                    text,
                    voice=voice,
                    lang=language,
                    speed=normalized_speed,
                    trim=True,
                    continuous=False,
                )
                metrics = write_wav(destination, samples, sample_rate)
        except Exception as exc:
            raise ProtocolError("synthesis_failed", "Local synthesis failed.") from exc

        return {
            "ok": True,
            "sample_rate": metrics.sample_rate,
            "frames": metrics.frames,
            "duration": metrics.duration,
            "rms": metrics.rms,
            "voice": voice,
        }


def _error_response(error: ProtocolError) -> dict[str, object]:
    return {
        "ok": False,
        "error": {"code": error.code, "message": error.message},
    }


def _write_response(stream: TextIO, response: dict[str, object]) -> None:
    stream.write(json.dumps(response, ensure_ascii=True, separators=(",", ":")))
    stream.write("\n")
    stream.flush()


def serve(
    model_path: str | os.PathLike[str],
    voices_path: str | os.PathLike[str],
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    engine_factory: EngineFactory | None = None,
) -> int:
    """Run the synchronous JSON-lines protocol until stdin reaches EOF."""

    input_stream = stdin or sys.stdin
    output_stream = stdout or sys.stdout
    try:
        worker = KokoroWorker(model_path, voices_path, engine_factory=engine_factory)
    except Exception:
        _write_response(
            output_stream,
            _error_response(
                ProtocolError("startup_failed", "Local speech engine initialization failed.")
            ),
        )
        return 1

    for line in input_stream:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
        except (json.JSONDecodeError, UnicodeError):
            response = _error_response(ProtocolError("invalid_json", "Request must be valid JSON."))
        else:
            try:
                response = worker.process(request)
            except ProtocolError as error:
                response = _error_response(error)
        _write_response(output_stream, response)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BLAIR local Kokoro helper")
    commands = parser.add_subparsers(dest="command", required=True)
    serve_parser = commands.add_parser("serve", help="run the JSON-lines synthesis worker")
    serve_parser.add_argument("--model", required=True, help="local Kokoro ONNX model path")
    serve_parser.add_argument("--voices", required=True, help="local Kokoro voices data path")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "serve":
        return serve(arguments.model, arguments.voices)
    return 2


if __name__ == "__main__":  # pragma: no cover - exercised by the parent process
    raise SystemExit(main())
