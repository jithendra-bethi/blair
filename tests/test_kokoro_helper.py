from __future__ import annotations

import io
import json
import wave
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
kokoro_helper = pytest.importorskip("blair.kokoro_helper")


class FakeEngine:
    def __init__(self, *, fail_on: str | None = None) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.fail_on = fail_on

    def create(self, text: str, **options: object) -> tuple[np.ndarray, int]:
        self.calls.append((text, options))
        if text == self.fail_on:
            raise RuntimeError(f"native failure included private text: {text}")
        return np.array([-0.5, 0.0, 0.5], dtype=np.float32), 24_000


def responses(stream: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_write_wav_encodes_mono_pcm16_and_reports_metrics(tmp_path: Path) -> None:
    output = tmp_path / "voice.wav"
    metrics = kokoro_helper.write_wav(
        output,
        np.array([-1.5, -0.5, 0.0, 0.5, 1.5]),
        24_000,
    )

    with wave.open(str(output), "rb") as stream:
        assert stream.getnchannels() == 1
        assert stream.getsampwidth() == 2
        assert stream.getframerate() == 24_000
        assert stream.getnframes() == 5
        pcm = np.frombuffer(stream.readframes(5), dtype="<i2")

    np.testing.assert_array_equal(pcm, [-32_768, -16_384, 0, 16_384, 32_767])
    assert metrics.sample_rate == 24_000
    assert metrics.frames == 5
    assert metrics.duration == pytest.approx(5 / 24_000)
    assert metrics.rms == pytest.approx(np.sqrt(0.5))


@pytest.mark.parametrize(
    "samples,sample_rate",
    [
        ([], 24_000),
        ([[0.0], [0.1]], 24_000),
        ([0.0, np.nan], 24_000),
        ([0.0, np.inf], 24_000),
        ([0.0], 0),
    ],
)
def test_write_wav_rejects_invalid_audio_without_output(
    tmp_path: Path, samples: object, sample_rate: int
) -> None:
    output = tmp_path / "invalid.wav"

    with pytest.raises(ValueError):
        kokoro_helper.write_wav(output, samples, sample_rate)  # type: ignore[arg-type]

    assert not output.exists()


def test_serve_initializes_once_sanitizes_environment_and_serializes_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ONNX_PROVIDER", "untrusted-provider")
    monkeypatch.setenv("PHONEMIZER_ESPEAK_LIBRARY", "untrusted-library")
    engine = FakeEngine()
    factory_calls: list[tuple[str, str]] = []

    def factory(model: str, voices: str) -> FakeEngine:
        assert "ONNX_PROVIDER" not in kokoro_helper.os.environ
        assert "PHONEMIZER_ESPEAK_LIBRARY" not in kokoro_helper.os.environ
        factory_calls.append((model, voices))
        return engine

    first = tmp_path / "one.wav"
    second = tmp_path / "two.wav"
    requests = io.StringIO(
        "\n".join(
            [
                json.dumps({"text": "First briefing", "output_path": str(first)}),
                json.dumps(
                    {
                        "op": "synthesize",
                        "text": "Second briefing",
                        "output_path": str(second),
                        "voice": "bf_alice",
                        "language": "en-gb",
                        "speed": 1.2,
                    }
                ),
            ]
        )
    )
    output = io.StringIO()

    result = kokoro_helper.serve(
        tmp_path / "model.onnx",
        tmp_path / "voices.bin",
        stdin=requests,
        stdout=output,
        engine_factory=factory,
    )

    assert result == 0
    assert len(factory_calls) == 1
    assert [call[0] for call in engine.calls] == ["First briefing", "Second briefing"]
    assert engine.calls[0][1] == {
        "voice": "bf_emma",
        "lang": "en-gb",
        "speed": 1.03,
        "trim": True,
        "continuous": False,
    }
    assert engine.calls[1][1] == {
        "voice": "bf_alice",
        "lang": "en-gb",
        "speed": 1.2,
        "trim": True,
        "continuous": False,
    }
    assert first.exists() and second.exists()
    assert responses(output) == [
        {
            "ok": True,
            "sample_rate": 24_000,
            "frames": 3,
            "duration": 3 / 24_000,
            "rms": pytest.approx(np.sqrt(1 / 6)),
            "voice": "bf_emma",
        },
        {
            "ok": True,
            "sample_rate": 24_000,
            "frames": 3,
            "duration": 3 / 24_000,
            "rms": pytest.approx(np.sqrt(1 / 6)),
            "voice": "bf_alice",
        },
    ]


def test_protocol_errors_do_not_echo_input_text_and_worker_continues(tmp_path: Path) -> None:
    malformed_secret = "MALFORMED_PRIVATE_PHRASE"
    missing_path_secret = "MISSING_PATH_PRIVATE_PHRASE"
    failing_secret = "SYNTHESIS_PRIVATE_PHRASE"
    final_output = tmp_path / "valid.wav"
    input_stream = io.StringIO(
        "\n".join(
            [
                "{not-json-" + malformed_secret,
                json.dumps({"text": missing_path_secret}),
                json.dumps({"text": failing_secret, "output_path": str(tmp_path / "failed.wav")}),
                json.dumps({"text": "safe", "output_path": str(final_output)}),
            ]
        )
    )
    output = io.StringIO()

    result = kokoro_helper.serve(
        tmp_path / "model.onnx",
        tmp_path / "voices.bin",
        stdin=input_stream,
        stdout=output,
        engine_factory=lambda _model, _voices: FakeEngine(fail_on=failing_secret),
    )

    encoded = output.getvalue()
    assert result == 0
    assert malformed_secret not in encoded
    assert missing_path_secret not in encoded
    assert failing_secret not in encoded
    parsed = responses(output)
    assert [item["ok"] for item in parsed] == [False, False, False, True]
    assert [item["error"]["code"] for item in parsed[:3]] == [  # type: ignore[index]
        "invalid_json",
        "invalid_request",
        "synthesis_failed",
    ]
    assert final_output.exists()


def test_startup_error_is_generic_and_does_not_read_requests(tmp_path: Path) -> None:
    secret = "STARTUP_PRIVATE_PHRASE"
    output = io.StringIO()

    def failing_factory(_model: str, _voices: str) -> FakeEngine:
        raise RuntimeError(secret)

    result = kokoro_helper.serve(
        tmp_path / "model.onnx",
        tmp_path / "voices.bin",
        stdin=io.StringIO(json.dumps({"text": secret, "output_path": "unused.wav"})),
        stdout=output,
        engine_factory=failing_factory,
    )

    assert result == 1
    assert secret not in output.getvalue()
    assert responses(output) == [
        {
            "ok": False,
            "error": {
                "code": "startup_failed",
                "message": "Local speech engine initialization failed.",
            },
        }
    ]


@pytest.mark.parametrize(
    "payload,code",
    [
        ([], "invalid_request"),
        ({"op": "download", "text": "private"}, "unsupported_operation"),
        ({"text": "private", "output_path": "https://example.invalid/out.wav"}, "invalid_request"),
        ({"text": "private", "output_path": r"\\server\share\out.wav"}, "invalid_request"),
        ({"text": "private", "output_path": "out.wav", "voice": "../bad"}, "invalid_request"),
        ({"text": "private", "output_path": "out.wav", "speed": True}, "invalid_request"),
        ({"text": "private", "output_path": "out.wav", "speed": 3.0}, "invalid_request"),
    ],
)
def test_protocol_rejects_non_objects_operations_and_network_paths(
    tmp_path: Path, payload: object, code: str
) -> None:
    output = io.StringIO()

    result = kokoro_helper.serve(
        tmp_path / "model.onnx",
        tmp_path / "voices.bin",
        stdin=io.StringIO(json.dumps(payload)),
        stdout=output,
        engine_factory=lambda _model, _voices: FakeEngine(),
    )

    assert result == 0
    response = responses(output)[0]
    assert response["ok"] is False
    assert response["error"]["code"] == code  # type: ignore[index]
    assert "private" not in output.getvalue()
