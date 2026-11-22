"""Connect (cold run) – DM40 device selection in the main app window."""

from __future__ import annotations

import queue
import threading

import tkinter as tk

from ble.discovery import DM40Device, scan_ble_devices_sync
from core.config import SCREEN_HEIGHT, SCREEN_WIDTH
from core.i18n import t
from gui import connect_layout as CL
from gui import range_layout as RL
from gui import layout as L
from gui.assets import bind_clickable, raise_click_hotspots
from gui.sprites import SpriteCache
from gui.fonts import gui_font
from gui.theme import rgb_hex


class ConnectScreen(tk.Frame):
    def __init__(self, master, app, scale: float) -> None:
        super().__init__(master, bg=rgb_hex("background"))
        self.app = app
        self.scale = scale
        self.sprites = SpriteCache()
        w, h = int(SCREEN_WIDTH * scale), int(SCREEN_HEIGHT * scale)
        self.configure(width=w, height=h)
        self.pack_propagate(False)

        self.canvas = tk.Canvas(self, width=w, height=h, highlightthickness=0, bg=rgb_hex("background"))
        self.canvas.pack()

        self._devices: list[DM40Device] = []
        self._selected = -1
        self._scanning = False
        self._scan_queue: queue.Queue = queue.Queue()
        self._sprite_ids: dict[str, int] = {}
        self._ble_pulse_on = True
        self._ble_pulse_after: str | None = None
        self._status_id: int | None = None
        self._connect_btn_bg_ids: dict[int, int] = {}

        self._draw_chrome()
        self._draw_bottom_buttons()

    def _s(self, v: float) -> int:
        return int(v * self.scale)

    def raise_click_layer(self) -> None:
        raise_click_hotspots(self.canvas)

    def _draw_chrome(self) -> None:
        self.canvas.create_rectangle(
            0, 0, self._s(L.SCREEN_W), self._s(L.TOP_BAR_H),
            fill=rgb_hex("top_bar_background"), outline="", tags="connect_chrome",
        )
        font = gui_font(self.app.settings, self._s(CL.SETUP_TITLE_FONT), "bold")
        self.canvas.create_text(
            self._s(L.SCREEN_W // 2), self._s(CL.SETUP_TITLE_Y), text=t("setup.title"),
            fill=rgb_hex("text_primary"), anchor="center", font=font, tags="connect_chrome",
        )
        hint_font = gui_font(self.app.settings, self._s(CL.SETUP_HINT_FONT), "normal")
        self.canvas.create_text(
            self._s(L.SCREEN_W // 2), self._s(CL.SETUP_HINT_Y),
            text=t("setup.hint"),
            fill=rgb_hex("text_secondary"), anchor="center", font=hint_font, tags="connect_chrome",
        )
        status_font = gui_font(self.app.settings, self._s(CL.SETUP_STATUS_FONT), "normal")
        self._status_id = self.canvas.create_text(
            self._s(L.SCREEN_W // 2), self._s(CL.SETUP_STATUS_Y), text="",
            fill=rgb_hex("text_primary"), anchor="center", font=status_font, tags="connect_chrome",
        )
        self._set_status(t("setup.status_initial"))
        self._place_settings_icon()
        self._place_back_icon()
        self._bind_back()

    def _place_settings_icon(self) -> None:
        """Settings icon in the top bar (same position as main screen)."""
        photo = self._top_bar_icon("settings.png", L.TOP_BAR_SETTINGS_W)
        if photo:
            self._show_sprite("settings", photo,
                              self._s(L.SETTINGS_IMG[0]), self._s(L.SETTINGS_IMG[1]))
        sx, sy, sw, sh = L.SETTINGS_HIT
        bind_clickable(
            self.canvas, self._s(sx), self._s(sy), self._s(sw), self._s(sh),
            self.app.show_settings_screen, tag="connect_hit_settings",
        )

    def _current_device(self) -> DM40Device | None:
        """The meter this app is already using (it stops advertising when linked)."""
        mac = (self.app.settings.get("target_mac") or "").strip()
        if not mac:
            return None
        model = self.app.settings.get("model_name") or "DM40C"
        counts = int(self.app.settings.get("device_counts") or 60000)
        return DM40Device(
            address=mac, name=model, model_name=model, device_counts=counts,
            known=True, connected=bool(getattr(self.app.ble, "connected", False)),
        )

    def _has_device(self) -> bool:
        return bool((self.app.settings.get("target_mac") or "").strip())

    def _place_back_icon(self) -> None:
        """Back arrow – only when a meter is already configured."""
        if not self._has_device():
            return
        photo = self.sprites.range_menu_sprite(
            "back.png", self.scale, max_h=self._s(L.TOP_BAR_H - 12),
        )
        if photo:
            self._show_sprite("back", photo,
                              self._s(RL.RANGE_BACK_IMG[0]), self._s(RL.RANGE_BACK_IMG[1]))

    def _bind_back(self) -> None:
        if not self._has_device():
            return
        bx, by, bw, bh = RL.range_back_hit()
        bind_clickable(
            self.canvas, self._s(bx), self._s(by), self._s(bw), self._s(bh),
            self.app.show_main_screen, tag="connect_hit_back",
        )

    def _set_status(self, text: str) -> None:
        if self._status_id is not None:
            self.canvas.itemconfigure(self._status_id, text=text)

    def _top_bar_icon(self, name: str, max_w: int) -> tk.PhotoImage | None:
        return self.sprites.top_bar(
            name, self.scale,
            max_w=self._s(max_w), max_h=self._s(L.TOP_BAR_ICON_H),
        )

    def _show_sprite(self, key: str, photo: tk.PhotoImage, x: int, y: int) -> None:
        if key in self._sprite_ids:
            self.canvas.delete(self._sprite_ids[key])
        self._sprite_ids[key] = self.canvas.create_image(
            x, y, anchor="nw", image=photo, tags="connect_chrome",
        )

    def _hide_sprite(self, key: str) -> None:
        item = self._sprite_ids.pop(key, None)
        if item is not None:
            self.canvas.delete(item)

    def _show_bt_icon(self) -> None:
        photo = self._top_bar_icon("bluetooth.png", L.TOP_BAR_BT_W)
        if photo:
            self._show_sprite("bt", photo, self._s(L.BT_IMG[0]), self._s(L.BT_IMG[1]))

    def _stop_bt_pulse(self) -> None:
        if self._ble_pulse_after is not None:
            self.app.root.after_cancel(self._ble_pulse_after)
            self._ble_pulse_after = None

    def _bt_pulse_tick(self) -> None:
        if not self._scanning:
            return
        if self._ble_pulse_on:
            self._show_bt_icon()
        else:
            self._hide_sprite("bt")
        self._ble_pulse_on = not self._ble_pulse_on
        self._ble_pulse_after = self.app.root.after(550, self._bt_pulse_tick)

    def _start_bt_pulse(self) -> None:
        self._stop_bt_pulse()
        self._ble_pulse_on = True
        self._bt_pulse_tick()

    def _stop_scan_ui(self) -> None:
        self._scanning = False
        self._stop_bt_pulse()
        self._show_bt_icon()

    def _connect_btn_bg_photo(self, rw: int, rh: int, radius: int, *, hovered: bool) -> tk.PhotoImage | None:
        color = "buttons_active" if hovered else "buttons"
        return self.sprites.rounded_button(color, rw, rh, radius)

    def _set_connect_btn_hover(self, index: int, hovered: bool) -> None:
        bg_id = self._connect_btn_bg_ids.get(index)
        if bg_id is None:
            return
        x, y, w, h = CL.setup_button_slots()[index]
        rw, rh = self._s(w), self._s(h)
        radius = self._s(L.MODE_BTN_RADIUS)
        photo = self._connect_btn_bg_photo(rw, rh, radius, hovered=hovered)
        if photo:
            self.canvas.itemconfig(bg_id, image=photo)

    def _draw_bottom_buttons(self) -> None:
        self._connect_btn_bg_ids.clear()
        font = gui_font(self.app.settings, self._s(13), "normal")
        for i, (label, (x, y, w, h)) in enumerate(zip(CL.setup_btn_labels(), CL.setup_button_slots())):
            rx, ry, rw, rh = self._s(x), self._s(y), self._s(w), self._s(h)
            radius = self._s(L.MODE_BTN_RADIUS)
            hit_tag = f"connect_hit_{i}"
            photo = self._connect_btn_bg_photo(rw, rh, radius, hovered=False)
            if photo:
                self._connect_btn_bg_ids[i] = self.canvas.create_image(
                    rx, ry, anchor="nw", image=photo,
                    tags=("connect_btn", f"connect_btn_{i}"),
                )
            self.canvas.create_text(
                rx + rw // 2, ry + rh // 2, text=label,
                fill=rgb_hex("text_primary"), anchor="center", font=font,
                tags=("connect_btn", f"connect_btn_txt_{i}"),
            )
            cmd = self.start_scan if i == 0 else (
                self._on_connect if i == 1 else self._open_manual_dialog
            )
            bind_clickable(
                self.canvas, rx, ry, rw, rh, cmd, tag=hit_tag,
            )
            self.canvas.tag_bind(hit_tag, "<Enter>", lambda _e, idx=i: self._set_connect_btn_hover(idx, True))
            self.canvas.tag_bind(hit_tag, "<Leave>", lambda _e, idx=i: self._set_connect_btn_hover(idx, False))

    def refresh_all(self) -> None:
        """Rebuild all translatable text; keep device list and scan state."""
        self.canvas.delete("connect_chrome")
        self.canvas.delete("connect_btn")
        self._connect_btn_bg_ids.clear()
        self._sprite_ids.clear()
        self._draw_chrome()
        self._draw_bottom_buttons()
        if self._scanning:
            self._set_status(t("setup.status_scanning"))
        elif self._devices:
            n = len(self._devices)
            if n == 1:
                self._set_status(t("setup.status_one_device"))
            else:
                self._set_status(t("setup.status_many_devices", count=n))
        else:
            self._set_status(t("setup.status_initial"))
        self._rebuild_device_list()

    def on_show(self, *, auto_scan: bool = False) -> None:
        self._show_bt_icon()
        current = self._current_device()
        if current is not None:
            self._devices = [current]
            self._selected = 0
            self._rebuild_device_list()
            self._set_status(t("setup.status_connected_only", name=current.name))
        if auto_scan:
            self.app.root.after(300, self.start_scan)

    def on_hide(self) -> None:
        self._stop_scan_ui()

    def start_scan(self) -> None:
        if self._scanning:
            return
        self._scanning = True
        # Keep the meter we are already linked to – it stops advertising, so a
        # scan alone would never list it.
        current = self._current_device()
        self._devices = [current] if current is not None else []
        self._selected = 0 if current is not None else -1
        self.canvas.delete("connect_row")
        self._rebuild_device_list()
        if current is not None:
            self._set_status(t("setup.status_connected_only", name=current.name))
        else:
            self._set_status(t("setup.status_scanning"))
        self._start_bt_pulse()
        threading.Thread(target=self._scan_worker, daemon=True).start()
        self._poll_scan_result()

    def _scan_worker(self) -> None:
        error: str | None = None
        devices: list[DM40Device] = []
        try:
            # Keep every device: the meter may advertise without a DM40 name
            # (already paired, or a custom name), and it must stay selectable.
            devices = scan_ble_devices_sync(timeout=12.0, include_unknown=True)
        except Exception as exc:
            error = str(exc)
        self._scan_queue.put((devices, error))

    def _poll_scan_result(self) -> None:
        if not self.winfo_exists():
            return
        try:
            devices, error = self._scan_queue.get_nowait()
        except queue.Empty:
            if self._scanning:
                self.app.root.after(100, self._poll_scan_result)
            return
        self._scan_done(devices, error)

    def _scan_done(self, devices: list[DM40Device], error: str | None) -> None:
        self._stop_scan_ui()
        current = self._current_device()
        if current is not None:
            rest = [d for d in devices if d.address.upper() != current.address.upper()]
            devices = [current] + rest
        self._devices = devices
        self._selected = 0 if devices else -1
        self._rebuild_device_list()
        known = [d for d in devices if d.known]
        if error:
            self._set_status(t("setup.status_scan_error", error=error))
        elif not devices:
            self._set_status(t("setup.status_no_device"))
        elif len(known) == 1:
            self._set_status(t("setup.status_one_device"))
        elif known:
            self._set_status(t("setup.status_many_devices", count=len(known)))
        else:
            self._set_status(t("setup.status_unknown_only", count=len(devices)))

    def _rebuild_device_list(self) -> None:
        self.canvas.delete("connect_row")
        if not self._devices:
            self.raise_click_layer()
            return

        font = gui_font(self.app.settings, self._s(CL.SETUP_ROW_FONT), "normal")
        x = CL.SETUP_LIST_MARGIN
        w = L.SCREEN_W - 2 * CL.SETUP_LIST_MARGIN
        y = CL.SETUP_LIST_TOP
        bottom = CL.setup_list_bottom()
        row_h = CL.SETUP_ROW_H + CL.SETUP_ROW_GAP

        for i, dev in enumerate(self._devices):
            if y + CL.SETUP_ROW_H > bottom:
                break
            active = i == self._selected
            rx, ry, rw, rh = self._s(x), self._s(y), self._s(w), self._s(CL.SETUP_ROW_H)
            bg = "buttons_active" if active else "range_buttons"
            self.canvas.create_rectangle(
                rx, ry, rx + rw, ry + rh,
                fill=rgb_hex(bg), outline="", tags=("connect_row", f"connect_row_{i}"),
            )
            label = dev.list_label()
            fill = "text_primary"
            if dev.connected:
                label = f"{label}   ·   {t('setup.connected_suffix')}"
                # selected row is blue – keep the text readable
                fill = "text_primary" if active else "buttons_active"
            elif not dev.known:
                label = f"{label}   ·   {t('setup.unknown_suffix')}"
                fill = "text_secondary"
            self.canvas.create_text(
                rx + self._s(CL.SETUP_ROW_PAD_LEFT), ry + rh // 2,
                text=label, anchor="w", font=font,
                fill=rgb_hex(fill), tags=("connect_row", f"connect_txt_{i}"),
            )
            bind_clickable(
                self.canvas, rx, ry, rw, rh,
                lambda idx=i: self._select_device(idx), tag=f"connect_row_hit_{i}",
            )
            y += row_h

        self.raise_click_layer()

    def _select_device(self, index: int) -> None:
        if index < 0 or index >= len(self._devices):
            return
        self._selected = index
        self._rebuild_device_list()

    def _on_connect(self) -> None:
        if self._selected < 0 or self._selected >= len(self._devices):
            self._set_status(t("setup.status_select_first"))
            return
        self._connect_to(self._devices[self._selected])

    def _connect_to(self, device: DM40Device) -> None:
        """Connect, falling back to the current model for unnamed devices."""
        if not device.known or not device.model_name:
            device = DM40Device(
                address=device.address,
                name=device.name or device.address,
                model_name=self.app.settings.get("model_name") or "DM40C",
                device_counts=int(self.app.settings.get("device_counts") or 60000),
                known=False,
            )
        self.app.complete_device_setup(device)

    def _open_manual_dialog(self) -> None:
        """Type a Bluetooth address by hand (when it never shows up in a scan)."""
        from gui.manual_connect import ManualConnectDialog

        dialog = ManualConnectDialog(self.app, str(self.app.settings.get("target_mac") or ""))
        self.app.root.wait_window(dialog)
        if dialog.result:
            self._connect_to(DM40Device(
                address=dialog.result, name=dialog.result,
                model_name="", device_counts=0, known=False,
            ))
