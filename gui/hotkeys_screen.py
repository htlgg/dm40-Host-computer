"""HOTKEYS screen – remap the keyboard shortcuts on the device-like UI.

Click a row, press the new key (Delete/BackSpace clears it, Esc cancels).
The whole table is stored in ``settings.json`` → ``hotkey_map``.
"""

from __future__ import annotations

import tkinter as tk

from core.config import SCREEN_HEIGHT, SCREEN_WIDTH
from core.i18n import t
from gui import hotkey_layout as HL
from gui import layout as L
from gui import sound
from gui.assets import bind_clickable, raise_click_hotspots
from gui.fonts import gui_font
from gui.hotkeys import (
    ACTION_ORDER,
    action_label,
    format_key_name,
    is_chord_capable,
    sequence_from_event,
)
from gui.settings import save_settings
from gui.sprites import SpriteCache
from gui.theme import rgb_hex

_CLEAR_KEYSYMS = ("Delete", "BackSpace")
_COMMIT_KEYSYMS = ("Return", "KP_Enter")


class HotkeysScreen(tk.Frame):
    def __init__(self, master, app, scale: float) -> None:
        super().__init__(master, bg=rgb_hex("background"))
        self.app = app
        self.scale = scale
        self.sprites = SpriteCache()

        w, h = int(SCREEN_WIDTH * scale), int(SCREEN_HEIGHT * scale)
        self.configure(width=w, height=h)
        self.pack_propagate(False)

        self.canvas = tk.Canvas(
            self, width=w, height=h, highlightthickness=0, bg=rgb_hex("background"),
        )
        self.canvas.pack()

        self._title_id: int | None = None
        self._back_sprite_id: int | None = None
        self._first_row = 0
        self._capture_action: str | None = None
        self._note = ""
        self._note_after: str | None = None
        self._show_disabled = False   # reveal the actions switched off
        self._capture_steps: list[str] = []   # keys typed so far while arming
        self._capture_after: str | None = None

        self._draw_top_bar()
        self._bind_back()
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-4>", lambda _event: self._scroll(-1))
        self.canvas.bind("<Button-5>", lambda _event: self._scroll(1))

    # ------------------------------------------------------------------
    # Chrome
    # ------------------------------------------------------------------

    def _s(self, value: float) -> int:
        return int(value * self.scale)

    def raise_click_layer(self) -> None:
        raise_click_hotspots(self.canvas)

    def _draw_top_bar(self) -> None:
        self.canvas.create_rectangle(
            0, 0, self._s(L.SCREEN_W), self._s(L.TOP_BAR_H),
            fill=rgb_hex("top_bar_background"), outline="", tags="hk_chrome",
        )
        font = gui_font(self.app.settings, self._s(HL.LABEL_FONT + 2), "normal")
        self._title_id = self.canvas.create_text(
            self._s(L.SCREEN_W // 2), self._s(18), text=t("hotkeys.title"),
            fill=rgb_hex("text_primary"), anchor="center", font=font, tags="hk_chrome",
        )
        self._place_back_icon()

    def _place_back_icon(self) -> None:
        if self._back_sprite_id is not None:
            self.canvas.delete(self._back_sprite_id)
            self._back_sprite_id = None
        max_h = self._s(L.TOP_BAR_H - 12)
        photo = self.sprites.range_menu_sprite("back.png", self.scale, max_h=max_h)
        if photo:
            self._back_sprite_id = self.canvas.create_image(
                self._s(8), self._s(8), anchor="nw", image=photo, tags="hk_chrome",
            )

    def _bind_back(self) -> None:
        from gui.range_layout import range_back_hit

        bx, by, bw, bh = range_back_hit()
        bind_clickable(
            self.canvas, self._s(bx), self._s(by), self._s(bw), self._s(bh),
            self._go_back, tag="hk_hit_goback",
        )

    def _go_back(self) -> None:
        self.cancel_capture()
        self.app.show_settings_screen()

    # ------------------------------------------------------------------
    # Content
    # ------------------------------------------------------------------

    def rebuild(self) -> None:
        self.cancel_capture()
        if self._title_id is not None:
            self.canvas.itemconfig(self._title_id, text=t("hotkeys.title"))
        for tag in ("hk_toggle", "hk_global", "hk_sound", "hk_hint", "hk_reset",
                    "hk_rows", "hk_scroll"):
            self.canvas.delete(tag)
        self.canvas.delete("hk_hit_toggle")
        self.canvas.delete("hk_hit_global")
        self.canvas.delete("hk_hit_sound")
        self.canvas.delete("hk_hit_reset")
        self.canvas.delete("hk_hint_more_hit")
        for action in ACTION_ORDER:
            # NOTE: row hotspots must not share a tag with the back button
            # (action ids include "back" → "hk_hit_back" would collide).
            self.canvas.delete(f"hk_action_hit_{action}")
            self.canvas.delete(f"hk_switch_hit_{action}")
        self._draw_toggle()
        self._draw_global_row()
        self._draw_hint()
        self._draw_rows()
        self._draw_sound_row()
        self._draw_reset()
        self.raise_click_layer()

    def visible_actions(self) -> list[str]:
        """Actions shown in the list (switched-off ones only when revealed)."""
        actions = self.app.hotkeys.enabled_actions()
        if self._show_disabled:
            disabled = self.app.hotkeys.disabled
            return [a for a in ACTION_ORDER if a not in disabled] + [
                a for a in ACTION_ORDER if a in disabled
            ]
        return actions

    def _row_metrics(self) -> tuple[int, int]:
        """(step, visible rows) for the scrollable list."""
        step = HL.ROW_H + HL.ROW_GAP
        visible = max(1, (HL.VIEW_BOTTOM - HL.VIEW_TOP) // step)
        return step, visible

    def _max_first_row(self) -> int:
        _step, visible = self._row_metrics()
        return max(0, len(self.visible_actions()) - visible)

    def _draw_toggle(self) -> None:
        x, y = self._s(HL.ROW_X), self._s(HL.TOGGLE_Y)
        w, h = self._s(HL.ROW_W), self._s(HL.ROW_H)
        self.canvas.create_rectangle(
            x, y, x + w, y + h, fill=rgb_hex("range_buttons"), outline="",
            tags=("hk_toggle", "hk_toggle_bg"),
        )
        label_font = gui_font(self.app.settings, self._s(HL.LABEL_FONT), "normal")
        state_font = gui_font(self.app.settings, self._s(HL.STATE_FONT), "normal")
        cy = y + h // 2
        pad = self._s(HL.ROW_MARGIN)
        self.canvas.create_text(
            x + pad, cy, text=t("hotkeys.enable"), fill=rgb_hex("text_primary"),
            anchor="w", font=label_font, tags=("hk_toggle",),
        )

        enabled = bool(self.app.settings.get("hotkeys", True))
        switch = self.sprites.settings_sprite(
            "switch_on.png" if enabled else "switch_off.png",
            self.scale, max_h=self._s(HL.SWITCH_MAX_H),
        )
        if switch:
            switch_x = x + w - pad - switch.width()
            self.canvas.create_image(
                switch_x, cy, anchor="w", image=switch, tags=("hk_toggle", "hk_toggle_sw"),
            )
            state_x = switch_x - self._s(HL.SWITCH_GAP)
        else:
            state_x = x + w - pad
        self.canvas.create_text(
            state_x, cy,
            text=t("settings.state_on") if enabled else t("settings.state_off"),
            fill=rgb_hex("buttons_active") if enabled else rgb_hex("text_secondary"),
            anchor="e", font=state_font, tags=("hk_toggle",),
        )
        bind_clickable(
            self.canvas, x, y, w, h, self._toggle_enabled, tag="hk_hit_toggle",
        )

    def _draw_global_row(self) -> None:
        """Switch: do the shortcuts also work while another window is focused?"""
        x, y = self._s(HL.ROW_X), self._s(HL.GLOBAL_Y)
        w, h = self._s(HL.ROW_W), self._s(HL.ROW_H)
        self.canvas.create_rectangle(
            x, y, x + w, y + h, fill=rgb_hex("range_buttons"), outline="",
            tags=("hk_global", "hk_global_bg"),
        )
        label_font = gui_font(self.app.settings, self._s(HL.LABEL_FONT), "normal")
        state_font = gui_font(self.app.settings, self._s(HL.STATE_FONT), "normal")
        cy = y + h // 2
        pad = self._s(HL.ROW_MARGIN)
        enabled = bool(self.app.settings.get("global_hotkeys", False))
        if enabled:
            count = len(self.app.hotkeys.enabled_actions())
            label = t("hotkeys.global_active", n=count)
        else:
            label = t("hotkeys.global_enable")
        self.canvas.create_text(
            x + pad, cy, text=label, fill=rgb_hex("text_primary"),
            anchor="w", font=label_font, tags=("hk_global",),
        )
        switch = self.sprites.settings_sprite(
            "switch_on.png" if enabled else "switch_off.png",
            self.scale, max_h=self._s(HL.SWITCH_MAX_H),
        )
        if switch:
            switch_x = x + w - pad - switch.width()
            self.canvas.create_image(
                switch_x, cy, anchor="w", image=switch, tags=("hk_global", "hk_global_sw"),
            )
            state_x = switch_x - self._s(HL.SWITCH_GAP)
        else:
            state_x = x + w - pad
        self.canvas.create_text(
            state_x, cy,
            text=t("settings.state_on") if enabled else t("settings.state_off"),
            fill=rgb_hex("buttons_active") if enabled else rgb_hex("text_secondary"),
            anchor="e", font=state_font, tags=("hk_global",),
        )
        bind_clickable(
            self.canvas, x, y, w, h, self._toggle_global_mode, tag="hk_hit_global",
        )

    def _toggle_global_mode(self) -> None:
        self.app.set_global_hotkeys(
            not self.app.settings.get("global_hotkeys", False)
        )

    def _draw_hint(self) -> None:
        self.canvas.delete("hk_hint_more_hit")
        font = gui_font(self.app.settings, self._s(HL.HINT_FONT), "normal")
        capturing = self._capture_action is not None and bool(self._capture_steps)
        if capturing:
            text = t(
                "hotkeys.capture_next_hint",
                combo=format_key_name(" ".join(self._capture_steps)),
            )
        else:
            text = self._note or t("hotkeys.hint")
        highlight = capturing or bool(self._note)
        self.canvas.create_text(
            self._s(HL.ROW_X), self._s(HL.HINT_Y), text=text, anchor="w", font=font,
            fill=rgb_hex("orange_main") if highlight else rgb_hex("text_secondary"),
            tags=("hk_hint",),
        )
        hidden = len(self.app.hotkeys.disabled)
        if not hidden or highlight:
            return
        label = (
            t("hotkeys.hide_disabled") if self._show_disabled
            else t("hotkeys.show_disabled", n=hidden)
        )
        item = self.canvas.create_text(
            self._s(HL.ROW_X + HL.ROW_W), self._s(HL.HINT_Y), text=label,
            anchor="e", font=font, fill=rgb_hex("buttons_active"),
            tags=("hk_hint", "hk_hint_more"),
        )
        bbox = self.canvas.bbox(item)
        if not bbox:
            return
        pad = self._s(3)
        bind_clickable(
            self.canvas, bbox[0] - pad, bbox[1] - pad,
            (bbox[2] - bbox[0]) + 2 * pad, (bbox[3] - bbox[1]) + 2 * pad,
            self._toggle_show_disabled, tag="hk_hint_more_hit",
        )

    def _toggle_show_disabled(self) -> None:
        self._show_disabled = not self._show_disabled
        self._first_row = 0
        self._refresh()

    def _draw_sound_row(self) -> None:
        """Row that opens the confirmation-sound settings."""
        x, y = self._s(HL.ROW_X), self._s(HL.SOUND_Y)
        w, h = self._s(HL.ROW_W), self._s(HL.ROW_H)
        self.canvas.create_rectangle(
            x, y, x + w, y + h, fill=rgb_hex("range_buttons"), outline="",
            tags=("hk_sound", "hk_sound_bg"),
        )
        label_font = gui_font(self.app.settings, self._s(HL.LABEL_FONT), "normal")
        state_font = gui_font(self.app.settings, self._s(HL.STATE_FONT), "normal")
        cy = y + h // 2
        pad = self._s(HL.ROW_MARGIN)
        self.canvas.create_text(
            x + pad, cy, text=t("sound.row"), fill=rgb_hex("text_primary"),
            anchor="w", font=label_font, tags=("hk_sound",),
        )
        enabled = bool(self.app.settings.get("beep_enabled", True))
        if enabled:
            volume = int(self.app.settings.get("beep_volume", sound.DEFAULT_VOLUME))
            labels = sound.style_labels()
            on_style = self.app.settings.get("beep_style_on", sound.DEFAULT_STYLE)
            off_style = self.app.settings.get("beep_style_off", sound.DEFAULT_STYLE)
            text = (
                f"{labels.get(on_style, on_style)} / {labels.get(off_style, off_style)}"
                f" · {volume}%"
            )
            color = rgb_hex("buttons_active")
        else:
            text = t("settings.state_off")
            color = rgb_hex("text_secondary")
        self.canvas.create_text(
            x + w - pad, cy, text=text + "  ›", fill=color, anchor="e",
            font=state_font, tags=("hk_sound",),
        )
        bind_clickable(
            self.canvas, x, y, w, h, self._open_sound_popup, tag="hk_hit_sound",
        )

    def _open_sound_popup(self) -> None:
        from gui.sound_popup import SoundPopup

        SoundPopup(self.app, self)

    def _draw_reset(self) -> None:
        x, y = self._s(HL.ROW_X), self._s(HL.RESET_Y)
        w, h = self._s(HL.ROW_W), self._s(HL.RESET_H)
        self.canvas.create_rectangle(
            x, y, x + w, y + h, fill=rgb_hex("range_buttons"), outline="",
            tags=("hk_reset", "hk_reset_bg"),
        )
        font = gui_font(self.app.settings, self._s(HL.LABEL_FONT), "normal")
        self.canvas.create_text(
            x + w // 2, y + h // 2, text=t("hotkeys.reset"),
            fill=rgb_hex("buttons_active"), anchor="center", font=font,
            tags=("hk_reset",),
        )
        bind_clickable(
            self.canvas, x, y, w, h, self._reset_defaults, tag="hk_hit_reset",
        )

    def _draw_scrollbar(self) -> None:
        max_first = self._max_first_row()
        if max_first <= 0:
            return
        _step, visible = self._row_metrics()
        total = len(self.visible_actions())
        track_top = HL.VIEW_TOP
        track_h = HL.VIEW_BOTTOM - HL.VIEW_TOP
        thumb_h = max(16, int(track_h * visible / total))
        thumb_y = track_top + int((track_h - thumb_h) * (self._first_row / max_first))
        self.canvas.create_rectangle(
            self._s(HL.SCROLL_X), self._s(track_top),
            self._s(HL.SCROLL_X + HL.SCROLL_W), self._s(HL.VIEW_BOTTOM),
            fill=rgb_hex("range_buttons"), outline="", tags=("hk_scroll", "hk_scroll_track"),
        )
        self.canvas.create_rectangle(
            self._s(HL.SCROLL_X), self._s(thumb_y),
            self._s(HL.SCROLL_X + HL.SCROLL_W), self._s(thumb_y + thumb_h),
            fill=rgb_hex("text_secondary"), outline="", tags=("hk_scroll", "hk_scroll_thumb"),
        )

    def _draw_rows(self) -> None:
        self.canvas.delete("hk_rows")
        for action in ACTION_ORDER:
            self.canvas.delete(f"hk_action_hit_{action}")
            self.canvas.delete(f"hk_switch_hit_{action}")
        actions = self.visible_actions()
        self._first_row = max(0, min(self._first_row, self._max_first_row()))

        step, visible = self._row_metrics()
        mapping = self.app.hotkeys.map
        label_font = gui_font(self.app.settings, self._s(HL.LABEL_FONT), "normal")
        key_font = gui_font(self.app.settings, self._s(HL.KEY_FONT), "bold")

        y = HL.VIEW_TOP
        for action in actions[self._first_row:self._first_row + visible]:
            self._draw_row(action, y, mapping.get(action, ""), label_font, key_font)
            y += step
        self._draw_scrollbar()

    def _draw_row(
        self, action: str, y: int, sequence: str, label_font: tuple, key_font: tuple,
    ) -> None:
        x = self._s(HL.ROW_X)
        y_px = self._s(y)
        w = self._s(HL.ROW_W)
        h = self._s(HL.ROW_H)
        enabled = self.app.hotkeys.is_action_enabled(action)
        capturing = action == self._capture_action
        background = "buttons_active" if capturing else "range_buttons"
        self.canvas.create_rectangle(
            x, y_px, x + w, y_px + h, fill=rgb_hex(background), outline="",
            tags=("hk_rows", f"hk_bg_{action}"),
        )
        cy = y_px + h // 2

        # Left switch: whether this single shortcut is active at all.
        switch = self.sprites.settings_sprite(
            "switch_on.png" if enabled else "switch_off.png",
            self.scale, max_h=self._s(HL.ROW_SWITCH_MAX_H),
        )
        if switch:
            self.canvas.create_image(
                x + self._s(HL.ROW_SWITCH_X), cy, anchor="w", image=switch,
                tags=("hk_rows", f"hk_sw_{action}"),
            )

        self.canvas.create_text(
            x + self._s(HL.LABEL_INDENT), cy, text=action_label(action), anchor="w",
            font=label_font,
            fill=rgb_hex("text_primary" if enabled else "text_secondary"),
            tags=("hk_rows", f"hk_lbl_{action}"),
        )

        pad = self._s(HL.ROW_MARGIN)
        if not enabled:
            key_text, key_color = t("hotkeys.disabled"), rgb_hex("text_secondary")
        elif capturing:
            if self._capture_steps:
                key_text = format_key_name(" ".join(self._capture_steps)) + " …"
            else:
                key_text = t("hotkeys.capture")
            key_color = rgb_hex("text_primary")
        else:
            key_text = format_key_name(sequence) or t("hotkeys.action_none")
            key_color = rgb_hex("text_primary") if sequence else rgb_hex("text_secondary")
        self.canvas.create_text(
            x + w - pad, cy, text=key_text, fill=key_color, anchor="e",
            font=key_font, tags=("hk_rows", f"hk_key_{action}"),
        )

        # Narrow left strip = on/off switch, the rest of the row = rebind.
        zone = self._s(HL.TOGGLE_ZONE_W)
        bind_clickable(
            self.canvas, x, y_px, zone, h,
            lambda a=action: self._toggle_action(a), tag=f"hk_switch_hit_{action}",
        )
        if enabled:
            bind_clickable(
                self.canvas, x + zone, y_px, w - zone, h,
                lambda a=action: self.begin_capture(a), tag=f"hk_action_hit_{action}",
            )

    def _toggle_action(self, action: str) -> None:
        """Turn one shortcut on/off (its key is kept for later)."""
        self.app.hotkeys.set_action_enabled(
            action, not self.app.hotkeys.is_action_enabled(action)
        )
        self._refresh()

    # ------------------------------------------------------------------
    # Scrolling
    # ------------------------------------------------------------------

    def _scroll(self, delta: int) -> None:
        if self._max_first_row() <= 0:
            return
        self._first_row = max(0, min(self._first_row + delta, self._max_first_row()))
        self._draw_rows()
        self.raise_click_layer()

    def _on_wheel(self, event: tk.Event) -> str:
        self._scroll(-2 if getattr(event, "delta", 0) > 0 else 2)
        return "break"

    # ------------------------------------------------------------------
    # Rebinding
    # ------------------------------------------------------------------

    @property
    def capturing(self) -> bool:
        return self._capture_action is not None

    def begin_capture(self, action: str) -> None:
        """Arm a row: the next key press becomes its shortcut."""
        if self._capture_action == action:
            self.cancel_capture()
            self._refresh()
            return
        self.cancel_capture()
        self._capture_action = action
        self.app.hotkeys.capturing = True
        self._note = ""
        # Make sure the armed row is on screen.
        actions = self.visible_actions()
        if action in actions:
            index = actions.index(action)
            _step, visible = self._row_metrics()
            if index < self._first_row or index >= self._first_row + visible:
                self._first_row = max(0, min(index, self._max_first_row()))
        self._refresh()

    def cancel_capture(self) -> None:
        self._capture_action = None
        self._capture_steps = []
        self._cancel_capture_timer()
        self.app.hotkeys.capturing = False

    # -- capture of one key, or a two-key chord --------------------------

    def _cancel_capture_timer(self) -> None:
        if self._capture_after is not None:
            try:
                self.app.root.after_cancel(self._capture_after)
            except tk.TclError:
                pass
            self._capture_after = None

    def _schedule_capture_timer(self) -> None:
        self._cancel_capture_timer()
        action = self._capture_action
        self._capture_after = self.app.root.after(
            HL.CHORD_CAPTURE_MS, lambda: self._capture_timeout_for(action),
        )

    def _capture_timeout_for(self, action: str | None) -> None:
        """Timer callback – ignored when the row has changed in the meantime."""
        self._capture_after = None
        if self._capture_action != action:
            return
        self._capture_timeout()

    def _capture_timeout(self) -> None:
        """Only one key was pressed – keep it as a single-key shortcut."""
        self._cancel_capture_timer()
        try:
            self._commit_capture()
        except tk.TclError:
            pass

    def _commit_capture(self) -> None:
        action = self._capture_action
        steps = list(self._capture_steps)
        self.cancel_capture()
        if action is None or not steps:
            return
        self._apply_capture(action, " ".join(steps))

    def on_capture_key(self, event: tk.Event) -> str | None:
        """Called by :class:`HotkeyManager` for every key while a row is armed."""
        if self._capture_action is None:
            return None
        sequence = sequence_from_event(event)
        if sequence is None:
            return "break"  # modifier only – swallow and keep waiting
        if sequence == "Escape":
            self.cancel_capture()
            self._refresh()
            return "break"

        keysym = getattr(event, "keysym", "")
        if not self._capture_steps:
            if keysym in _CLEAR_KEYSYMS:      # Delete clears the binding
                action = self._capture_action
                self.cancel_capture()
                if action is not None:
                    self._apply_capture(action, "")
                return "break"
            self._capture_steps = [sequence]
            if not is_chord_capable(sequence):
                # Modifier combos and F-keys can never start a chord.
                self._commit_capture()
                return "break"
            self._schedule_capture_timer()
            self._refresh()
            return "break"

        # Second key: complete the chord (Return keeps just the first key).
        if keysym in _COMMIT_KEYSYMS:
            self._commit_capture()
            return "break"
        if keysym in _CLEAR_KEYSYMS:
            self.cancel_capture()
            self._refresh()
            return "break"
        self._capture_steps.append(sequence)
        self._commit_capture()
        return "break"

    def _apply_capture(self, action: str, sequence: str) -> None:
        swapped = self.app.hotkeys.set_key(action, sequence)
        if swapped:
            self._set_note(t("hotkeys.note_swapped", name=action_label(swapped)))
        elif not sequence:
            self._set_note(t("hotkeys.note_cleared", name=action_label(action)))
        else:
            self._set_note(t(
                "hotkeys.note_set",
                name=action_label(action),
                combo=format_key_name(sequence),
            ))
        self._refresh()

    def on_hide(self) -> None:
        """Leave the screen – drop any half-finished capture."""
        if self._capture_action is not None:
            self.cancel_capture()
            self._refresh()

    def dispose(self) -> None:
        """Cancel pending timers before the screen is rebuilt."""
        self.cancel_capture()
        if self._note_after is not None:
            try:
                self.app.root.after_cancel(self._note_after)
            except tk.TclError:
                pass
            self._note_after = None

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        self.canvas.delete("hk_hint")
        self.canvas.delete("hk_rows")
        self.canvas.delete("hk_scroll")
        self._draw_hint()
        self._draw_rows()
        self.raise_click_layer()

    def _set_note(self, note: str) -> None:
        self._note = note
        if self._note_after is not None:
            try:
                self.app.root.after_cancel(self._note_after)
            except tk.TclError:
                pass
            self._note_after = None
        if note:
            self._note_after = self.app.root.after(HL.NOTE_MS, self._clear_note)

    def _clear_note(self) -> None:
        self._note_after = None
        self._note = ""
        try:
            self.canvas.delete("hk_hint")
            self._draw_hint()
        except tk.TclError:
            pass

    def _toggle_enabled(self) -> None:
        self.app.settings["hotkeys"] = not bool(self.app.settings.get("hotkeys", True))
        save_settings(self.app.settings)
        self.canvas.delete("hk_toggle")
        self.canvas.delete("hk_hit_toggle")
        self._draw_toggle()
        self.raise_click_layer()

    def _reset_defaults(self) -> None:
        self.app.hotkeys.reset_map()
        self._set_note(t("hotkeys.note_reset"))
        self._first_row = 0
        self._refresh()
