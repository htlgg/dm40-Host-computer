"""Main application window – Main / Range / Settings screen switching."""

import time

import tkinter as tk

from ble.worker import BleCallbacks, BleWorker
from core.config import CMD_DISCOVERY, CMD_POLL, IMAGES_DIR
from core.protocol_constants import CMD_ID
from core.i18n import t, get_i18n
from gui import layout as display_layout
from core.modes import MODE_CYCLE_GROUPS, ModeState
from core.parsing import MODEL, range_label_from_packet
from core.ranges import range_display_label
from gui.main_screen import MainScreen
from gui.range_screen import RangeScreen
from gui.raw_console import RawConsole
from gui.settings import load_settings, apply_saved_model, save_settings, persist_device
from gui.connect_screen import ConnectScreen
from gui import sound
from gui.diagnostics import log
from gui.global_hotkeys import GlobalHotkeys
from gui.hotkeys import HotkeyManager
from gui.hotkeys_screen import HotkeysScreen
from gui.settings_screen import SettingsScreen
from gui.theme import rgb_hex
from gui.win_titlebar import fit_toplevel_to_client, schedule_windows_titlebar

_BACKGROUND_TX = frozenset({CMD_DISCOVERY, CMD_POLL, CMD_ID})


class DM40App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.settings = load_settings()
        apply_saved_model(self.settings)

        # Initialize i18n from language in settings.json
        lang = (self.settings.get("language") or "").strip() or "en-US"
        get_i18n().init(lang)
        self.scale = float(self.settings.get("window_scale", 1.0))
        self.mode_state = ModeState()
        for gid, opts in MODE_CYCLE_GROUPS:
            self.mode_state.register_group(gid, opts)
        self.mode_state.load()

        self._current_screen = "main"
        self._client_w = int(display_layout.SCREEN_W * self.scale)
        self._rebuilding = False
        self._fullscreen = False
        self._zoomed = False
        self._suppress_resize = False
        self._startup_scale = self.scale
        self._startup_pos: tuple[int, int] | None = None
        self._windowed_pos: tuple[int, int] | None = None
        self._configure_after: str | None = None

        self.root.title(t("app.title"))
        self.root.resizable(True, True)
        self._apply_window_icon()
        # Apply dark caption as early as possible – some Windows builds only
        # honour the attribute while the frame is being created.
        try:
            from gui.win_titlebar import apply_windows_titlebar

            apply_windows_titlebar(self.root)
        except Exception:
            pass
        self.root.configure(bg=rgb_hex("background"))

        self._ui_column = tk.Frame(root, bg=rgb_hex("background"))
        self._ui_column.pack()

        dm40_h = self._dm40_logical_height()
        self._client_dm40_h = int(dm40_h * self.scale)
        self.container = tk.Frame(
            self._ui_column, bg=rgb_hex("background"),
            width=self._client_w, height=self._client_dm40_h,
        )
        self.container.pack_propagate(False)
        self.container.pack(expand=True)

        self.raw_console = RawConsole(self._ui_column, self.scale)

        self._readings: list[str] = []
        self._last_range_flag = 0
        self._raw_rx_burst_until = 0.0
        self._last_raw_line = ""
        self._raw_poll_pending: str | None = None
        self._raw_poll_after: str | None = None
        self._meas_pending: tuple[object, bytes] | None = None
        self._meas_scheduled = False
        self._ble_started = False

        cbs = BleCallbacks(
            on_connecting=self._on_connecting,
            on_connected=self._on_connected,
            on_disconnected=self._on_disconnected,
            on_bluetooth_off=self._on_bluetooth_off,
            on_model=self._on_model,
            on_measurement=self._on_measurement,
            on_raw_traffic=self._on_raw_traffic,
        )
        self.ble = BleWorker(cbs, target_mac=self.settings.get("target_mac", ""))

        self.main_screen = MainScreen(self.container, self, self.scale)
        self.range_screen = RangeScreen(self.container, self, self.scale)
        self.settings_screen = SettingsScreen(self.container, self, self.scale)
        self.hotkeys_screen = HotkeysScreen(self.container, self, self.scale)
        self.connect_screen = ConnectScreen(self.container, self, self.scale)
        place_kw = dict(x=0, y=0, width=self._client_w, height=self._client_dm40_h)
        for screen in (
            self.main_screen, self.range_screen, self.settings_screen,
            self.hotkeys_screen, self.connect_screen,
        ):
            screen.place(**place_kw)

        self.main_screen.refresh_mode_buttons(self.mode_state)
        self.global_hotkeys = GlobalHotkeys(self)
        self.hotkeys = HotkeyManager(self)
        self.hotkeys.capture_sink = self.hotkeys_screen.on_capture_key
        self.global_hotkeys.start()
        schedule_windows_titlebar(self.root)
        self.root.bind("<Configure>", self._on_configure, add="+")
        # Remember where the window opened so leaving full screen can restore it.
        self.root.after(900, self._remember_startup_pos)
        self.root.after(1100, self._startup_titlebar_refresh)
        if self._needs_device_setup():
            self.show_connect_screen(auto_scan=True)
        else:
            self.show_main_screen()
            self._sync_raw_callback()
            self.ble.start()
            self._ble_started = True

    def _needs_device_setup(self) -> bool:
        return not (self.settings.get("target_mac") or "").strip()

    def complete_device_setup(self, device) -> None:
        from core.parsing import apply_model

        apply_model(device.model_name, device.device_counts)
        self.settings["target_mac"] = device.address
        self.settings["model_name"] = device.model_name
        self.settings["device_counts"] = device.device_counts
        save_settings(self.settings)
        self.ble.set_target_mac(device.address)
        if not self._ble_started:
            self.ble.start()
            self._ble_started = True
        self.connect_screen.on_hide()
        self.show_main_screen()

    def reload_language(self, lang_code: str) -> None:
        """Switch language, refresh all screens, and update settings.json."""
        i18n = get_i18n()
        if not i18n.load_language(lang_code):
            return
        # Atomic settings.json write (.tmp then replace, prevents corruption)
        self.settings["language"] = lang_code
        from gui.settings import save_settings
        if not save_settings(self.settings):
            # Save failure does not block UI refresh; in-memory language still applies this session
            pass
        # Refresh UI
        self.root.title(t("app.title"))
        self._refresh_all_screens_i18n()

    def _refresh_all_screens_i18n(self) -> None:
        """Refresh translatable strings on every screen (language is switched from Settings)."""
        self.main_screen.refresh_all()
        kind = self.mode_state.get_active_kind()
        self.range_screen.rebuild_for_kind(kind, self._last_range_flag)
        self.settings_screen.rebuild()
        self.hotkeys_screen.rebuild()
        self.connect_screen.refresh_all()
        self._apply_window_size()

    def show_connect_screen(self, *, auto_scan: bool = False) -> None:
        self._current_screen = "connect"
        self.hotkeys_screen.on_hide()
        self.main_screen.lower()
        self.range_screen.lower()
        self.settings_screen.lower()
        self.hotkeys_screen.lower()
        self.connect_screen.lift()
        self.apply_settings()
        self.connect_screen.on_show(auto_scan=auto_scan)
        self.connect_screen.raise_click_layer()

    def _sync_raw_callback(self) -> None:
        """Without RAW console, do not call callback from BLE thread (every poll TX+RX)."""
        self.ble._callbacks.on_raw_traffic = (
            self._on_raw_traffic if self.settings.get("raw_console") else None
        )

    def _dm40_logical_height(self) -> int:
        if self._current_screen == "main" and self.settings.get("mini_app"):
            return display_layout.MINI_SCREEN_H
        return display_layout.SCREEN_H

    def _client_dimensions(self) -> tuple[int, int]:
        h = int(self._dm40_logical_height() * self.scale)
        if self._current_screen == "main" and self.settings.get("raw_console"):
            h += int(display_layout.RAW_CONSOLE_H * self.scale)
        return self._client_w, h

    def _apply_window_size(self) -> None:
        """Client area = DM40 UI (+ RAW console); no empty strip below content."""
        if self._rebuilding or self._fullscreen:
            return
        self.root.update_idletasks()
        self.root.update()
        w, h = self._client_dimensions()
        fit_toplevel_to_client(self.root, self._ui_column, w, h)
        # fit_toplevel_to_client pins the minimum to the CURRENT size, which
        # would stop the user from shrinking the window again.
        self.root.minsize(240, 150)

    # -- window scaling --------------------------------------------------

    def _on_configure(self, event=None) -> None:
        """Debounce window resizes – child widgets also raise Configure."""
        if event is not None and event.widget is not self.root:
            return
        if self._rebuilding:
            return
        if self._configure_after is not None:
            try:
                self.root.after_cancel(self._configure_after)
            except tk.TclError:
                pass
        self._configure_after = self.root.after(260, self._apply_resize)

    def _logical_height_with_console(self) -> int:
        """Logical height of everything the window shows (UI + RAW console)."""
        height = self._dm40_logical_height()
        if self._current_screen == "main" and self.settings.get("raw_console"):
            height += display_layout.RAW_CONSOLE_H
        return height

    def _apply_resize(self) -> None:
        self._configure_after = None
        if self._rebuilding or self._suppress_resize:
            return
        try:
            width = self.root.winfo_width()
            height = self.root.winfo_height()
            fullscreen = bool(self.root.attributes("-fullscreen"))
            zoomed = self.root.state() == "zoomed"
        except tk.TclError:
            return

        # Left full screen through the system button / Win+Up?
        if self._fullscreen and not fullscreen:
            self._exit_fullscreen()
            return
        self._fullscreen = fullscreen

        # Maximise button: scale while maximised, but come back to the startup
        # size when the window is restored again (same as the full screen path).
        if zoomed and not self._zoomed:
            self._zoomed = True
            self._windowed_scale = self.scale
            self._windowed_pos = (self.root.winfo_x(), self.root.winfo_y())
        elif not zoomed and self._zoomed:
            self._zoomed = False
            self._restore_windowed_state()
            return

        if width < 80 or height < 60:
            return
        logical_h = self._logical_height_with_console()
        self._rebuild_screens(min(width / display_layout.SCREEN_W, height / logical_h))

    def toggle_fullscreen(self) -> None:
        """Full screen ⇄ the size/scale the app was started with."""
        if not self._fullscreen:
            self._windowed_scale = self.scale
            self._windowed_pos = (self.root.winfo_x(), self.root.winfo_y())
            self._fullscreen = True
            try:
                self.root.attributes("-fullscreen", True)
            except tk.TclError:
                self._fullscreen = False
                return
            self.root.after(320, self._apply_resize)
        else:
            self._exit_fullscreen()

    def _exit_fullscreen(self) -> None:
        """Return to the startup ratio and position (not the huge screen size)."""
        self._fullscreen = False
        try:
            self.root.attributes("-fullscreen", False)
        except tk.TclError:
            pass
        self._restore_windowed_state()

    def _restore_windowed_state(self) -> None:
        """Back to the startup scale, size and position."""
        self._suppress_resize = True
        target = self._startup_scale or self.scale
        self._rebuild_screens(target)
        self._apply_window_size()

        position = self._startup_pos or self._windowed_pos
        if position:
            try:
                self.root.geometry(f"+{max(0, position[0])}+{max(0, position[1])}")
            except tk.TclError:
                pass

        if self._configure_after is not None:
            try:
                self.root.after_cancel(self._configure_after)
            except tk.TclError:
                pass
            self._configure_after = None
        self.root.after(500, self._release_resize_guard)

    def _release_resize_guard(self) -> None:
        self._suppress_resize = False

    def _remember_startup_pos(self) -> None:
        """Store the window position used at launch, to restore it later."""
        if self._startup_pos is None and not self._fullscreen:
            try:
                self._startup_pos = (self.root.winfo_x(), self.root.winfo_y())
            except tk.TclError:
                pass

    def _startup_titlebar_refresh(self) -> None:
        """Make the dark caption stick on the very first frame.

        Windows only paints the DWM dark caption once the frame has been
        rearranged, which is why the bar turned dark after the user resized the
        window. Do that rearrangement ourselves right after startup.
        """
        try:
            width, height = self.root.winfo_width(), self.root.winfo_height()
            if width > 10 and height > 10:
                self.root.geometry(f"{width + 1}x{height}")
                self.root.update_idletasks()
                self.root.geometry(f"{width}x{height}")
                self.root.update_idletasks()
        except tk.TclError:
            pass
        self._reapply_titlebar()
        self.root.after(180, self._reapply_titlebar)

    def _reapply_titlebar(self) -> None:
        try:
            from gui.win_titlebar import apply_windows_titlebar

            if self.root.winfo_exists():
                apply_windows_titlebar(self.root)
        except Exception:
            pass

    def _rebuild_screens(self, scale: float) -> None:
        """Re-create every screen at a new scale, keeping the runtime state."""
        try:
            scale = float(scale)
        except (TypeError, ValueError):
            return
        scale = max(0.5, min(4.0, round(scale, 3)))
        if self._rebuilding or abs(scale - self.scale) < 0.005:
            return
        self._rebuilding = True
        try:
            previous = self._current_screen
            save_slots = self.main_screen._save_slots
            last_measurement = self.main_screen._last_display_measurement
            ble_state = self.main_screen._ble_state
            bt_off = self.main_screen._bt_off_display

            for widget in (
                self.main_screen, self.range_screen, self.settings_screen,
                self.hotkeys_screen, self.connect_screen,
            ):
                try:
                    widget.dispose()
                except Exception:
                    pass
                widget.destroy()

            self.scale = scale
            self.settings["window_scale"] = scale
            self._client_w = int(display_layout.SCREEN_W * scale)

            self.main_screen = MainScreen(self.container, self, scale)
            self.range_screen = RangeScreen(self.container, self, scale)
            self.settings_screen = SettingsScreen(self.container, self, scale)
            self.hotkeys_screen = HotkeysScreen(self.container, self, scale)
            self.connect_screen = ConnectScreen(self.container, self, scale)
            try:
                self.raw_console.destroy()
            except Exception:
                pass
            self.raw_console = RawConsole(self._ui_column, scale)
            self._sync_raw_callback()

            self.main_screen._save_slots = save_slots
            self.main_screen._refresh_save_slots()
            # Connection state first – "connecting" paints the "---" placeholder.
            if bt_off:
                self.main_screen.show_bluetooth_off()
            else:
                self.main_screen.set_ble_connection_state(ble_state)
            if last_measurement is not None:
                m, rng_label = last_measurement
                self.main_screen._last_display_measurement = (m, rng_label)
                self.main_screen.update_measurement(m, rng_label)
            self.hotkeys.capture_sink = self.hotkeys_screen.on_capture_key
            self._resize_container()
            self._update_raw_console_visibility()

            if previous == "range":
                self.show_range_screen()
            elif previous == "settings":
                self.show_settings_screen()
            elif previous == "hotkeys":
                self.show_hotkeys_screen()
            elif previous == "connect":
                self.show_connect_screen()
            else:
                self.show_main_screen()
        finally:
            self._rebuilding = False
        if not self._fullscreen:
            self._apply_window_size()
        self.root.after(220, self._reapply_titlebar)

    def _apply_window_icon(self) -> None:
        """Show the DM40 icon in the title bar / taskbar instead of Tk's feather."""
        try:
            icon = IMAGES_DIR / "app.ico"
            if icon.exists():
                self.root.iconbitmap(default=str(icon))
        except Exception:
            pass

    def _resize_container(self) -> None:
        dm40_h = self._dm40_logical_height()
        self._client_dm40_h = int(dm40_h * self.scale)
        self.container.configure(width=self._client_w, height=self._client_dm40_h)
        place_kw = dict(x=0, y=0, width=self._client_w, height=self._client_dm40_h)
        for screen in (
            self.main_screen, self.range_screen, self.settings_screen,
            self.hotkeys_screen, self.connect_screen,
        ):
            screen.place(**place_kw)
        if self._current_screen == "main":
            self.main_screen.resize_to_logical_height(dm40_h)

    def _update_raw_console_visibility(self) -> None:
        show = self._current_screen == "main" and bool(self.settings.get("raw_console"))
        if show:
            self.raw_console.pack(fill="x", after=self.container)
        else:
            self.raw_console.pack_forget()
            self._raw_poll_pending = None
            self._cancel_raw_poll_tick()

    def apply_settings(self) -> None:
        self.root.attributes("-topmost", bool(self.settings.get("always_on_top", False)))
        mini = bool(self.settings.get("mini_app", False))
        self.main_screen.apply_view_mode(mini=mini, resize=self._current_screen == "main")
        if not self.settings.get("raw_console"):
            self._raw_poll_pending = None
            self._cancel_raw_poll_tick()
        self._sync_raw_callback()
        self._update_raw_console_visibility()
        self._resize_container()
        self._apply_window_size()

    @staticmethod
    def _format_raw_line(direction: str, data: bytes) -> str:
        hex_str = data.hex(" ").upper()
        if direction == "RX":
            crc = "PASS" if (sum(data) & 0xFF) == 0 else "FAIL"
            return f"RX {hex_str}  CRC:{crc}\n"
        return f"TX {hex_str}\n"

    def _is_priority_raw(self, direction: str, data: bytes) -> bool:
        """User TX (MODE, RANGE, HOLD, …) + short RX response."""
        if direction == "TX":
            return data not in _BACKGROUND_TX
        return direction == "RX" and time.monotonic() < self._raw_rx_burst_until

    def _append_raw_line(self, line: str, *, priority: bool) -> None:
        if not self.settings.get("raw_console") or self._current_screen != "main":
            return
        if priority:
            self._raw_poll_pending = None
            self._cancel_raw_poll_tick()
        elif line == self._last_raw_line:
            return
        self._last_raw_line = line
        self.raw_console.append(line)
        if priority and line.startswith("TX "):
            self._raw_rx_burst_until = time.monotonic() + 0.6

    def _cancel_raw_poll_tick(self) -> None:
        if self._raw_poll_after is not None:
            self.root.after_cancel(self._raw_poll_after)
            self._raw_poll_after = None

    def _schedule_raw_poll_tick(self) -> None:
        if self._raw_poll_after is None:
            self._raw_poll_after = self.root.after(
                display_layout.RAW_CONSOLE_POLL_MS, self._emit_raw_poll_line,
            )

    def _queue_raw_poll_line(self, line: str) -> None:
        """Poll: throttled output, no queue – keeps only the latest unshown line."""
        if line == self._last_raw_line:
            return
        self._raw_poll_pending = line
        self._schedule_raw_poll_tick()

    def _emit_raw_poll_line(self) -> None:
        self._raw_poll_after = None
        if not self.settings.get("raw_console") or self._current_screen != "main":
            self._raw_poll_pending = None
            return
        line = self._raw_poll_pending
        if line is None:
            return
        self._raw_poll_pending = None
        if line != self._last_raw_line:
            self._last_raw_line = line
            self.raw_console.append(line)
        if self._raw_poll_pending is not None:
            self._schedule_raw_poll_tick()

    def _on_raw_traffic(self, direction: str, data: bytes) -> None:
        line = self._format_raw_line(direction, data)
        if self._is_priority_raw(direction, data):
            self.root.after(0, lambda l=line: self._append_raw_line(l, priority=True))
            return
        self._queue_raw_poll_line(line)

    def show_main_screen(self) -> None:
        self._current_screen = "main"
        self.hotkeys_screen.on_hide()
        self.range_screen.lower()
        self.settings_screen.lower()
        self.hotkeys_screen.lower()
        self.connect_screen.lower()
        self.main_screen.lift()
        self.apply_settings()
        self.main_screen.raise_click_layer()

    def show_range_screen(self) -> None:
        self._current_screen = "range"
        self.hotkeys_screen.on_hide()
        kind = self.mode_state.get_active_kind()
        self.range_screen.rebuild_for_kind(kind, self._last_range_flag)
        self.main_screen.lower()
        self.settings_screen.lower()
        self.hotkeys_screen.lower()
        self.connect_screen.lower()
        self.range_screen.lift()
        self.apply_settings()
        self.range_screen.raise_click_layer()

    def show_settings_screen(self) -> None:
        previous = self._current_screen
        if previous != "hotkeys":
            # Coming back from the HOTKEYS screen must not overwrite where
            # Settings itself was opened from.
            self._screen_before_settings = previous
        self._current_screen = "settings"
        self.hotkeys_screen.on_hide()
        self.settings_screen.rebuild()
        self.main_screen.lower()
        self.range_screen.lower()
        self.hotkeys_screen.lower()
        self.connect_screen.lower()
        self.settings_screen.lift()
        self.apply_settings()
        self.settings_screen.raise_click_layer()

    def show_hotkeys_screen(self) -> None:
        self._current_screen = "hotkeys"
        self.hotkeys_screen.rebuild()
        self.main_screen.lower()
        self.range_screen.lower()
        self.settings_screen.lower()
        self.connect_screen.lower()
        self.hotkeys_screen.lift()
        self.apply_settings()
        self.hotkeys_screen.raise_click_layer()

    def go_back_from_settings(self) -> None:
        """Return to the screen that was visible before entering settings."""
        if getattr(self, "_screen_before_settings", "") == "connect":
            self.show_connect_screen()
        else:
            self.show_main_screen()

    def cycle_mode(self, group_id: str) -> None:
        self.main_screen.release_hold_freeze()
        self.ble.send_packet(self.mode_state.cycle_group(group_id))
        self.main_screen.refresh_mode_buttons(self.mode_state)
        self.main_screen.raise_click_layer()

    def save_reading(self) -> None:
        """Store the current reading (shared by the digits click and the shortcut)."""
        self.main_screen.save_reading()

    def clear_readings(self) -> None:
        """Wipe the saved readings (top-bar button, long press and shortcut)."""
        self.main_screen.clear_readings()

    def apply_global_hotkeys(self) -> None:
        """Kept for compatibility – the keyboard hook needs no registration."""
        return

    def set_global_hotkeys(self, enabled: bool) -> None:
        """Switch "shortcuts also work while another window is focused"."""
        enabled = bool(enabled)
        if bool(self.settings.get("global_hotkeys", False)) == enabled:
            return
        self.settings["global_hotkeys"] = enabled
        save_settings(self.settings)
        log(f"background mode -> {'ON' if enabled else 'OFF'}")
        sound.play(self.settings, "on" if enabled else "off")
        if self._current_screen == "hotkeys":
            self.hotkeys_screen.rebuild()

    def toggle_hold(self) -> None:
        """Toggle RUN / HOLD (shared by the top-bar area and the shortcut)."""
        self.main_screen.toggle_hold()

    @property
    def current_range_flag(self) -> int:
        """Last range flag seen from the meter (or the last one we requested)."""
        return self._last_range_flag

    def select_range_flag(self, flag: int, *, refresh_range_screen: bool = True) -> None:
        """Request a range (挡位) – shared by the RANGE screen and keyboard shortcuts."""
        self.main_screen.release_hold_freeze()
        self.ble.send_range_flag(flag)
        self._last_range_flag = flag
        label = range_display_label(flag, MODEL.model_name)
        if label:
            self.main_screen.set_range_label(label, flash=True)
        if refresh_range_screen and self._current_screen == "range":
            self.range_screen.rebuild_for_kind(self.mode_state.get_active_kind(), flag)
            self.range_screen.raise_click_layer()

    def capture_reading(self) -> None:
        pass

    def _on_connecting(self) -> None:
        self.root.after(0, lambda: self.main_screen.set_ble_connection_state("connecting"))

    def _on_connected(self) -> None:
        def ui() -> None:
            self.main_screen.set_ble_connection_state("connected")
            self._persist_device_from_session()

        self.root.after(0, ui)

    def _on_disconnected(self) -> None:
        self.root.after(0, lambda: self.main_screen.set_ble_connection_state("disconnected"))

    def _on_bluetooth_off(self) -> None:
        self.root.after(0, lambda: self.main_screen.show_bluetooth_off())

    def _on_model(self) -> None:
        def ui() -> None:
            self.main_screen.set_ble_connection_state("connected")
            self._persist_device_from_session()

        self.root.after(0, ui)

    def _persist_device_from_session(self) -> None:
        persist_device(
            self.settings,
            mac=self.ble.target_mac,
            model_name=MODEL.model_name,
            device_counts=MODEL.device_counts,
        )

    def _on_measurement(self, m, data: bytes) -> None:
        self._meas_pending = (m, data)
        if not self._meas_scheduled:
            self._meas_scheduled = True
            self.root.after(0, self._flush_measurement)

    def _flush_measurement(self) -> None:
        self._meas_scheduled = False
        pending = self._meas_pending
        if pending is None:
            return
        self._meas_pending = None
        m, data = pending
        if len(data) > 5:
            self._last_range_flag = data[5]
        if not m.hold:
            self.mode_state.last_kind = m.kind
            if self.mode_state.sync_from_kind(m.kind):
                self.main_screen.refresh_mode_buttons(self.mode_state)
        rng = range_label_from_packet(data, m.range)
        trace_key = data[5] if len(data) > 5 else 0
        self.main_screen.update_measurement(m, rng, trace_key)


def run_app() -> None:
    root = tk.Tk()
    DM40App(root)
    # Last chance before the event loop: the frame now exists for real.
    try:
        root.update_idletasks()
        from gui.win_titlebar import apply_windows_titlebar

        apply_windows_titlebar(root)
    except Exception:
        pass
    root.after(1200, lambda: _reapply_titlebar(root))
    root.mainloop()


def _reapply_titlebar(root: tk.Tk) -> None:
    try:
        from gui.win_titlebar import apply_windows_titlebar

        if root.winfo_exists():
            apply_windows_titlebar(root)
    except Exception:
        pass
