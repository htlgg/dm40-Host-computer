"""Small dialog to type a Bluetooth address by hand.

Useful when the meter is paired/known to Windows but its advertisement never
shows up in a scan – the address then simply gets connected to directly.
"""

from __future__ import annotations

import tkinter as tk

from core.i18n import t
from gui.theme import rgb_hex


def normalize_address(raw: str) -> str | None:
    """Accept 'AA:BB:CC:DD:EE:FF', 'aa-bb-cc-dd-ee-ff' or 12 bare digits."""
    cleaned = "".join(ch for ch in (raw or "") if ch.isalnum()).upper()
    if len(cleaned) != 12 or any(ch not in "0123456789ABCDEF" for ch in cleaned):
        return None
    return ":".join(cleaned[i:i + 2] for i in range(0, 12, 2))


class ManualConnectDialog(tk.Toplevel):
    def __init__(self, app, initial: str = "") -> None:
        super().__init__(app.root)
        self.app = app
        self.result: str | None = None
        self.title(t("setup.manual_title"))
        self.configure(bg=rgb_hex("background"))
        self.resizable(False, False)
        self.transient(app.root)
        self.attributes("-topmost", True)

        font = ("Microsoft YaHei UI", 10)
        body = tk.Frame(self, bg=rgb_hex("background"), padx=14, pady=12)
        body.pack(fill="both", expand=True)

        tk.Label(
            body, text=t("setup.manual_hint"), bg=rgb_hex("background"),
            fg=rgb_hex("text_secondary"), font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", pady=(0, 6))

        self._entry = tk.Entry(
            body, font=font, width=22, justify="center",
            bg="#181818", fg=rgb_hex("text_primary"),
            insertbackground=rgb_hex("text_primary"), relief="flat",
        )
        self._entry.pack(ipady=4, pady=(0, 8))
        self._entry.insert(0, initial)

        self._error = tk.Label(
            body, text="", bg=rgb_hex("background"),
            fg=rgb_hex("buttons_active"), font=("Microsoft YaHei UI", 9),
        )
        self._error.pack(anchor="w")

        buttons = tk.Frame(body, bg=rgb_hex("background"))
        buttons.pack(fill="x", pady=(8, 0))

        def button(text: str, command) -> None:
            tk.Button(
                buttons, text=text, command=command, font=font,
                bg="#292c31", fg=rgb_hex("text_primary"),
                activebackground=rgb_hex("buttons_active"),
                activeforeground="#ffffff", relief="flat", bd=0, padx=12, pady=3,
            ).pack(side="right", padx=(6, 0))

        button(t("setup.manual_cancel"), self._cancel)
        button(t("setup.manual_ok"), self._confirm)

        self.bind("<Return>", lambda _e: self._confirm())
        self.bind("<Escape>", lambda _e: self._cancel())
        self._entry.focus_set()
        self._entry.select_range(0, "end")

        self.update_idletasks()
        width, height = self.winfo_reqwidth(), self.winfo_reqheight()
        x = app.root.winfo_rootx() + (app.root.winfo_width() - width) // 2
        y = app.root.winfo_rooty() + (app.root.winfo_height() - height) // 3
        self.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def _confirm(self) -> None:
        address = normalize_address(self._entry.get())
        if address is None:
            self._error.configure(text=t("setup.manual_invalid"))
            return
        self.result = address
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()
