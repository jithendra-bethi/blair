from __future__ import annotations

import os
from collections.abc import Callable


class ConsentPrompter:
    def __init__(self, callback: Callable[[str, str], bool] | None = None) -> None:
        self.callback = callback

    def ask(self, provider: str, session_id: str) -> bool:
        if self.callback:
            return self.callback(provider, session_id)
        # Wrapper choices arrive as launch-scoped event metadata. Process-wide
        # environment values cannot provide consent for an unrelated session.
        if os.name != "nt":
            return False
        return _windows_prompt(provider)


def _windows_prompt(provider: str) -> bool:
    import ctypes

    message = (
        f"Speak concise completion briefings for this {provider} session?\n\n"
        "BLAIR never uses your microphone. You can turn Briefing Protocol off at any time."
    )
    yes_no = 0x00000004
    icon_question = 0x00000020
    set_foreground = 0x00010000
    response = ctypes.windll.user32.MessageBoxW(
        None,
        message,
        "BLAIR — Briefing Protocol",
        yes_no | icon_question | set_foreground,
    )
    return response == 6
