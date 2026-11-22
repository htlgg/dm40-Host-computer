"""Tk smoke test for the keyboard shortcuts —no meter, no Bluetooth needed.

Stubs out bleak and the BLE worker, builds the real window, then fires key
events and checks which commands the app would send, including remapping a key
on the HOTKEYS screen:

    python tests/smoke_gui.py

Needs a desktop session (Tk opens a toplevel window).
"""

from __future__ import annotations

import sys
import time
import types
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# --- stub bleak before the app imports it -----------------------------
def _install_bleak_stub() -> None:
    if "bleak" in sys.modules:
        return
    bleak = types.ModuleType("bleak")

    class BleakClient:  # pragma: no cover - never used in this test
        def __init__(self, *args, **kwargs) -> None:
            raise RuntimeError("BLE is stubbed out in tests")

    class BleakScanner:  # pragma: no cover - never used in this test
        @staticmethod
        async def discover(*args, **kwargs):
            return []

    bleak.BleakClient = BleakClient
    bleak.BleakScanner = BleakScanner
    sys.modules["bleak"] = bleak


_install_bleak_stub()

import tkinter as tk  # noqa: E402

from ble.worker import BleWorker  # noqa: E402
from core.config import UI_STATE_PATH  # noqa: E402
from core.parsing import Measurement, apply_model  # noqa: E402
from gui import app_window  # noqa: E402
from gui import hotkey_layout  # noqa: E402
from gui.theme import rgb_hex  # noqa: E402
from gui import hotkeys as hotkeys_module  # noqa: E402
from gui import hotkeys_screen as hotkeys_screen_module  # noqa: E402
from gui import layout as gui_layout  # noqa: E402
from gui import settings_layout  # noqa: E402
from gui.hotkeys import (  # noqa: E402
    ACTION_ORDER,
    DEFAULT_HOTKEY_MAP,
    format_key_name,
    is_chord_capable,
    key_sequences,
    normalize_map,
    normalize_step,
    parse_sequence_steps,
    sequence_from_event,
)
from gui.settings import DEFAULTS  # noqa: E402

# Keep the repo clean: the app would otherwise write settings.json next to it.
_saved: list[dict] = []


def _fake_save_settings(settings: dict) -> bool:
    _saved.append(dict(settings))
    return True


hotkeys_module.save_settings = _fake_save_settings
hotkeys_screen_module.save_settings = _fake_save_settings
app_window.save_settings = _fake_save_settings
# Synthetic events carry no real key state: use the event.state fallback.
hotkeys_module._os_modifiers = lambda: None
# The chord timer must not fire in the middle of a test run —the timeout path
# is driven explicitly via _capture_timeout().
hotkey_layout.CHORD_CAPTURE_MS = 600_000

_checks = 0
_failures: list[str] = []


def check(label: str, actual, expected) -> None:
    global _checks
    _checks += 1
    if actual != expected:
        _failures.append(f"{label}: expected {expected!r}, got {actual!r}")


def check_true(label: str, value, detail: str = "") -> None:
    global _checks
    _checks += 1
    if not value:
        _failures.append(f"{label}: expected truthy, got {value!r} {detail}")


