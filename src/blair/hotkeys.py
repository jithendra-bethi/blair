from __future__ import annotations

import os
import threading
from collections.abc import Callable
from pathlib import Path

from .playback import PlaybackController
from .state import StateStore

ActionCallback = Callable[[str], None]

_MODIFIERS = {
    "alt": 0x0001,
    "ctrl": 0x0002,
    "control": 0x0002,
    "shift": 0x0004,
    "win": 0x0008,
    "windows": 0x0008,
}
_MOD_NOREPEAT = 0x4000


def parse_hotkey(value: str) -> tuple[int, int]:
    parts = [part.strip().casefold() for part in value.split("+") if part.strip()]
    if len(parts) < 2:
        raise ValueError("hotkey must include a modifier and a key")
    modifiers = _MOD_NOREPEAT
    for modifier in parts[:-1]:
        if modifier not in _MODIFIERS:
            raise ValueError(f"unsupported hotkey modifier: {modifier}")
        modifiers |= _MODIFIERS[modifier]
    key = parts[-1]
    if len(key) == 1 and key.isalnum():
        virtual_key = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        virtual_key = 0x70 + int(key[1:]) - 1
    else:
        raise ValueError(f"unsupported hotkey key: {key}")
    return modifiers, virtual_key


class HotkeyActions:
    def __init__(
        self,
        home: Path,
        *,
        state: StateStore | None = None,
        playback: PlaybackController | None = None,
    ) -> None:
        self.home = home
        self.state = state or StateStore(home)
        self.playback = playback or PlaybackController(home)

    def toggle(self) -> str:
        session = self.state.get()
        if not session:
            return "hotkey-no-session"
        enabled = session.enabled is not True
        self.state.set_enabled(enabled, session.session_id)
        if not enabled:
            self.playback.stop()
        return "hotkey-enabled" if enabled else "hotkey-disabled"

    def replay(self) -> str:
        session = self.state.get()
        if not session or not session.last_audio:
            return "hotkey-no-briefing"
        path = Path(session.last_audio)
        if not path.exists():
            return "hotkey-no-briefing"
        self.playback.play(path)
        return "hotkey-replayed"

    def stop(self) -> str:
        return "hotkey-stopped" if self.playback.stop() else "hotkey-no-speech"


class GlobalHotkeys:
    """Windows RegisterHotKey host; it listens for key events, never audio."""

    def __init__(
        self,
        actions: HotkeyActions,
        bindings: dict[str, str],
        callback: ActionCallback | None = None,
    ) -> None:
        self.actions = actions
        self.bindings = bindings
        self.callback = callback or (lambda action: None)
        self.thread: threading.Thread | None = None
        self.thread_id: int | None = None
        self.registered_count = 0
        self.ready = threading.Event()

    def start(self) -> bool:
        if os.name != "nt" or self.thread:
            return False
        self.thread = threading.Thread(target=self._run, name="blair-hotkeys", daemon=True)
        self.thread.start()
        self.ready.wait(timeout=2)
        return self.registered_count > 0

    def stop(self) -> None:
        if os.name != "nt" or not self.thread:
            return
        if self.thread_id:
            import ctypes

            ctypes.windll.user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)
        self.thread.join(timeout=2)
        self.thread = None
        self.thread_id = None

    def _run(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self.thread_id = int(kernel32.GetCurrentThreadId())
        actions = {
            1: self.actions.toggle,
            2: self.actions.replay,
            3: self.actions.stop,
        }
        names = {1: "toggle", 2: "replay", 3: "stop"}
        registered: list[int] = []
        try:
            for identifier, name in names.items():
                try:
                    modifiers, virtual_key = parse_hotkey(self.bindings[name])
                except ValueError:
                    self.callback(f"hotkey-{name}-invalid")
                    continue
                if user32.RegisterHotKey(None, identifier, modifiers, virtual_key):
                    registered.append(identifier)
                else:
                    self.callback(f"hotkey-{name}-unavailable")
            self.registered_count = len(registered)
            self.ready.set()
            message = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message != 0x0312:
                    continue
                action = actions.get(int(message.wParam))
                if not action:
                    continue
                try:
                    self.callback(action())
                except Exception:
                    self.callback("hotkey-action-error")
        finally:
            for identifier in registered:
                user32.UnregisterHotKey(None, identifier)
            self.registered_count = 0
            self.ready.set()
