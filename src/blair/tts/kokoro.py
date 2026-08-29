from __future__ import annotations

import atexit
import hashlib
import importlib.util
import json
import os
import queue
import subprocess
import sys
import threading
import urllib.request
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from ..config import _atomic_json_write
from ..errors import TtsError
from ..locking import file_lock
from ..models import SpeechArtifact

ProgressCallback = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class ModelAsset:
    filename: str
    url: str
    size: int
    sha256: str


MODEL_ASSETS = (
    ModelAsset(
        filename="kokoro-v1.0.onnx",
        url=(
            "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
            "model-files-v1.1/kokoro-v1.0.onnx"
        ),
        size=325_505_369,
        sha256="beb0d1848dee9a49da392cc3df26958d46cfa35d321edf434f52949153f0df3a",
    ),
    ModelAsset(
        filename="voices-v1.0.bin",
        url=(
            "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
            "model-files-v1.1/voices-v1.0.bin"
        ),
        size=28_214_398,
        sha256="bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
    ),
)

MODEL_RELEASE = "model-files-v1.1"
_WORKER_TIMEOUT_SECONDS = 180.0
_UNTRUSTED_ENVIRONMENT = ("ONNX_PROVIDER", "PHONEMIZER_ESPEAK_LIBRARY")
_WORKER_CACHE_LOCK = threading.Lock()
_WORKER_CACHE: dict[tuple[str, str], _KokoroWorkerClient] = {}


def model_directory(home: Path) -> Path:
    return home / "models" / "kokoro" / MODEL_RELEASE


def dependencies_available() -> bool:
    return (
        importlib.util.find_spec("kokoro_onnx") is not None
        and importlib.util.find_spec("numpy") is not None
    )


def models_ready(models_dir: Path, *, verify_hash: bool = True) -> bool:
    for asset in MODEL_ASSETS:
        path = models_dir / asset.filename
        if not path.exists() or path.stat().st_size != asset.size:
            return False
        if verify_hash and _sha256(path) != asset.sha256:
            return False
    return True


def ensure_models(models_dir: Path, progress: ProgressCallback | None = None) -> tuple[Path, ...]:
    reporter = progress or (lambda message: None)
    models_dir.mkdir(parents=True, exist_ok=True)
    with file_lock(models_dir / ".bootstrap.lock", timeout=900):
        for asset in MODEL_ASSETS:
            destination = models_dir / asset.filename
            if _asset_valid(destination, asset):
                reporter(f"Ready: {asset.filename}")
                continue
            destination.unlink(missing_ok=True)
            partial = destination.with_suffix(destination.suffix + ".partial")
            partial.unlink(missing_ok=True)
            reporter(f"Downloading {asset.filename} ({asset.size // 1_000_000} MB)...")
            request = urllib.request.Request(asset.url, headers={"User-Agent": "BLAIR/0.1"})
            try:
                with (
                    urllib.request.urlopen(request, timeout=60) as response,
                    partial.open("wb") as stream,
                ):
                    downloaded = 0
                    while chunk := response.read(1024 * 1024):
                        stream.write(chunk)
                        downloaded += len(chunk)
                        if downloaded % (25 * 1024 * 1024) < len(chunk):
                            reporter(f"  {downloaded * 100 // asset.size}%")
                    stream.flush()
                    os.fsync(stream.fileno())
            except Exception as exc:
                partial.unlink(missing_ok=True)
                raise TtsError(f"Could not download {asset.filename}: {exc}") from exc
            if not _asset_valid(partial, asset):
                partial.unlink(missing_ok=True)
                raise TtsError(f"Downloaded {asset.filename} failed size or SHA-256 verification")
            os.replace(partial, destination)
            reporter(f"Verified: {asset.filename}")
        _atomic_json_write(
            models_dir / "manifest.json",
            {
                "release": MODEL_RELEASE,
                "assets": [
                    {
                        "filename": asset.filename,
                        "url": asset.url,
                        "size": asset.size,
                        "sha256": asset.sha256,
                    }
                    for asset in MODEL_ASSETS
                ],
            },
        )
    return tuple(models_dir / asset.filename for asset in MODEL_ASSETS)


class _WorkerTransportError(TtsError):
    """A local helper transport failure that is safe to retry once."""


