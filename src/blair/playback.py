from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

from .config import _atomic_json_write
from .errors import BlairError
from .locking import file_lock
from .paths import blair_home, ensure_layout
from .state import StateStore


class PlaybackController:
    """Owns an interruptible WAV playback worker process."""

    def __init__(self, home: Path | None = None) -> None:
        self.home = home or blair_home()
        self.state_path = self.home / "playback.json"
        self.lock_path = self.home / "runtime" / "playback.lock"
        self.sessions = StateStore(self.home)

    def play(self, audio: Path, *, wait: bool = False) -> int | None:
        if not audio.exists():
            raise BlairError(f"Audio file does not exist: {audio}")
        ensure_layout(self.home)
        audio = audio.resolve()
        with file_lock(self.lock_path):
            if self.sessions.is_speech_muted():
                return None
            process, token = self._start_locked(audio=audio)
        if wait:
            try:
                return_code = process.wait(timeout=180)
            finally:
                self._clear_token(token)
            if return_code != 0:
                raise BlairError(f"Audio playback failed with exit code {return_code}")
        return process.pid

    def _start_locked(
        self, *, audio: Path | None = None, announcement: str | None = None
    ) -> tuple[subprocess.Popen, str]:
        """Publish one cancellable worker; caller holds the playback lock."""
        token = secrets.token_hex(32)
        state = {
            "pid": None,
            "ready": False,
            "token": token,
            "audio": str(audio) if audio else None,
            "announcement": announcement,
            "started_at": time.time(),
        }
        command = [
            sys.executable,
            "-m",
            "blair.playback",
            "--token",
            token,
            "--home",
            str(self.home.resolve()),
        ]
        command += ["--announcement", announcement] if announcement else ["--worker", str(audio)]
        _atomic_json_write(self.state_path, state)
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
            state["pid"] = process.pid
            _atomic_json_write(self.state_path, state)
        except BaseException:
            self.state_path.unlink(missing_ok=True)
            raise
        return process, token

    def stop(self) -> bool:
        """Cancel the current token; never terminate a PID loaded from disk."""
        with file_lock(self.lock_path):
            state = self._state()
            self.state_path.unlink(missing_ok=True)
            return bool(state and state.get("token"))

    def set_muted(self, muted: bool) -> bool:
        return self._change_mute(muted)

    def toggle_muted(self, *, announce: bool = False) -> bool:
        return self._change_mute(None, announce=announce)

    def _change_mute(self, muted: bool | None, *, announce: bool = False) -> bool:
        # The playback lock makes changing the global switch and cancelling the
        # current token atomic relative to every new playback attempt.
        with file_lock(self.lock_path):
            muted = (
                self.sessions.toggle_speech_muted()
                if muted is None
                else self.sessions.set_speech_muted(muted)
            )
            current = self._state()
            if muted or (current and current.get("announcement")):
                self.state_path.unlink(missing_ok=True)
            if announce:
                # Only these fixed control messages may speak while globally muted.
                # Reserve their token now so rapid toggles/Stop cancel stale feedback.
                self._start_locked(announcement="muted" if muted else "unmuted")
            return muted

    def _owns_token(self, token: str) -> bool:
        with file_lock(self.lock_path):
            state = self._state()
            return bool(state and state.get("token") == token)

    def _clear_token(self, token: str) -> None:
        with file_lock(self.lock_path):
            state = self._state()
            if state and state.get("token") == token:
                self.state_path.unlink(missing_ok=True)

    def _state(self) -> dict[str, object] | None:
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            return state if isinstance(state, dict) else None
        except (OSError, json.JSONDecodeError):
            return None


def _play_sync(audio: Path, cancelled: Callable[[], bool]) -> int:
    if cancelled():
        return 0
    if os.name == "nt":
        import winsound

        finished = threading.Event()

        def watch_cancellation() -> None:
            while not finished.wait(0.025):
                try:
                    should_stop = cancelled()
                except (OSError, TimeoutError):
                    os._exit(1)
                if should_stop:
                    # This dedicated sound worker exits itself. No saved PID is
                    # trusted, and a reused PID in another process is never touched.
                    os._exit(0)

        watcher = threading.Thread(target=watch_cancellation, daemon=True)
        watcher.start()
        try:
            winsound.PlaySound(str(audio), winsound.SND_FILENAME | winsound.SND_NODEFAULT)
            return 0
        finally:
            finished.set()
            watcher.join(timeout=1)
    for command in (["afplay", str(audio)], ["aplay", str(audio)]):
        try:
            process = subprocess.Popen(command)
        except FileNotFoundError:
            continue
        # This handle is our own unreaped child, not a PID from shared state.
        try:
            while process.poll() is None:
                if cancelled():
                    process.terminate()
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    return 0
                time.sleep(0.025)
            return process.returncode
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--announcement", choices=("muted", "unmuted"))
    parser.add_argument("--token")
    parser.add_argument("--home", type=Path)
    args = parser.parse_args(argv)
    if not (args.worker or args.announcement) or not args.token:
        return 2
    controller = PlaybackController(args.home)
    with file_lock(controller.lock_path):
        state = controller._state()
        if (
            not state
            or state.get("token") != args.token
            or state.get("announcement") != args.announcement
        ):
            return 0
        # Record the actual worker rather than the Windows venv launcher PID.
        state["pid"] = os.getpid()
        state["ready"] = True
        _atomic_json_write(controller.state_path, state)
    try:
        audio = args.worker
        if args.announcement:
            from .feedback import announcement_audio

            audio = announcement_audio(controller.home, args.announcement)
        if audio is None or not controller._owns_token(args.token):
            return 0
        return _play_sync(audio, lambda: not controller._owns_token(args.token))
    finally:
        controller._clear_token(args.token)


if __name__ == "__main__":
    raise SystemExit(main())
