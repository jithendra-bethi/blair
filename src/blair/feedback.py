from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from .config import load_config
from .locking import file_lock
from .tts import select_backend

_MESSAGES = {"muted": "Blair muted.", "unmuted": "Blair unmuted."}


def announcement_audio(home: Path, announcement: str) -> Path | None:
    """Cache fixed control phrases in Blair's configured voice, outside replay history."""
    text = _MESSAGES[announcement]
    config = load_config(home)
    if config.backend == "none" or not config.play_audio:
        return None
    signature = json.dumps([text, config.backend, config.voice, config.language, config.speed])
    key = hashlib.sha256(signature.encode()).hexdigest()[:24]
    root = home / "runtime" / "control-audio"
    root.mkdir(parents=True, exist_ok=True)
    audio = root / f"{key}.wav"
    with file_lock(root / f"{key}.lock", timeout=120):
        if audio.exists():
            return audio
        temporary = root / f"{key}-{uuid4().hex}.wav"
        try:
            select_backend(config, home).synthesize(
                text, temporary, voice=config.voice, language=config.language, speed=config.speed
            )
            temporary.replace(audio)
        finally:
            temporary.unlink(missing_ok=True)
    return audio
