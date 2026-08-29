from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .config import _atomic_json_write
from .errors import BlairError
from .paths import blair_home, ensure_layout


class PlaybackController:
    """Owns an interruptible WAV playback worker process."""

    def __init__(self, home: Path | None = None) -> None:
        self.home = home or blair_home()
        self.state_path = self.home / "playback.json"

    def play(self, audio: Path, *, wait: bool = False) -> int:
        if not audio.exists():
            raise BlairError(f"Audio file does not exist: {audio}")
        self.stop()
        ensure_layout(self.home)
        token = next(tempfile._get_candidate_names())
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        process = subprocess.Popen(
            [sys.executable, "-m", "blair.playback", "--worker", str(audio), "--token", token],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        _atomic_json_write(
            self.state_path,
            {
                "pid": process.pid,
                "token": token,
                "audio": str(audio.resolve()),
                "started_at": time.time(),
            },
        )
        if wait:
            return_code = process.wait(timeout=180)
            self.state_path.unlink(missing_ok=True)
            if return_code != 0:
                raise BlairError(f"Audio playback failed with exit code {return_code}")
        return process.pid

    def stop(self) -> bool:
        state = self._state()
        if not state:
            return False
        pid = int(state.get("pid", 0))
        stopped = False
        if pid > 0:
            try:
                os.kill(pid, signal.SIGTERM)
                stopped = True
            except (OSError, ProcessLookupError):
                pass
        self.state_path.unlink(missing_ok=True)
        return stopped

    def _state(self) -> dict[str, object] | None:
        if not self.state_path.exists():
            return None
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.state_path.unlink(missing_ok=True)
            return None


def _play_sync(audio: Path) -> int:
    if os.name == "nt":
        import winsound

        winsound.PlaySound(str(audio), winsound.SND_FILENAME)
        return 0
    for command in (["afplay", str(audio)], ["aplay", str(audio)]):
        try:
            return subprocess.run(command, check=False).returncode
        except FileNotFoundError:
            continue
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--token")
    args = parser.parse_args(argv)
    if not args.worker or not args.token:
        return 2
    return _play_sync(args.worker)


if __name__ == "__main__":
    raise SystemExit(main())