class FakeBle:
    """Records what the app tries to send."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, object]] = []
        self._callbacks = types.SimpleNamespace(on_raw_traffic=None)

    @property
    def connected(self) -> bool:
        return True

    def send_range_flag(self, flag: int) -> None:
        self.sent.append(("range", flag))

    def send_packet(self, packet: bytes) -> None:
        self.sent.append(("packet", bytes(packet)))

    def send_command(self, payload: list[int]) -> None:
        self.sent.append(("cmd", bytes(payload)))


def build_app() -> tuple[tk.Tk, "app_window.DM40App"]:
    # Pretend a meter is paired so the app boots straight to the main screen.
    app_window.load_settings = lambda: {
        **DEFAULTS,
        "target_mac": "AA:BB:CC:DD:EE:FF",
        "model_name": "DM40C",
        "device_counts": 60000,
        "language": "en-US",
    }
    BleWorker.start = lambda self: None  # no BLE thread

    # The window must stay mapped: the app fits its toplevel from real Tk geometry.
    root = tk.Tk()
    app = app_window.DM40App(root)
    apply_model("DM40C", 60000)
    app.ble = FakeBle()
    root.update()
    return root, app


def test_pure_helpers() -> None:
    check("normalize default", normalize_map(None)["range_next"], "Tab")
    check("normalize override", normalize_map({"range_next": "F5"})["range_next"], "F5")
    check("normalize drops unknown", "bogus" in normalize_map({"bogus": "x"}), False)
    check("normalize drops non-str", normalize_map({"range_next": 5})["range_next"], "Tab")
    check("sequences for letter", key_sequences("a"), ["a", "A"])
    check("sequences for digit", key_sequences("4"), ["KeyPress-4"])
    check("sequences for tab", key_sequences("Tab"), ["Tab"])
    check("sequences for prev", key_sequences("Shift-Tab"), ["Shift-Tab", "ISO_Left_Tab"])
    check("sequences for empty", key_sequences(""), [])
    check("format tab", format_key_name("Tab"), "Tab")
    check("format shift+tab", format_key_name("Shift-Tab"), "Shift+Tab")
    check("format ctrl+letter", format_key_name("Control-a"), "Ctrl+A")
    check("format ctrl+shift", format_key_name("Control-Shift-S"), "Ctrl+Shift+S")
    check("format escape", format_key_name("Escape"), "Esc")
    check("format f5", format_key_name("F5"), "F5")
    check("format empty", format_key_name(""), "")
    check("parse single key", parse_sequence_steps("Tab"), ["Tab"])
    check("parse chord", parse_sequence_steps("0 1"), ["0", "1"])
    check("format chord", format_key_name("0 1"), "0 → 1")
    check("format chord with modifier", format_key_name("Control-k 1"), "Ctrl+K → 1")
    check("digit can start a chord", is_chord_capable("0"), True)
    check("letter can start a chord", is_chord_capable("k"), True)
    check("F-key cannot start a chord", is_chord_capable("F7"), False)
    check("modifier combo cannot start a chord", is_chord_capable("Control-1"), False)
    check("punctuation display", format_key_name("period 1"), ". → 1")
    check("punctuation can start a chord", is_chord_capable("period"), True)
    # Tk binds punctuation by keysym name, not by character.
    check("minus binds by name", key_sequences("-"), ["minus"])
    check("plus binds by name", key_sequences("+"), ["plus"])
    check("period binds by name", key_sequences("."), ["period"])
    check("normalize minus", normalize_step("-"), "minus")
    check("normalize ctrl+plus", normalize_step("Control-+"), "Control-plus")
    check("minus display", format_key_name("-"), "-")
    check("minus can start a chord", is_chord_capable("-"), True)
    check("shift+tab still binds", key_sequences("Shift-Tab"), ["Shift-Tab", "ISO_Left_Tab"])

    check("event F5", sequence_from_event(SimpleNamespace(keysym="F5", state=0)), "F5")
    check("event ctrl+s", sequence_from_event(SimpleNamespace(keysym="s", state=0x4)), "Control-s")
    check(
        "event ctrl+shift+s",
        sequence_from_event(SimpleNamespace(keysym="S", state=0x4 | 0x1)),
        "Control-S",
    )
    check(
        "event modifier only",
        sequence_from_event(SimpleNamespace(keysym="Shift_L", state=0x1)),
        None,
    )
    check(
        "event shift+tab",
        sequence_from_event(SimpleNamespace(keysym="Tab", state=0x1)),
        "Shift-Tab",
    )
    check(
        "event alt+f1",
        sequence_from_event(SimpleNamespace(keysym="F1", state=0x8)),
        "Alt-F1",
    )


def main() -> int:
    ui_state_existed = UI_STATE_PATH.exists()
    test_pure_helpers()
    root, app = build_app()
    try:
        run_checks(root, app)
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass
        if not ui_state_existed and UI_STATE_PATH.exists():
            UI_STATE_PATH.unlink(missing_ok=True)

    if _failures:
        print(f"FAILED - {len(_failures)} of {_checks} checks:")
        for line in _failures:
            print(f"  - {line}")
        return 1
    print(f"OK - {_checks} GUI hotkey checks passed")
    return 0


def run_checks(root: tk.Tk, app) -> None:
    sent = app.ble.sent

    def tap(sequence: str, **kw) -> None:
        # Tk drops key events when the toplevel lost the focus.
        root.focus_force()
        root.event_generate(sequence, **kw)
        root.update()

    def press(sequence: str) -> list[tuple[str, object]]:
        sent.clear()
        tap(sequence)
        return list(sent)

    def reset_range_state() -> None:
        app.settings["hotkeys"] = True
        app.mode_state.last_kind = "VDC"
        app.mode_state.active_group = "VDC"
        app._last_range_flag = 0x00

    # Bindings are registered on the toplevel (so no widget needs focus).
    for sequence in ("<Tab>", "<Shift-Tab>", "<KeyPress-r>", "<Escape>", "<F1>"):
        check_true(f"binding {sequence}", bool(root.bind(sequence)), f"got {root.bind(sequence)!r}")

    # --- range cycling ------------------------------------------------
    reset_range_state()
    check("Tab from 600mV", press("<KeyPress-Tab>"), [("range", 0x08)])
    check("label after Tab", app.main_screen._last_range_label, "6V")
    check("Shift+Tab back", press("<Shift-Tab>"), [("range", 0x00)])
    check("label after Shift+Tab", app.main_screen._last_range_label, "600mV")

    # --- direct range selection ---------------------------------------
    # These shortcuts are hidden by default, so switch them on for the test.
    for _n in (1, 4):
        app.hotkeys.set_action_enabled(f"range_index_{_n}", True)
    app._last_range_flag = 0x00
    check("key 4 → 600V", press("<KeyPress-4>"), [("range", 0x18)])
    check("label after key 4", app.main_screen._last_range_label, "600V")

    app._last_range_flag = 0x18
    check("key 1 → 600mV", press("<KeyPress-1>"), [("range", 0x00)])
    check("key 9 is a no-op", press("<KeyPress-9>"), [])

    # --- AUTO / AUTO+ ---------------------------------------------------
    app._last_range_flag = 0x00
    check("key a → AUTO", press("<KeyPress-a>"), [("range", 0x28)])
    check("label AUTO", app.main_screen._last_range_label, "AUTO")
    check("key p → AUTO+", press("<KeyPress-p>"), [("range", 0x30)])
    check("label AUTO+", app.main_screen._last_range_label, "AUTO+")

    # --- save-reading shortcut -------------------------------------------
    app.show_main_screen()
    reset_range_state()
    check("save reading binds to F7 by default", app.hotkeys.map["save_reading"], "F7")

    m = Measurement()
    m.kind, m.value_str, m.decimals, m.display_unit = "VDC", "1.2345", 4, "V"
    app.main_screen._bt_off_display = False
    app.main_screen._last_display_measurement = (m, "")
    app.main_screen._save_slots.clear_all()

    press("<F7>")
    slots = [s.text for s in app.main_screen._save_slots.slots if s.text.strip()]
    check("F7 stores one reading", len(slots), 1)

    press("<F7>")
    slots = [s.text for s in app.main_screen._save_slots.slots if s.text.strip()]
    check("second F7 stores another slot", len(slots), 2)

    # Ten slots, filled row by row.
    check("ten save slots", len(app.main_screen._save_slots.slots), 10)
    check("ten slot rectangles", len(gui_layout.save_slot_slots()), 10)
    app.main_screen._save_slots.clear_all()
    for _ in range(10):
        press("<F7>")
    slots = [s.text for s in app.main_screen._save_slots.slots if s.text.strip()]
    check("all ten slots fill up", len(slots), 10)

    # Clear with the shortcut.
    check("clear binds to F9 by default", app.hotkeys.map["clear_readings"], "F9")
    press("<F9>")
    slots = [s.text for s in app.main_screen._save_slots.slots if s.text.strip()]
    check("F9 clears every slot", len(slots), 0)

    # Clear with the top-bar button.
    press("<F7>")
    press("<F7>")
    canvas = app.main_screen.canvas
    check_true("clear button hotspot exists", bool(canvas.find_withtag("hit_clear")))
    canvas.event_generate("<Button-1>", x=246, y=19)
    root.update()
    slots = [s.text for s in app.main_screen._save_slots.slots if s.text.strip()]
    check("clear button wipes the slots", len(slots), 0)

    app.show_settings_screen()
    press("<F7>")
    slots = [s.text for s in app.main_screen._save_slots.slots if s.text.strip()]
    check("no saving outside the main screen", len(slots), 0)
    app.main_screen._save_slots.clear_all()
    app.show_main_screen()

    # --- RUN / HOLD shortcut ---------------------------------------------
    app.show_main_screen()
    reset_range_state()
    check("hold binds to F8 by default", app.hotkeys.map["hold"], "F8")
    app.main_screen._last_hold = None
    sent.clear()
    tap("<F8>")
    check("F8 sends HOLD", [kind for kind, _ in sent], ["cmd"])
    check("held after the first press", app.main_screen._last_hold, True)
    sent.clear()
    tap("<F8>")
    check("second F8 sends RUN", [kind for kind, _ in sent], ["cmd"])
    check("running after the second press", app.main_screen._last_hold, False)

    # --- modes without ranges are safe no-ops ---------------------------
    app.mode_state.last_kind = "CAP"
    app.mode_state.active_group = None
    check("CAP has no ranges", press("<KeyPress-Tab>"), [])
    check("CAP ignores digits", press("<KeyPress-2>"), [])

    # --- F-keys cycle the MODE groups -----------------------------------
    reset_range_state()
    app.mode_state.active_group = None
    sent.clear()
    tap("<F2>")
    check("F2 activates ADC group", app.mode_state.active_group, "ADC")
    check_true("F2 sends a mode command", any(kind == "packet" for kind, _ in sent), f"sent={sent}")

    # --- Esc returns from other screens ---------------------------------
    app.show_settings_screen()
    check("settings screen active", app._current_screen, "settings")
    check("Esc handled", press("<Escape>"), [])
    check("Esc went back to main", app._current_screen, "main")

    app.show_connect_screen()
    check("connect screen active", app._current_screen, "connect")
    press("<Escape>")
    check("Esc does not leave the connect screen", app._current_screen, "connect")
    app.show_main_screen()

    # --- text widgets keep their keys -----------------------------------
    class _FakeTextField:
        def winfo_class(self) -> str:
            return "Text"

    real_focus_get = root.focus_get
    root.focus_get = lambda: _FakeTextField()
    reset_range_state()
    check("typing in a text field is not hijacked", press("<KeyPress-2>"), [])
    root.focus_get = real_focus_get
    root.update()

    # --- the Settings toggle disables everything ------------------------
    reset_range_state()
    app.settings["hotkeys"] = False
    check("hotkeys OFF → Tab ignored", press("<KeyPress-Tab>"), [])
    app.settings["hotkeys"] = True
    check("hotkeys ON → Tab works again", press("<KeyPress-Tab>"), [("range", 0x08)])

    # --- RANGE screen click still works and returns to the main screen ---
    app.show_range_screen()
    check("range screen active", app._current_screen, "range")
    sent.clear()
    app.range_screen._pick(0x20)
    root.update()
    check("range pick sends flag", sent, [("range", 0x20)])
    check("range pick returns to main", app._current_screen, "main")

    # --- hotkeys also work while the RANGE screen is open -----------------
    reset_range_state()
    app.show_range_screen()
    check("range hotkey sends flag", press("<KeyPress-Tab>"), [("range", 0x08)])
    check("range hotkey keeps RANGE screen", app._current_screen, "range")
    check("range screen highlight follows", app.range_screen._active_flag, 0x08)
    app.show_main_screen()

    # --- HOTKEYS screen: remap, swap, clear, reset ------------------------
    app.show_settings_screen()
    app.show_hotkeys_screen()
    check("hotkeys screen active", app._current_screen, "hotkeys")
    check_true(
        "action list is longer than one screen",
        app.hotkeys_screen._max_first_row() > 0,
        f"max_first_row={app.hotkeys_screen._max_first_row()}",
    )

    reset_range_state()
    app.hotkeys_screen.begin_capture("range_next")
    check("capture armed", app.hotkeys.capturing, True)
    tap("<KeyPress-F10>")
    check("capture stored F10", app.hotkeys.map["range_next"], "F10")
    check_true(
        "rebind is confirmed on screen",
        "F10" in app.hotkeys_screen._note,
        f"note={app.hotkeys_screen._note!r}",
    )
    check("capture released", app.hotkeys.capturing, False)
    check("only the diff is persisted", app.settings.get("hotkey_map"), {"range_next": "F10"})
    check_true("settings were saved", bool(_saved), f"saved={_saved}")

    app.show_main_screen()
    reset_range_state()
    check("old key is dead", press("<KeyPress-Tab>"), [])
    check("new key cycles", press("<KeyPress-F10>"), [("range", 0x08)])

    # A key that has no binding at all is captured through the generic hook.
    app.show_hotkeys_screen()
    app.hotkeys_screen.begin_capture("range_auto_plus")
    tap("<KeyPress-k>")
    app.hotkeys_screen._capture_timeout()   # plain keys wait for a chord partner
    root.update()
    check("unbound key captured", app.hotkeys.map["range_auto_plus"], "k")

    # Colliding with an existing binding swaps the two instead of dropping one.
    swapped = app.hotkeys.set_key("range_prev", "F1")
    check("conflict reports the swap", swapped, "mode_1")
    check(
        "both keys survive the swap",
        (app.hotkeys.map["range_prev"], app.hotkeys.map["mode_1"]),
        ("F1", "Shift-Tab"),
    )

    # Delete clears a binding.
    app.hotkeys_screen.begin_capture("range_auto")
    tap("<KeyPress-Delete>")
    check("Delete unbinds", app.hotkeys.map["range_auto"], "")
    app.show_main_screen()
    reset_range_state()
    check("unbound key does nothing", press("<KeyPress-a>"), [])

    # Esc cancels a capture without changing anything.
    app.show_hotkeys_screen()
    app.hotkeys_screen.begin_capture("range_auto")
    tap("<Escape>")
    check("Esc cancels the capture", app.hotkeys.capturing, False)
    check("cancelled capture kept the map", app.hotkeys.map["range_auto"], "")

    # Restore defaults.
    app.hotkeys_screen._reset_defaults()
    check("reset restores every default", app.hotkeys.map, dict(DEFAULT_HOTKEY_MAP))
    check("reset clears the overrides", app.settings.get("hotkey_map"), {})
    app.show_main_screen()
    reset_range_state()
    check("Tab works again after reset", press("<KeyPress-Tab>"), [("range", 0x08)])

    # Esc leaves the HOTKEYS screen back to Settings.
    app.show_hotkeys_screen()
    press("<Escape>")
    check("Esc leaves the hotkeys screen", app._current_screen, "settings")

    # Scrolling.
    app.show_hotkeys_screen()
    app.hotkeys_screen._first_row = 0
    app.hotkeys_screen._scroll(3)
    check_true("scrolling moves the list", app.hotkeys_screen._first_row > 0)
    app.hotkeys_screen._first_row = 0
    app.hotkeys_screen._draw_rows()
    app.show_main_screen()

    # --- language refresh rebuilds every screen (incl. the HOTKEYS one) ----
    app._refresh_all_screens_i18n()
    check("i18n refresh keeps the app alive", app._current_screen, "main")
    app.show_hotkeys_screen()
    check_true(
        "hotkeys screen redraws after refresh",
        bool(app.hotkeys_screen.canvas.find_all()),
        "empty canvas",
    )
    app.show_main_screen()

    # --- per-action switch: off frees the key and hides the row -----------
    app.show_hotkeys_screen()
    root.update()
    hk = app.hotkeys
    hk_screen = app.hotkeys_screen
    check("all actions on by default", hk.enabled_actions(), list(ACTION_ORDER))

    hk.set_action_enabled("range_next", False)
    check("switch is persisted", app.settings.get("hotkey_disabled"), ["range_next"])
    check("disabled action leaves the list", "range_next" in hk.enabled_actions(), False)
    check("disabled action is not visible", hk_screen.visible_actions().count("range_next"), 0)
    check("switching off clears the key", hk.map["range_next"], "")

    app.show_main_screen()
    reset_range_state()
    check("disabled key does nothing", press("<KeyPress-Tab>"), [])

    # Reveal it, then switch it back on by clicking the row's left switch.
    app.show_hotkeys_screen()
    root.update()
    hk_screen._toggle_show_disabled()
    root.update()
    check("revealed on request", hk_screen.visible_actions().count("range_next"), 1)

    hk_screen._first_row = hk_screen._max_first_row()
    hk_screen._draw_rows()
    root.update()
    actions = hk_screen.visible_actions()
    row_on_screen = len(actions) - 1 - hk_screen._first_row
    step = hotkey_layout.ROW_H + hotkey_layout.ROW_GAP
    switch_y = hotkey_layout.VIEW_TOP + row_on_screen * step + hotkey_layout.ROW_H // 2
    hk_screen.canvas.event_generate("<Button-1>", x=20, y=switch_y)
    root.update()
    check("switch click re-enables", app.settings.get("hotkey_disabled"), [])
    check("switch click does not arm capture", hk.capturing, False)
    check("re-enabled row has no key", hk.map["range_next"], "")

    app.show_main_screen()
    reset_range_state()
    check("cleared key stays unused", press("<KeyPress-Tab>"), [])

    # Reset also clears the per-action switches.
    app.show_hotkeys_screen()
    hk.set_action_enabled("back", False)
    hk_screen._reset_defaults()
    check("reset re-enables everything", app.settings.get("hotkey_disabled"), [])
    check("all actions back after reset", hk.enabled_actions(), list(ACTION_ORDER))
    app.show_main_screen()

    # --- chord shortcuts: press 0 then 1 --------------------------------
    app.show_hotkeys_screen()
    root.update()
    hk_screen = app.hotkeys_screen
    reset_range_state()

    hk_screen.begin_capture("mode_1")
    tap("<KeyPress-0>")
    tap("<KeyPress-1>")
    check("two keys make a chord", app.hotkeys.map["mode_1"], "0 1")
    check("capture released after the chord", hk.capturing, False)

    app.show_main_screen()
    reset_range_state()
    app.mode_state.active_group = None
    sent.clear()
    tap("<KeyPress-0>")
    check("first key alone does nothing", list(sent), [])
    check("chord waits for the second key", hk._chord_action, "mode_1")
    tap("<KeyPress-1>")
    check("second key runs the action", app.mode_state.active_group, "VDC")
    check("chord cleared after firing", hk._chord_action, None)
    check_true("chord sends one command", len(sent) == 1, f"sent={sent}")

    # Enter commits a single key without waiting for the timeout.
    app.show_hotkeys_screen()
    hk_screen.begin_capture("mode_1")
    tap("<KeyPress-0>")
    tap("<Return>")
    check("Enter keeps a single key", app.hotkeys.map["mode_1"], "0")

    # The capture timeout keeps the first key on its own.
    hk_screen.begin_capture("mode_1")
    tap("<KeyPress-2>")
    hk_screen._capture_timeout()
    root.update()
    check("timeout keeps a single key", app.hotkeys.map["mode_1"], "2")
    check("capture ended after the timeout", hk.capturing, False)

    hk_screen._reset_defaults()
    app.show_main_screen()

    # --- punctuation keys really fire (numpad "-", "+", ".") --------------
    app.show_hotkeys_screen()
    root.update()
    hk_screen.begin_capture("range_prev")
    tap("<KeyPress>", keysym="-")
    hk_screen._capture_timeout()
    root.update()
    check("minus captured", app.hotkeys.map["range_prev"], "-")

    app.show_main_screen()
    reset_range_state()
    app._last_range_flag = 0x08
    check("minus key fires", press("<minus>"), [("range", 0x00)])

    app.show_hotkeys_screen()
    hk_screen._reset_defaults()
    app.show_main_screen()

    # --- background (system-wide) hotkeys --------------------------------
    from gui.global_hotkeys import KBDLLHOOKSTRUCT

    def vk_seq(vk_code: int, scan: int) -> str:
        """Translate a virtual key exactly like the low-level hook does."""
        kb = KBDLLHOOKSTRUCT()
        kb.vkCode, kb.scanCode = vk_code, scan
        return app.global_hotkeys._sequence_for(kb)

    check("digit translation", vk_seq(0x31, 2), "1")
    check("letter translation", vk_seq(0x53, 31), "s")
    check("F-key translation", vk_seq(0x70, 59), "F1")
    check("symbol translation", vk_seq(0xBD, 12), "minus")
    check("Tab translation", vk_seq(0x09, 15), "Tab")
    # shifted symbols must not keep a "Shift-" prefix, otherwise a shortcut
    # stored as "*" / "+" would never match in the background hook
    from gui.global_hotkeys import GlobalHotkeys as _GH
    check("Shift+8 → asterisk", _GH._compose(False, False, True, "*"), "asterisk")
    check("Shift+= → plus", _GH._compose(False, False, True, "+"), "plus")
    check("plain - stays minus", _GH._compose(False, False, False, "-"), "minus")
    check("Ctrl+Shift+= keeps Ctrl", _GH._compose(True, False, True, "+"), "Control-plus")

    # Keys typed while our own window is focused must not enter the queue –
    # otherwise they get replayed later (the stray F11 toggle / extra beep).
    import ctypes as _ct

    service = app.global_hotkeys
    kb = KBDLLHOOKSTRUCT()
    kb.vkCode, kb.scanCode = 0x31, 2
    kb_ptr = _ct.cast(_ct.pointer(kb), _ct.c_void_p)
    service._queue.queue.clear()
    service._foreground_is_ours = lambda: True
    service._on_key(0, 0x0100, kb_ptr.value)
    check("focused key is not queued", service._queue.qsize(), 0)
    service._foreground_is_ours = lambda: False
    check_true("'1' counts as a bound shortcut",
               service.app.hotkeys.sequence_is_bound("1"), "1")
    _prev_global = app.settings.get("global_hotkeys", False)

    service._queue.queue.clear()
    app.settings["global_hotkeys"] = True
    service._foreground_is_shell = lambda: True
    result = int(service._on_key(0, 0x0100, kb_ptr.value))
    check("bound key is queued in background mode", service._queue.qsize(), 1)
    check("bound key is swallowed on the desktop", result, 1)

    service._queue.queue.clear()
    service._foreground_is_shell = lambda: False
    result = int(service._on_key(0, 0x0100, kb_ptr.value))
    check_true("bound key still reaches a real app", result != 1,
               f"hook returned {result}")

    service._queue.queue.clear()
    app.settings["global_hotkeys"] = False
    service._foreground_is_shell = lambda: True
    result = int(service._on_key(0, 0x0100, kb_ptr.value))
    check("desktop stays silent with background mode off", result, 1)

    service._queue.queue.clear()
    service._foreground_is_shell = lambda: False
    result = int(service._on_key(0, 0x0100, kb_ptr.value))
    check_true("key passes through when background mode is off", result != 1,
               f"hook returned {result}")

    kb2 = KBDLLHOOKSTRUCT()
    kb2.vkCode, kb2.scanCode = 0x5A, 44          # "z"
    kb2_ptr = _ct.cast(_ct.pointer(kb2), _ct.c_void_p)
    service._queue.queue.clear()
    app.settings["global_hotkeys"] = True
    result = int(service._on_key(0, 0x0100, kb2_ptr.value))
    check("unbound key is queued", service._queue.qsize(), 1)
    check_true("unbound key is never swallowed", result != 1, f"hook returned {result}")
    app.settings["global_hotkeys"] = _prev_global
    service._queue.queue.clear()

    check("background mode is off by default", app.settings.get("global_hotkeys"), False)
    app.hotkeys.run_action("toggle_global")
    check("toggle turns background mode on", app.settings.get("global_hotkeys"), True)
    app.hotkeys.run_action("toggle_global")
    check("toggle turns background mode off", app.settings.get("global_hotkeys"), False)

    # Every bound key works in the background – plain symbols included.
    app.hotkeys.set_key("save_reading", ".")
    app.show_main_screen()
    app.main_screen._save_slots.clear_all()
    app.main_screen._last_display_measurement = (m, "")
    app.main_screen._bt_off_display = False

    check("background is silent while off", app.hotkeys.dispatch_sequence("."), False)
    slots = [s.text for s in app.main_screen._save_slots.slots if s.text.strip()]
    check("nothing saved while off", len(slots), 0)

    app.settings["global_hotkeys"] = True
    check("background dispatch accepts '.'", app.hotkeys.dispatch_sequence("."), True)
    slots = [s.text for s in app.main_screen._save_slots.slots if s.text.strip()]
    check("plain symbol saves in background", len(slots), 1)
    app.main_screen._save_slots.clear_all()

    # A digit bound to a mode group also fires in the background.
    app.hotkeys.set_action_enabled("range_index_1", False)
    app.hotkeys.set_key("mode_1", "1")
    app.mode_state.active_group = None
    app.hotkeys.dispatch_sequence("1")
    check("digit works in background", app.mode_state.active_group, "VDC")
    app.hotkeys.set_key("mode_1", "F1")
    app.hotkeys.set_action_enabled("range_index_1", True)

    # Chords work in the background too.
    app.hotkeys.set_key("mode_2", "0 1")
    app.hotkeys.dispatch_sequence("0")
    check("chord waits for its second key", app.hotkeys._chord_action, "mode_2")
    app.mode_state.active_group = "VDC"
    app.hotkeys.dispatch_sequence("1")
    check("chord fires in background", app.mode_state.active_group, "ADC")
    app.mode_state.active_group = None

    # Disabled rows stay silent.
    app.hotkeys.set_action_enabled("save_reading", False)
    check("disabled row is silent", app.hotkeys.dispatch_sequence("."), False)
    app.hotkeys.set_action_enabled("save_reading", True)

    # The on/off key keeps working while the mode is off.
    app.settings["global_hotkeys"] = False
    app.hotkeys.set_key("toggle_global", "F11")
    check("toggle key works while off", app.hotkeys.dispatch_sequence("F11"), True)
    check("toggle key turned it on", app.settings.get("global_hotkeys"), True)
    app.hotkeys.dispatch_sequence("F11")
    check("toggle key turned it off", app.settings.get("global_hotkeys"), False)

    app.hotkeys.set_key("save_reading", "F7")
    app.hotkeys.set_key("mode_2", "F2")
    app.main_screen._save_slots.clear_all()
    app.show_main_screen()

    # --- mini mode layout -------------------------------------------------
    app.main_screen._save_slots.clear_all()
    app.settings["mini_app"] = True
    app.show_main_screen()
    root.update()
    ms = app.main_screen
    check("mini window height", int(gui_layout.MINI_SCREEN_H), 188)
    digits = ms.canvas.bbox(ms._text_ids["value_digits"])
    mode_boxes = [
        ms.canvas.bbox(item) for item in ms.canvas.find_withtag("mode_btn")
        if ms.canvas.type(item) == "image"
    ]
    mode_boxes = [box for box in mode_boxes if box]
    check_true("mode row exists in mini mode", bool(mode_boxes))
    check_true(
        "digits do not overlap the MODE row",
        digits[3] <= min(box[1] for box in mode_boxes),
        f"digits={digits} mode_top={min(box[1] for box in mode_boxes)}",
    )

    for _ in range(3):
        ms.save_reading()
    root.update()
    ghosts = [
        item for item in ms.canvas.find_all()
        if ms.canvas.type(item) == "image"
        and "save_slot" in ms.canvas.gettags(item)
        and ms.canvas.itemcget(item, "state") != "hidden"
    ]
    check("no ghost slot sprites in mini mode", len(ghosts), 0)

    app.settings["mini_app"] = False
    app.show_main_screen()
    root.update()
    check("full window height", int(gui_layout.SCREEN_H), 300)
    app.main_screen._save_slots.clear_all()

    # --- graph scale labels sit on an opaque plate ------------------------
    from core.parsing import Measurement as _Measurement

    sample = _Measurement()
    sample.kind = "VDC"
    sample.value_str = "3.2000"
    sample.decimals = 4
    sample.display_unit = "V"
    sample.norm_value = 3.2
    sample.vertical_pad = 0.05
    app.main_screen.update_measurement(sample, "6V")
    for _ in range(6):
        root.update()
        time.sleep(0.06)

    graph = app.main_screen._graph
    canvas = app.main_screen.canvas
    for name, text_id in graph._scale_ids.items():
        check(f"{name} scale label is white", canvas.itemcget(text_id, "fill"),
              rgb_hex("text_primary"))
        plate = graph._scale_bg["column"]
        box = canvas.bbox(plate)
        check_true(
            f"{name} label plate starts at the plot edge",
            box is not None and box[0] <= graph._plot_px[0] + 1,
            f"plate={box} plot_left={graph._plot_px[0]}",
        )
        check_true(
            f"{name} label is above its plate",
            list(canvas.find_all()).index(plate) < list(canvas.find_all()).index(text_id),
            "stacking",
        )

    # --- relative toggle shortcut -----------------------------------------
    was_rel = graph._relative_active
    check("relative-hotkey action exists", "toggle_rel" in hotkeys_module.ACTION_ORDER, True)
    app.hotkeys.run_action("toggle_rel")
    root.update()
    check("relative hotkey turns it on", graph._relative_active, not was_rel)
    app.hotkeys.run_action("toggle_rel")
    root.update()
    check("relative hotkey turns it off again", graph._relative_active, was_rel)

    # --- back button / row clicks (tag-collision regression) --------------
    app.show_hotkeys_screen()
    root.update()
    canvas = app.hotkeys_screen.canvas
    canvas.event_generate("<Button-1>", x=20, y=15)
    root.update()
    check("back button leaves the hotkeys screen", app._current_screen, "settings")

    app.show_hotkeys_screen()
    root.update()
    canvas = app.hotkeys_screen.canvas
    canvas.event_generate("<Button-1>", x=200, y=hotkey_layout.VIEW_TOP + 12)
    root.update()
    check("row click arms a capture", app.hotkeys.capturing, True)
    check("row click armed the first row", app.hotkeys_screen._capture_action, "range_next")
    app.hotkeys_screen.cancel_capture()
    app.show_main_screen()

    # --- window scaling ---------------------------------------------------
    app.settings["mini_app"] = False
    app.show_main_screen()
    root.update()
    base_scale = app.scale
    root.geometry("960x600")
    for _ in range(60):
        root.update()
        time.sleep(0.02)
    check_true("resizing rescales the UI", app.scale > base_scale + 0.2,
               f"{base_scale} -> {app.scale}")
    check("canvas follows the scale",
          (app.main_screen.canvas.winfo_width(), app.main_screen.canvas.winfo_height()),
          (int(gui_layout.SCREEN_W * app.scale), int(gui_layout.SCREEN_H * app.scale)))
    check_true("measurement survived the rebuild",
               bool(app.main_screen._last_display_measurement))

    root.geometry("480x300")
    for _ in range(60):
        root.update()
        time.sleep(0.02)
    check_true("shrinking restores the scale", abs(app.scale - base_scale) < 0.2,
               f"scale={app.scale}")

    # --- the extra Settings row still fits on screen -----------------------
    last_y = settings_layout.settings_row_slots()[-1][1]
    check_true(
        "settings rows fit the window",
        last_y + settings_layout.SETTINGS_ROW_H <= app_window.display_layout.SCREEN_H,
        f"last row bottom={last_y + settings_layout.SETTINGS_ROW_H}",
    )
    check("action list covers every key", len(ACTION_ORDER), len(DEFAULT_HOTKEY_MAP))


if __name__ == "__main__":
    raise SystemExit(main())

