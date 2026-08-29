from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_has_no_microphone_or_cloud_ai_client_imports() -> None:
    forbidden = {
        "anthropic",
        "openai",
        "pyaudio",
        "sounddevice",
        "speech_recognition",
        "webrtcvad",
    }
    imported: set[str] = set()
    for source_path in (ROOT / "src" / "blair").rglob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".", 1)[0])

    assert imported.isdisjoint(forbidden)
