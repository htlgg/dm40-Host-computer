"""System-wide shortcuts – work while another window is focused.

Tk only sees keys while its window is focused, so background mode installs a
low-level keyboard hook (``WH_KEYBOARD_LL``). The hook only *observes* keys –
it never swallows them – so typing in other programs keeps working exactly as
before. Matched keys are handed to the Tk thread through a queue.

Consequence worth knowing: while background mode is on, a key that is bound to
an action also fires while you type in another program (the character still
reaches that program). Bind keys you do not type, or switch the mode off.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import queue
import sys
import threading
import time

from gui.hotkeys import CHAR_TO_KEYSYM, normalize_step

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012

_REPEAT_GUARD_S = 0.20      # ignore auto-repeat of the same key
_POLL_MS = 40


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wt.DWORD),
        ("scanCode", wt.DWORD),
        ("flags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wt.ULONG)),
    ]


# Virtual keys with a stable name in our shortcut syntax
VK_NAMES = {
    0x08: "BackSpace", 0x09: "Tab", 0x0D: "Return", 0x1B: "Escape",
    0x20: "space",
    0x21: "Prior", 0x22: "Next", 0x23: "End", 0x24: "Home",
    0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down",
    0x2D: "Insert", 0x2E: "Delete",
}
MODIFIER_VKS = {0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C}

# Windows that belong to the desktop shell – they beep at digit keys.
_SHELL_CLASSES = {
    "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
    "SysListView32", "NotifyIconOverflowWindow", "TaskListThumbnailWnd",
}


class GlobalHotkeys:
    """Low-level keyboard hook that feeds background shortcuts to the app."""

    def __init__(self, app) -> None:
        self.app = app
        self._queue: queue.Queue[str] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._proc_ref = None
        self._hook = None
        self._thread_id = 0
        self._after_id = None
        self._last_seen: dict[str, float] = {}
        self._swallowed_vks: set[int] = set()
        self._available = sys.platform == "win32"
        self._own_hwnds: set[int] = set()
        self._hwnd_refresh = 0.0

    # -- lifecycle ------------------------------------------------------

    @property
    def available(self) -> bool:
        return self._available

    def start(self) -> None:
        if not self._available or self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="dm40-key-hook", daemon=True,
        )
        self._thread.start()
        self._ready.wait(3.0)
        self._refresh_own_hwnds()
        self._after_id = self.app.root.after(_POLL_MS, self._poll)
        self.app.root.bind("<Destroy>", self._on_destroy, add="+")

    @staticmethod
    def _user32():
        """user32 with 64-bit safe handle types (default int would truncate HWNDs)."""
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        user32.GetParent.argtypes = [ctypes.c_void_p]
        user32.GetParent.restype = ctypes.c_void_p
        return user32

    def _refresh_own_hwnds(self) -> None:
        """Cache the HWNDs that belong to this app (main thread only)."""
        try:
            user32 = self._user32()
            root = self.app.root
            handles = {int(root.winfo_id())}
            parent = user32.GetParent(ctypes.c_void_p(root.winfo_id()))
            if parent:
                handles.add(int(parent))
            self._own_hwnds = handles
        except Exception:
            pass

    def _on_destroy(self, event=None) -> None:
        """Stop the polling loop before the window goes away."""
        widget = getattr(event, "widget", None)
        if widget is not None and widget is not self.app.root:
            return
        if self._after_id is not None:
            try:
                self.app.root.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def stop(self) -> None:
        try:
            if self._thread_id:
                ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        except Exception:
            pass

    # -- hook thread ----------------------------------------------------

    def _run(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        try:
            hookproc = ctypes.WINFUNCTYPE(
                ctypes.c_ssize_t, ctypes.c_int, wt.WPARAM, wt.LPARAM,
            )
            user32.SetWindowsHookExW.argtypes = [
                ctypes.c_int, hookproc, wt.HINSTANCE, wt.DWORD,
            ]
            user32.SetWindowsHookExW.restype = ctypes.c_void_p
            user32.CallNextHookEx.argtypes = [
                ctypes.c_void_p, ctypes.c_int, wt.WPARAM, wt.LPARAM,
            ]
            user32.CallNextHookEx.restype = ctypes.c_ssize_t
            user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
            user32.GetMessageW.restype = wt.BOOL

            self._proc_ref = hookproc(self._on_key)
            self._thread_id = kernel32.GetCurrentThreadId()
            self._hook = user32.SetWindowsHookExW(
                WH_KEYBOARD_LL, self._proc_ref, None, 0,
            )
        except Exception:
            self._hook = None
        finally:
            self._ready.set()
        if not self._hook:
            self._available = False
            return

        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        try:
            user32.UnhookWindowsHookEx(ctypes.c_void_p(self._hook))
        except Exception:
            pass

    def _on_key(self, n_code, w_param, l_param):
        try:
            if n_code >= 0:
                if w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    # Skip keys that our own window is going to handle anyway –
                    # queueing them would replay them later (e.g. an F11 toggle
                    # firing again once another window takes the focus).
                    if not self._foreground_is_ours():
                        kb = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                        sequence = self._sequence_for(kb)
                        if sequence:
                            # Queue first – a swallowed key must still be acted on.
                            shell = self._foreground_is_shell()
                            swallow = self._should_swallow(sequence, shell=shell)
                            self._queue.put(sequence)
                            if swallow:
                                self._swallowed_vks.add(int(kb.vkCode))
                                return 1
                            self._log_bound(sequence, shell)
                elif w_param in (WM_KEYUP, WM_SYSKEYUP):
                    # A key-up without its key-down makes the shell beep, so the
                    # release of a swallowed key has to be dropped as well.
                    if self._swallowed_vks:
                        kb = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                        vk = int(kb.vkCode)
                        if vk in self._swallowed_vks:
                            self._swallowed_vks.discard(vk)
                            return 1
        except Exception:
            pass
        return ctypes.windll.user32.CallNextHookEx(None, n_code, w_param, l_param)

    def _foreground_is_ours(self) -> bool:
        """Cheap check used inside the hook callback."""
        try:
            foreground = self._user32().GetForegroundWindow()
        except Exception:
            return False
        return bool(foreground) and int(foreground) in self._own_hwnds

    def _should_swallow(self, sequence: str, *, shell: bool | None = None) -> bool:
        """Keep a bound key away from the desktop shell.

        The shell answers digit keys with a system sound, and those keys cannot
        type anything on the desktop anyway – so swallowing them there is safe
        and keeps the app silent. Real windows still get every key.
        """
        if not self.app.settings.get("global_swallow", True):
            return False
        if not (self._foreground_is_shell() if shell is None else shell):
            return False
        try:
            return self.app.hotkeys.sequence_is_bound(sequence)
        except Exception:
            return False

    def _log_bound(self, sequence: str, shell: bool) -> None:
        """Record why a bound key was NOT swallowed (diagnostics only)."""
        try:
            if not self.app.hotkeys.sequence_is_bound(sequence):
                return
            from gui.diagnostics import log

            log(
                f"hook key={sequence} shell={shell} "
                f"global={self.app.settings.get('global_hotkeys')} -> passed through"
            )
        except Exception:
            pass

    def _foreground_is_shell(self) -> bool:
        """True when the desktop / taskbar has the keyboard focus."""
        try:
            user32 = self._user32()
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return False
            buffer = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(ctypes.c_void_p(hwnd), buffer, 64)
            return buffer.value in _SHELL_CLASSES
        except Exception:
            return False

    # -- key translation -------------------------------------------------

    def _sequence_for(self, kb) -> str | None:
        vk = int(kb.vkCode)
        if vk in MODIFIER_VKS:
            return None
        user32 = ctypes.windll.user32
        control = bool(user32.GetAsyncKeyState(0x11) & 0x8000)
        alt = bool(user32.GetAsyncKeyState(0x12) & 0x8000)
        shift = bool(user32.GetAsyncKeyState(0x10) & 0x8000)

        if vk in VK_NAMES:
            key = VK_NAMES[vk]
            parts = []
            if control:
                parts.append("Control")
            if alt:
                parts.append("Alt")
            if shift:
                parts.append("Shift")
            parts.append(key)
            return "-".join(parts)
        if 0x70 <= vk <= 0x87:
            parts = []
            if control:
                parts.append("Control")
            if alt:
                parts.append("Alt")
            if shift:
                parts.append("Shift")
            parts.append(f"F{vk - 0x6F}")
            return "-".join(parts)

        char = self._char_for(vk, int(kb.scanCode))
        if not char:
            return None
        return self._compose(control, alt, shift, char)

    @staticmethod
    def _compose(control: bool, alt: bool, shift: bool, char: str) -> str:
        """Turn modifiers + character into the sequence used by the key map."""
        if len(char) == 1 and char.isalpha():
            key = char.lower()
            shift = False           # a letter's case is not a modifier here
        else:
            key = CHAR_TO_KEYSYM.get(char, char)
            if len(char) == 1 and not char.isalnum():
                # "+" or "*" already carry the shift – "Shift-plus" would never
                # match a shortcut stored as "+".
                shift = False
        parts = []
        if control:
            parts.append("Control")
        if alt:
            parts.append("Alt")
        if shift:
            parts.append("Shift")
        parts.append(key)
        return "-".join(parts)

    @staticmethod
    def _char_for(vk: int, scan: int) -> str:
        """The character this key produces on the current layout."""
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            state = (ctypes.c_ubyte * 256)()
            user32.GetKeyboardState(state)
            layout = user32.GetKeyboardLayout(kernel32.GetCurrentThreadId())
            buf = ctypes.create_unicode_buffer(8)
            count = user32.ToUnicodeEx(
                vk, scan, state, buf, len(buf), 0x4, layout,
            )
            if count == 1:
                return buf.value
        except Exception:
            pass
        return ""

    # -- Tk thread -------------------------------------------------------

    def _poll(self) -> None:
        self._after_id = None
        now = time.monotonic()
        if now - self._hwnd_refresh > 2.0:
            self._hwnd_refresh = now
            self._refresh_own_hwnds()
        focused = self._foreground_is_ours()
        try:
            while True:
                sequence = self._queue.get_nowait()
                if focused:
                    continue           # Tk already handled this key
                if now - self._last_seen.get(sequence, 0.0) < _REPEAT_GUARD_S:
                    continue           # auto-repeat
                self._last_seen[sequence] = now
                try:
                    self.app.hotkeys.dispatch_sequence(sequence)
                except Exception:
                    pass
        except queue.Empty:
            pass
        try:
            self._after_id = self.app.root.after(_POLL_MS, self._poll)
        except Exception:
            self._after_id = None

