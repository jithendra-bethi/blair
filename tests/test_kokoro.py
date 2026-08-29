from __future__ import annotations

import hashlib
import io
import threading
from pathlib import Path

import pytest

from blair.errors import TtsError
from blair.tts import kokoro


class Response(io.BytesIO):
    def __enter__(self) -> Response:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def asset(payload: bytes) -> kokoro.ModelAsset:
    return kokoro.ModelAsset(
        filename="tiny.onnx",
        url="https://example.invalid/tiny.onnx",
        size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def test_bootstrap_verifies_and_reuses_offline_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"verified model bytes"
    calls = 0

    def open_asset(*args: object, **kwargs: object) -> Response:
        nonlocal calls
        calls += 1
        return Response(payload)

    monkeypatch.setattr(kokoro, "MODEL_ASSETS", (asset(payload),))
    monkeypatch.setattr(kokoro.urllib.request, "urlopen", open_asset)
    destination = tmp_path / "Unicode voice Ω"

    paths = kokoro.ensure_models(destination)
    assert paths[0].read_bytes() == payload
    assert (destination / "manifest.json").exists()
    assert kokoro.models_ready(destination) is True

    monkeypatch.setattr(
        kokoro.urllib.request,
        "urlopen",
        lambda *args, **kwargs: pytest.fail("valid cache must remain offline"),
    )
    kokoro.ensure_models(destination)
    assert calls == 1


def test_corrupt_download_is_deleted_before_runtime_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = b"correct bytes"
    monkeypatch.setattr(kokoro, "MODEL_ASSETS", (asset(expected),))
    monkeypatch.setattr(
        kokoro.urllib.request,
        "urlopen",
        lambda *args, **kwargs: Response(b"wrong bytes!"),
    )

    with pytest.raises(TtsError, match="failed size or SHA-256"):
        kokoro.ensure_models(tmp_path)

    assert not (tmp_path / "tiny.onnx").exists()
    assert not (tmp_path / "tiny.onnx.partial").exists()


def test_concurrent_bootstrap_downloads_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"single shared download"
    calls = 0
    call_lock = threading.Lock()

    def open_asset(*args: object, **kwargs: object) -> Response:
        nonlocal calls
        with call_lock:
            calls += 1
        return Response(payload)

    monkeypatch.setattr(kokoro, "MODEL_ASSETS", (asset(payload),))
    monkeypatch.setattr(kokoro.urllib.request, "urlopen", open_asset)
    errors: list[BaseException] = []

    def bootstrap() -> None:
        try:
            kokoro.ensure_models(tmp_path)
        except BaseException as exc:
            errors.append(exc)

    workers = [threading.Thread(target=bootstrap) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=5)

    assert errors == []
    assert calls == 1


class FakeWorker:
    def __init__(self, *, transport_failure: bool = False) -> None:
        self.transport_failure = transport_failure
        self.calls: list[dict[str, object]] = []

    def synthesize(self, text: str, output_path: Path, **options: object) -> dict[str, object]:
        self.calls.append({"text": text, "output_path": output_path, **options})
        if self.transport_failure:
            raise kokoro._WorkerTransportError("safe test transport failure")
        output_path.write_bytes(b"RIFF" + (b"\x00" * 44))
        return {"ok": True, "sample_rate": 24_000, "duration": 1.25, "voice": "bf_emma"}


def test_backend_uses_local_worker_contract_and_returns_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = FakeWorker()
    monkeypatch.setattr(kokoro, "dependencies_available", lambda: True)
    monkeypatch.setattr(kokoro, "models_ready", lambda _path: True)
    monkeypatch.setattr(kokoro, "_get_worker", lambda _model, _voices: worker)
    backend = kokoro.KokoroBackend(tmp_path)
    output = tmp_path / "briefing.wav"

    assert backend.available() is True
    artifact = backend.synthesize(
        "A concise local briefing.",
        output,
        voice="bf_emma",
        language="en-gb",
        speed=1.03,
    )

    assert artifact.path == output
    assert artifact.sample_rate == 24_000
    assert artifact.duration_seconds == 1.25
    assert worker.calls == [
        {
            "text": "A concise local briefing.",
            "output_path": output,
            "voice": "bf_emma",
            "language": "en-gb",
            "speed": 1.03,
        }
    ]


def test_backend_replaces_worker_and_retries_once_after_transport_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    failed = FakeWorker(transport_failure=True)
    replacement = FakeWorker()
    workers = iter((failed, replacement))
    discarded: list[object] = []
    monkeypatch.setattr(kokoro, "dependencies_available", lambda: True)
    monkeypatch.setattr(kokoro, "models_ready", lambda _path: True)
    monkeypatch.setattr(kokoro, "_get_worker", lambda _model, _voices: next(workers))
    monkeypatch.setattr(
        kokoro,
        "_discard_worker",
        lambda _model, _voices, worker: discarded.append(worker),
    )
    output = tmp_path / "retried.wav"

    artifact = kokoro.KokoroBackend(tmp_path).synthesize(
        "Retry this briefing once.",
        output,
        voice="bf_emma",
        language="en-gb",
        speed=1.03,
    )

    assert artifact.path == output
    assert discarded == [failed]
    assert len(failed.calls) == 1
    assert len(replacement.calls) == 1