class _KokoroWorkerClient:
    """Serialized JSON-lines client for one persistent local Kokoro process."""

    def __init__(self, model_path: Path, voices_path: Path) -> None:
        self.model_path = model_path.resolve()
        self.voices_path = voices_path.resolve()
        self._lock = threading.Lock()
        self._responses: queue.Queue[dict[str, object] | None] = queue.Queue()
        self._process: subprocess.Popen[str] | None = None
        self._closed = False

    def synthesize(
        self,
        text: str,
        output_path: Path,
        *,
        voice: str,
        language: str,
        speed: float,
    ) -> dict[str, object]:
        with self._lock:
            if self._closed:
                raise _WorkerTransportError("The local Kokoro helper is unavailable")
            if self._process is None:
                self._start_locked()
            process = self._process
            if process is None or process.poll() is not None or process.stdin is None:
                self._terminate_locked()
                raise _WorkerTransportError("The local Kokoro helper stopped unexpectedly")

            request = {
                "op": "synthesize",
                "text": text,
                "output_path": str(output_path.resolve()),
                "voice": voice,
                "language": language,
                "speed": speed,
            }
            try:
                process.stdin.write(json.dumps(request, ensure_ascii=True, separators=(",", ":")))
                process.stdin.write("\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError, UnicodeError) as exc:
                self._terminate_locked()
                raise _WorkerTransportError(
                    "Could not send work to the local Kokoro helper"
                ) from exc

            try:
                response = self._responses.get(timeout=_WORKER_TIMEOUT_SECONDS)
            except queue.Empty as exc:
                self._terminate_locked()
                raise _WorkerTransportError("Local Kokoro synthesis timed out") from exc
            if response is None:
                self._terminate_locked()
                raise _WorkerTransportError("The local Kokoro helper stopped unexpectedly")
            if response.get("ok") is not True:
                if "error" not in response:
                    self._terminate_locked()
                    raise _WorkerTransportError("The local Kokoro helper returned invalid data")
                raise TtsError("Local Kokoro synthesis failed")
            return response

    def _start_locked(self) -> None:
        environment = os.environ.copy()
        for name in _UNTRUSTED_ENVIRONMENT:
            environment.pop(name, None)
        command = [
            sys.executable,
            "-m",
            "blair.kokoro_helper",
            "serve",
            "--model",
            str(self.model_path),
            "--voices",
            str(self.voices_path),
        ]
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="strict",
                bufsize=1,
                env=environment,
                creationflags=creation_flags,
            )
        except (OSError, ValueError) as exc:
            self._closed = True
            raise _WorkerTransportError("Could not start the local Kokoro helper") from exc
        self._process = process
        reader = threading.Thread(
            target=self._read_responses,
            args=(process,),
            name="blair-kokoro-reader",
            daemon=True,
        )
        reader.start()

    def _read_responses(self, process: subprocess.Popen[str]) -> None:
        stream = process.stdout
        if stream is None:
            self._responses.put(None)
            return
        try:
            for line in stream:
                try:
                    parsed = json.loads(line)
                except (json.JSONDecodeError, UnicodeError):
                    self._responses.put({"ok": False})
                else:
                    self._responses.put(parsed if isinstance(parsed, dict) else {"ok": False})
        finally:
            self._responses.put(None)

    def close(self) -> None:
        with self._lock:
            self._terminate_locked()

    def _terminate_locked(self) -> None:
        self._closed = True
        process, self._process = self._process, None
        if process is None:
            return
        if process.stdin is not None:
            with suppress(OSError):
                process.stdin.close()
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                with suppress(OSError):
                    process.kill()


def _worker_key(model_path: Path, voices_path: Path) -> tuple[str, str]:
    return (str(model_path.resolve()), str(voices_path.resolve()))


def _get_worker(model_path: Path, voices_path: Path) -> _KokoroWorkerClient:
    key = _worker_key(model_path, voices_path)
    with _WORKER_CACHE_LOCK:
        worker = _WORKER_CACHE.get(key)
        if worker is None:
            worker = _KokoroWorkerClient(model_path, voices_path)
            _WORKER_CACHE[key] = worker
        return worker


def _discard_worker(model_path: Path, voices_path: Path, worker: _KokoroWorkerClient) -> None:
    key = _worker_key(model_path, voices_path)
    with _WORKER_CACHE_LOCK:
        if _WORKER_CACHE.get(key) is worker:
            _WORKER_CACHE.pop(key, None)
    worker.close()


def _close_workers() -> None:
    with _WORKER_CACHE_LOCK:
        workers = tuple(_WORKER_CACHE.values())
        _WORKER_CACHE.clear()
    for worker in workers:
        worker.close()


atexit.register(_close_workers)


class KokoroBackend:
    """Kokoro ONNX speech using the local British female `bf_emma` voice."""

    name = "kokoro-onnx"

    def __init__(self, models_dir: Path) -> None:
        self.models_dir = models_dir
        self._verified = False

    def available(self) -> bool:
        self._verified = dependencies_available() and models_ready(self.models_dir)
        return self._verified

    def synthesize(
        self,
        text: str,
        output_path: Path,
        *,
        voice: str,
        language: str,
        speed: float,
    ) -> SpeechArtifact:
        if not dependencies_available():
            raise TtsError("Kokoro dependencies are missing; install BLAIR with the 'kokoro' extra")
        if not self._verified and not models_ready(self.models_dir):
            raise TtsError("Kokoro model files are missing; run 'blair setup'")
        self._verified = True
        if not text.strip():
            raise TtsError("Cannot synthesize an empty briefing")

        model_path = self.models_dir / MODEL_ASSETS[0].filename
        voices_path = self.models_dir / MODEL_ASSETS[1].filename
        output_path.parent.mkdir(parents=True, exist_ok=True)
        worker = _get_worker(model_path, voices_path)
        try:
            try:
                response = worker.synthesize(
                    text,
                    output_path,
                    voice=voice,
                    language=language,
                    speed=speed,
                )
            except _WorkerTransportError:
                _discard_worker(model_path, voices_path, worker)
                worker = _get_worker(model_path, voices_path)
                response = worker.synthesize(
                    text,
                    output_path,
                    voice=voice,
                    language=language,
                    speed=speed,
                )
        except TtsError:
            output_path.unlink(missing_ok=True)
            raise
        if not output_path.exists() or output_path.stat().st_size <= 44:
            raise TtsError("Kokoro did not produce a valid WAV file")
        sample_rate = response.get("sample_rate")
        duration = response.get("duration")
        if isinstance(sample_rate, bool) or not isinstance(sample_rate, int):
            output_path.unlink(missing_ok=True)
            raise TtsError("Kokoro returned invalid audio metadata")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            output_path.unlink(missing_ok=True)
            raise TtsError("Kokoro returned invalid audio metadata")
        return SpeechArtifact(
            path=output_path,
            backend=self.name,
            voice=voice,
            sample_rate=sample_rate,
            duration_seconds=float(duration),
        )


def _asset_valid(path: Path, asset: ModelAsset) -> bool:
    return path.exists() and path.stat().st_size == asset.size and _sha256(path) == asset.sha256


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
