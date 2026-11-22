"""Small popup to configure the confirmation sound (volume / effect / on-off)."""

from __future__ import annotations

import tkinter as tk

from core.i18n import t
from gui import layout as L
from gui.sound import (
    DEFAULT_STYLE,
    DEFAULT_VOLUME,
    STYLES,
    play,
    style_labels,
)


class SoundPopup(tk.Toplevel):
    """Modal-ish settings window for the toggle sound."""

    def __init__(self, app, anchor_widget: tk.Misc) -> None:
        super().__init__(app.root)
        self.app = app
        self.overrideredirect(True)
        self.configure(bg="#c8c8c8")
        self.attributes("-topmost", True)
        self._closing = False

        inner = tk.Frame(self, bg="#181818", padx=10, pady=8)
        inner.pack(padx=1, pady=1, fill="both", expand=True)

        self._font = ("Microsoft YaHei UI", 9)
        self._build_rows(inner)

        self.update_idletasks()
        width = self.winfo_reqwidth()
        height = self.winfo_reqheight()
        x = anchor_widget.winfo_rootx() + anchor_widget.winfo_width() - width
        y = anchor_widget.winfo_rooty() + anchor_widget.winfo_height() + 2
        self.geometry(f"{width}x{height}+{max(0, x)}+{y}")

        self.bind("<Escape>", lambda _e: self.close())
        self.bind("<FocusOut>", self._on_focus_out)
        self.after(120, self.focus_force)

    # -- layout ---------------------------------------------------------

    def _row(self, parent: tk.Misc) -> tk.Frame:
        row = tk.Frame(parent, bg="#181818")
        row.pack(fill="x", pady=2)
        return row

    def _label(self, parent: tk.Misc, text: str, width: int = 6) -> tk.Label:
        lbl = tk.Label(
            parent, text=text, bg="#181818", fg="#f7f7f7",
            font=self._font, anchor="w", width=width,
        )
        lbl.pack(side="left")
        return lbl

    def _button(self, parent: tk.Misc, text: str, command) -> tk.Button:
        btn = tk.Button(
            parent, text=text, command=command, font=self._font,
            bg="#292c31", fg="#f7f7f7", activebackground="#0082ce",
            activeforeground="#ffffff", relief="flat", bd=0, padx=6, pady=2,
        )
        btn.pack(side="left", padx=2)
        return btn

    def _build_rows(self, parent: tk.Misc) -> None:
        settings = self.app.settings

        state_row = self._row(parent)
        self._label(state_row, t("sound.enable"))
        self._state_btn = self._button(state_row, "", self._toggle_enabled)

        volume_row = self._row(parent)
        self._label(volume_row, t("sound.volume"))
        self._button(volume_row, "−", lambda: self._change_volume(-10))
        self._volume_lbl = tk.Label(
            volume_row, text="", width=4, bg="#181818", fg="#5fc3ff",
            font=self._font,
        )
        self._volume_lbl.pack(side="left")
        self._button(volume_row, "+", lambda: self._change_volume(10))

        style_row = self._row(parent)
        self._label(style_row, t("sound.style_on"))
        self._button(style_row, "◀", lambda: self._change_style("on", -1))
        self._style_on_lbl = tk.Label(
            style_row, text="", width=9, bg="#181818", fg="#5fc3ff",
            font=self._font,
        )
        self._style_on_lbl.pack(side="left", padx=4)
        self._button(style_row, "▶", lambda: self._change_style("on", 1))

        off_row = self._row(parent)
        self._label(off_row, t("sound.style_off"))
        self._button(off_row, "◀", lambda: self._change_style("off", -1))
        self._style_off_lbl = tk.Label(
            off_row, text="", width=9, bg="#181818", fg="#5fc3ff",
            font=self._font,
        )
        self._style_off_lbl.pack(side="left", padx=4)
        self._button(off_row, "▶", lambda: self._change_style("off", 1))

        test_row = self._row(parent)
        self._button(test_row, t("sound.preview_on"), lambda: self._preview("on"))
        self._button(test_row, t("sound.preview_off"), lambda: self._preview("off"))

        self._refresh()

    # -- behaviour ------------------------------------------------------

    def _refresh(self) -> None:
        settings = self.app.settings
        enabled = bool(settings.get("beep_enabled", True))
        self._state_btn.configure(
            text=t("settings.state_on") if enabled else t("settings.state_off"),
            fg="#5fc3ff" if enabled else "#a0a0a0",
        )
        volume = int(settings.get("beep_volume", DEFAULT_VOLUME))
        self._volume_lbl.configure(text=f"{volume}%")
        labels = style_labels()
        style_on = settings.get("beep_style_on", DEFAULT_STYLE)
        style_off = settings.get("beep_style_off", DEFAULT_STYLE)
        self._style_on_lbl.configure(text=labels.get(style_on, style_on))
        self._style_off_lbl.configure(text=labels.get(style_off, style_off))

    def _save(self) -> None:
        from gui.settings import save_settings

        save_settings(self.app.settings)
        self.app.hotkeys_screen.rebuild()

    def _toggle_enabled(self) -> None:
        self.app.settings["beep_enabled"] = not bool(
            self.app.settings.get("beep_enabled", True)
        )
        self._save()
        self._refresh()

    def _change_volume(self, delta: int) -> None:
        volume = int(self.app.settings.get("beep_volume", DEFAULT_VOLUME)) + delta
        self.app.settings["beep_volume"] = max(0, min(100, volume))
        self._save()
        self._refresh()

    def _change_style(self, kind: str, step: int) -> None:
        key = f"beep_style_{kind}"
        current = self.app.settings.get(key, DEFAULT_STYLE)
        index = STYLES.index(current) if current in STYLES else 0
        self.app.settings[key] = STYLES[(index + step) % len(STYLES)]
        self._save()
        self._refresh()

    def _preview(self, kind: str) -> None:
        play(self.app.settings, kind)

    def _on_focus_out(self, _event=None) -> None:
        if not self._closing:
            self.close()

    def close(self) -> None:
        self._closing = True
        try:
            self.destroy()
        except tk.TclError:
            pass
