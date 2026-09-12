from __future__ import annotations

import base64
import hashlib
import json
import os
import queue
import secrets
import signal
import subprocess
import sys
import threading
import time
from dataclasses import asdict
from datetime import UTC, datetime
from multiprocessing.connection import Client, Listener
from pathlib import Path
from typing import Any

from .adapters import MAX_PAYLOAD_BYTES, NormalizedEvent, parse_generic_event
from .config import _atomic_json_write, load_config
from .hotkeys import GlobalHotkeys, HotkeyActions
from .locking import file_lock
from .paths import blair_home, ensure_layout
from .pipeline import BriefingPipeline
from .playback import PlaybackController
from .runtime import self_command

_SHUTDOWN = b'{"control":"shutdown"}'
_SENTINEL = object()


def _runtime_dir(home: Path) -> Path:
    path = home / "runtime"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _family() -> str:
    return "AF_PIPE" if os.name == "nt" else "AF_UNIX"


def _address(home: Path) -> str:
    digest = hashlib.sha256(str(home.resolve()).encode("utf-8")).hexdigest()[:16]
    if os.name == "nt":
        return rf"\\.\pipe\BLAIR-{digest}"
    return str(_runtime_dir(home) / f"blair-{digest}.sock")


def _auth_key(home: Path) -> bytes:
    path = _runtime_dir(home) / "daemon-auth.key"
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        encoded = path.read_text(encoding="ascii").strip()
        return base64.urlsafe_b64decode(encoded)
    key = secrets.token_bytes(32)
    try:
        with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as stream:
            stream.write(base64.urlsafe_b64encode(key).decode("ascii"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return key


def enqueue_event(event: NormalizedEvent, home: Path | None = None) -> None:
    """Deliver an event without waiting for briefing synthesis or playback."""

    root = ensure_layout(home or blair_home())
    payload = json.dumps(asdict(event), separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise ValueError("Normalized event exceeds BLAIR's payload limit")
    try:
        _send(payload, root)
        return
    except (ConnectionError, FileNotFoundError, OSError, EOFError):
        start_daemon(root)
    deadline = time.monotonic() + 3.0
    last_error: BaseException | None = None
    while time.monotonic() < deadline:
        try:
            _send(payload, root)
            return
        except (ConnectionError, FileNotFoundError, OSError, EOFError) as exc:
            last_error = exc
            time.sleep(0.05)
    raise ConnectionError(f"BLAIR background service did not start: {last_error}")


def _send(payload: bytes, home: Path) -> None:
    connection = Client(_address(home), family=_family(), authkey=_auth_key(home))
    try:
        connection.send_bytes(payload)
    finally:
        connection.close()


def start_daemon(home: Path | None = None) -> int:
    root = ensure_layout(home or blair_home())
    current = daemon_pid(root)
    if current:
        return current
    command = self_command("_daemon", "serve")
    environment = os.environ.copy()
    environment.pop("BLAIR_CONSENT_RESPONSE", None)
    environment.pop("BLAIR_LAUNCH_ID", None)
    environment["BLAIR_HOME"] = str(root)
    creationflags = 0
    if os.name == "nt":
        # DETACHED_PROCESS makes Windows ignore CREATE_NO_WINDOW; the venv
        # launcher can then give the daemon a visible console.
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "CREATE_NO_WINDOW", 0
        )
    process = subprocess.Popen(
        command,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creationflags,
        cwd=str(root),
    )
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        running = daemon_pid(root)
        if running:
            return running
        if process.poll() is not None:
            break
        time.sleep(0.05)
    return process.pid


def stop_daemon(home: Path | None = None) -> bool:
    root = home or blair_home()
    if not daemon_pid(root):
        return False
    try:
        _send(_SHUTDOWN, root)
    except (ConnectionError, FileNotFoundError, OSError, EOFError):
        return False
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if not daemon_pid(root):
            return True
        time.sleep(0.05)
    return False


def daemon_pid(home: Path | None = None) -> int | None:
    root = home or blair_home()
    runtime = _runtime_dir(root)
    path = runtime / "daemon.json"
    # Windows denies unlink/replace while an ordinary reader has the file open.
    # Serialize status reads with publication and cleanup, including stale records.
    with file_lock(runtime / "daemon-state.lock"):
        try:
            pid = int(json.loads(path.read_text(encoding="utf-8"))["pid"])
        except FileNotFoundError:
            return None
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            path.unlink(missing_ok=True)
            return None
        if _pid_alive(pid):
            return pid
        path.unlink(missing_ok=True)
        return None


def _remove_daemon_record(home: Path, instance_id: str) -> None:
    runtime = _runtime_dir(home)
    path = runtime / "daemon.json"
    with file_lock(runtime / "daemon-state.lock"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        # A replacement service may have published after the listener closed.
        # Even a reused PID must not let the old service remove the new record.
        if isinstance(record, dict) and record.get("instance_id") == instance_id:
            path.unlink(missing_ok=True)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        still_active = 259
        handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            return bool(
                ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                and exit_code.value == still_active
            )
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class EventLedger:
    """Content-free event hashes used to suppress duplicate hook deliveries."""

    def __init__(self, home: Path, *, duplicate_window: float = 8.0) -> None:
        self.path = _runtime_dir(home) / "event-ledger.json"
        self.duplicate_window = duplicate_window

    def seen_or_add(self, event: NormalizedEvent, *, now: float | None = None) -> bool:
        timestamp = time.time() if now is None else now
        data = self._read()
        entries = {
            key: float(value)
            for key, value in data.get("entries", {}).items()
            if timestamp - float(value) < 86_400
        }
        event_key = "event:" + hashlib.sha256(event.event_id.encode("utf-8")).hexdigest()
        fingerprint = (
            "text:"
            + hashlib.sha256(
                "\0".join((event.provider, event.session_id, event.text)).encode("utf-8")
            ).hexdigest()
        )
        duplicate = event_key in entries or (
            fingerprint in entries and timestamp - entries[fingerprint] <= self.duplicate_window
        )
        entries[event_key] = timestamp
        entries[fingerprint] = timestamp
        _atomic_json_write(self.path, {"version": 1, "entries": entries})
        return duplicate

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "entries": {}}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": 1, "entries": {}}
        return value if isinstance(value, dict) else {"version": 1, "entries": {}}


class BlairDaemon:
    def __init__(self, home: Path | None = None) -> None:
        self.home = ensure_layout(home or blair_home())
        self.runtime = _runtime_dir(self.home)
        self.stop_event = threading.Event()
        self.events: queue.Queue[tuple[int, NormalizedEvent] | object] = queue.Queue()
        self.sequence_lock = threading.Lock()
        self.latest_sequence = 0
        self.ledger = EventLedger(self.home)
        self.pipeline = BriefingPipeline(home=self.home)
        config = self.pipeline.config
        self.hotkeys = (
            GlobalHotkeys(
                HotkeyActions(self.home),
                {
                    "toggle": config.hotkey_toggle,
                    "replay": config.hotkey_replay,
                    "stop": config.hotkey_stop,
                },
                self._log_action,
            )
            if config.hotkeys_enabled
            else None
        )

    def serve(self) -> int:
        address = _address(self.home)
        if os.name != "nt":
            Path(address).unlink(missing_ok=True)
        try:
            listener = Listener(address, family=_family(), authkey=_auth_key(self.home))
        except OSError:
            return 0 if daemon_pid(self.home) else 1

        instance_id = secrets.token_hex(16)
        with file_lock(self.runtime / "daemon-state.lock"):
            _atomic_json_write(
                self.runtime / "daemon.json",
                {
                    "pid": os.getpid(),
                    "instance_id": instance_id,
                    "started_at": datetime.now(UTC).isoformat(),
                    "address_hash": hashlib.sha256(address.encode("utf-8")).hexdigest(),
                },
            )
        worker = threading.Thread(target=self._work, name="blair-worker", daemon=True)
        worker.start()
        if self.hotkeys:
            self._log("hotkeys-registered" if self.hotkeys.start() else "hotkeys-unavailable")
        self._log("daemon-started")
        try:
            while not self.stop_event.is_set():
                connection = listener.accept()
                try:
                    payload = connection.recv_bytes(MAX_PAYLOAD_BYTES)
                except (EOFError, OSError):
                    continue
                finally:
                    connection.close()
                if payload == _SHUTDOWN:
                    self.stop_event.set()
                    self._signal_worker_stop()
                    break
                try:
                    event = parse_generic_event(payload.decode("utf-8"))
                except Exception as exc:
                    self._log("event-rejected", error=exc)
                    continue
                self._enqueue_latest(event)
        finally:
            listener.close()
            self.stop_event.set()
            self._signal_worker_stop()
            if self.hotkeys:
                self.hotkeys.stop()
            PlaybackController(self.home).stop()
            _remove_daemon_record(self.home, instance_id)
            if os.name != "nt":
                Path(address).unlink(missing_ok=True)
            self._log("daemon-stopped")
        return 0

    def _log_action(self, action: str) -> None:
        self._log(action)

    def _work(self) -> None:
        while not self.stop_event.is_set():
            queued = self.events.get()
            if queued is _SENTINEL:
                return
            assert isinstance(queued, tuple)
            sequence, event = queued
            result = event.to_agent_result()
            if event.metadata.get("failed"):
                result.text = f"The agent turn failed. {result.text}"
            elif event.metadata.get("background_pending"):
                result.text = (
                    f"The agent still has background work and is not finished. {result.text}"
                )
            try:
                # Use one validated settings snapshot for this entire briefing.
                config = load_config(self.home)
                if config.backend != self.pipeline.config.backend:
                    self.pipeline.backend = None
                self.pipeline.config = config
                outcome = self.pipeline.handle(result, play=False)
                reason = outcome.reason
                if outcome.artifact and self.pipeline.config.play_audio:
                    with self.sequence_lock:
                        session = self.pipeline.state.get(event.session_id)
                        if sequence == self.latest_sequence and session and session.enabled is True:
                            process = self.pipeline.playback.play(outcome.artifact.path)
                            reason = "spoken" if process is not None else "speech-muted"
                        elif session and session.enabled is not True:
                            reason = "disabled-after-synthesis"
                        else:
                            reason = "superseded"
            except Exception as exc:  # A failed briefing must not end the event worker.
                self._log("briefing-error", event, exc)
                continue
            self._log(f"briefing-{reason}", event)

    def _enqueue_latest(self, event: NormalizedEvent) -> None:
        with self.sequence_lock:
            try:
                # Reject ignored arrivals before changing audio or the pending
                # sequence. Keep all ledger access in this serialized admission path.
                if self.ledger.seen_or_add(event):
                    self._log("event-duplicate", event)
                    return
                state = self.pipeline.state
                if state.is_speech_muted():
                    self._log("briefing-speech-muted", event)
                    return
                session = state.get(event.session_id)
                launch_id = event.metadata.get("launch_id")
                consent_override = event.metadata.get("consent_override")
                if (
                    isinstance(launch_id, str)
                    and launch_id
                    and isinstance(consent_override, bool)
                    and (session is None or session.launch_id != launch_id)
                ):
                    state.ensure_session(event.session_id, event.provider, event.cwd)
                    session = state.begin_launch(event.session_id, launch_id, consent_override)
                if session and session.enabled is False:
                    self._log("briefing-session-disabled", event)
                    return
                # Unknown sessions still ask in the worker, never in the listener.
                if session and session.enabled is True:
                    self.pipeline.playback.stop()
            except Exception as exc:
                self._log("event-rejected", event, exc)
                return
            self.latest_sequence += 1
            sequence = self.latest_sequence
            while True:
                try:
                    self.events.get_nowait()
                except queue.Empty:
                    break
            self.events.put_nowait((sequence, event))

    def _signal_worker_stop(self) -> None:
        while True:
            try:
                self.events.get_nowait()
            except queue.Empty:
                break
        self.events.put_nowait(_SENTINEL)

    def _log(
        self,
        action: str,
        event: NormalizedEvent | None = None,
        error: BaseException | None = None,
    ) -> None:
        record: dict[str, Any] = {
            "time": datetime.now(UTC).isoformat(),
            "action": action,
        }
        if event:
            record["provider"] = event.provider
            record["session_hash"] = hashlib.sha256(event.session_id.encode("utf-8")).hexdigest()[
                :12
            ]
            record["event_hash"] = hashlib.sha256(event.event_id.encode("utf-8")).hexdigest()[:12]
        if error:
            record["error_type"] = type(error).__name__
            record["error"] = str(error)[:300]
        path = self.home / "logs" / "blair.log"
        try:
            with path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(record, sort_keys=True) + "\n")
        except OSError:
            pass


def serve(home: Path | None = None) -> int:
    return BlairDaemon(home).serve()


def main(argv: list[str] | None = None) -> int:
    arguments = argv if argv is not None else sys.argv[1:]
    if arguments == ["serve"]:
        return serve()
    return 2


if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    raise SystemExit(main())
