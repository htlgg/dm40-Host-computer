"""Tiny append-only log next to the exe – used to trace unexpected behaviour.

Only a handful of events are written (shortcut toggles, actions fired from the
background hook, sounds played). Nothing is sent anywhere; delete the file at
any time.
"""

from __future__ import annotations

import time

from core.config import PROJECT_ROOT

LOG_PATH = PROJECT_ROOT / "dm40-diagnostics.log"
MAX_BYTES = 200_000


def log(message: str) -> None:
    try:
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > MAX_BYTES:
            LOG_PATH.unlink()
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {message}\n")
    except Exception:
        pass
