from __future__ import annotations

import sys
from pathlib import Path


def self_command(*arguments: str) -> list[str]:
    """Return a stable command that can launch this BLAIR installation."""

    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).resolve()), *arguments]
    return [str(Path(sys.executable).resolve()), "-m", "blair", *arguments]
