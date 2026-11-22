"""Only one copy of the app may run.

Two copies would each install a keyboard hook: one key press would be handled
twice (the mode flips off and straight back on) and every confirmation sound
would play twice.
"""

from __future__ import annotations

import ctypes
import sys

_MUTEX_NAME = "DM40Wireless-SingleInstance-v1"
_ERROR_ALREADY_EXISTS = 183

_handle: int | None = None


def acquire() -> bool:
    """True when this is the first instance; keeps the mutex alive."""
    global _handle
    if sys.platform != "win32":
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CreateMutexW.argtypes = [
            ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p,
        ]
        _handle = kernel32.CreateMutexW(None, True, _MUTEX_NAME)
        return kernel32.GetLastError() != _ERROR_ALREADY_EXISTS
    except Exception:
        return True


def focus_existing(title: str) -> None:
    """Bring the window of the running copy to the front."""
    try:
        user32 = ctypes.windll.user32
        user32.FindWindowW.restype = ctypes.c_void_p
        handle = user32.FindWindowW(None, title)
        if handle:
            user32.ShowWindow(ctypes.c_void_p(handle), 9)      # SW_RESTORE
            user32.SetForegroundWindow(ctypes.c_void_p(handle))
    except Exception:
        pass
