"""Window-level keyboard shortcuts: default map, remapping and dispatch.

Keys are handled by the toplevel window, so no widget needs focus. Every action
can be rebound from the HOTKEYS screen (Settings → Keyboard shortcuts) and is
stored in ``settings.json`` under ``hotkey_map`` (only the entries that differ
from :data:`DEFAULT_HOTKEY_MAP` are written).

Default map
-----------
======================  ==============  ================================
Action                  Key             Effect
======================  ==============  ================================
range_next              Tab             next range of the active mode
range_prev              Shift-Tab       previous range
range_auto              A               AUTO range
range_auto_plus         P               AUTO+ range
range_index_1 … 9       1 … 9           jump to range N (RANGE screen order)
mode_1 … 6              F1 … F6         cycle the MODE button group
back                    Esc             leave RANGE / SETTINGS / HOTKEYS
======================  ==============  ================================

Everything is disabled by ``"hotkeys": false``; keys are ignored while a text
field (RAW console, language popup) owns the focus so typing keeps working.
"""

from __future__ import annotations

import sys
import tkinter as tk

from core.modes import MODE_CYCLE_GROUPS
from core.ranges import (
    auto_plus_range_flag,
    auto_range_flag,
    cycle_range_flag,
    flag_at_index,
)
from gui.settings import save_settings

# Widget classes that consume typed characters – never steal keys from them.
TYPING_WIDGET_CLASSES = frozenset(
    {"Entry", "TEntry", "Text", "Spinbox", "TCombobox", "Listbox"}
)

# Screens where the different shortcuts make sense.
RANGE_SCREENS = ("main", "range")
MODE_SCREENS = ("main",)

RANGE_ACTIONS = ("range_next", "range_prev", "range_auto", "range_auto_plus")
RANGE_INDEX_ACTIONS = tuple(f"range_index_{index}" for index in range(1, 10))
MODE_ACTIONS = tuple(f"mode_{index}" for index in range(1, 7))

ACTION_ORDER: tuple[str, ...] = (
    RANGE_ACTIONS + ("save_reading", "clear_readings", "hold", "toggle_rel")
    + RANGE_INDEX_ACTIONS + MODE_ACTIONS
    + ("toggle_global", "toggle_fullscreen", "back")
)

DEFAULT_HOTKEY_MAP: dict[str, str] = {
    "range_next": "Tab",
    "range_prev": "Shift-Tab",
    "range_auto": "a",
    "range_auto_plus": "p",
    "save_reading": "F7",
    "clear_readings": "F9",
    "hold": "F8",
    "toggle_rel": "r",
    "toggle_global": "F11",
    "toggle_fullscreen": "Alt-Return",
    **{f"range_index_{index}": str(index) for index in range(1, 10)},
    **{f"mode_{index}": f"F{index}" for index in range(1, 7)},
    "back": "Escape",
}

# Keysyms that only exist as modifiers – a capture waits for the real key.
MODIFIER_KEYSYMS = frozenset({
    "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R",
    "Super_L", "Super_R", "Meta_L", "Meta_R", "Hyper_L", "Hyper_R",
    "Caps_Lock", "Num_Lock", "ISO_Level3_Shift", "Mode_switch",
})

CHORD_TIMEOUT_MS = 1500   # how long the second key of a chord may take

# Tk reports punctuation keys as the *character* ("+", "-", "."), but a binding
# pattern needs the keysym *name* ("<plus>", "<minus>", "<period>").
CHAR_TO_KEYSYM = {
    "+": "plus", "-": "minus", "=": "equal", ".": "period", ",": "comma",
    "/": "slash", "\\": "backslash", ";": "semicolon", "'": "apostrophe",
    "[": "bracketleft", "]": "bracketright", "`": "grave",
    "<": "less", ">": "greater", "?": "question", "!": "exclam",
    "@": "at", "#": "numbersign", "$": "dollar", "%": "percent",
    "^": "asciicircum", "&": "ampersand", "*": "asterisk",
    "(": "parenleft", ")": "parenright", "_": "underscore",
    "{": "braceleft", "}": "braceright", "|": "bar", ":": "colon",
    '"': "quotedbl", "~": "asciitilde", " ": "space",
}
KEYSYM_TO_CHAR = {name: char for char, name in CHAR_TO_KEYSYM.items()}

_MODIFIER_PREFIXES = ("Control", "Alt", "Shift", "Command", "Super")
_MODIFIER_NAMES = {"Control": "Ctrl", "Command": "Cmd", "Super": "Win"}
_KEY_NAMES = {
    "Escape": "Esc",
    "Return": "Enter",
    "BackSpace": "BkSp",
    "Delete": "Del",
    "Insert": "Ins",
    "Prior": "PgUp",
    "Next": "PgDn",
    "space": "Space",
    "Left": "←",
    "Right": "→",
    "Up": "↑",
    "Down": "↓",
    # Punctuation keysyms → the glyph the key prints
    "period": ".",
    "comma": ",",
    "slash": "/",
    "backslash": "\\",
    "semicolon": ";",
    "apostrophe": "'",
    "bracketleft": "[",
    "bracketright": "]",
    "minus": "-",
    "equal": "=",
    "grave": "`",
    "plus": "+",
    "less": "<",
    "greater": ">",
    "question": "?",
    "exclam": "!",
    "at": "@",
    "numbersign": "#",
    "dollar": "$",
    "percent": "%",
    "asciicircum": "^",
    "ampersand": "&",
    "asterisk": "*",
    "parenleft": "(",
    "parenright": ")",
    "underscore": "_",
    "braceleft": "{",
    "braceright": "}",
    "bar": "|",
    "colon": ":",
    "quotedbl": "\"",
    "asciitilde": "~",
    "space": "Space",
    "KP_Add": "Num+",
    "KP_Subtract": "Num-",
    "KP_Multiply": "Num*",
    "KP_Divide": "Num/",
    "KP_Decimal": "Num.",
    "KP_Enter": "NumEnter",
}


# ----------------------------------------------------------------------
# Pure helpers (no Tk state – unit tested)
# ----------------------------------------------------------------------

def normalize_map(raw: dict | None) -> dict[str, str]:
    """Default map overlaid with the user overrides read from settings."""
    mapping = dict(DEFAULT_HOTKEY_MAP)
    if isinstance(raw, dict):
        for action, sequence in raw.items():
            if action in mapping and isinstance(sequence, str):
                mapping[action] = sequence.strip()
    return mapping


def normalize_disabled(raw) -> set[str]:
    """Actions switched off on the HOTKEYS screen (stored as a list)."""
    if not isinstance(raw, list):
        return set()
    return {action for action in raw if isinstance(action, str) and action in ACTION_ORDER}


def parse_sequence_steps(sequence: str) -> list[str]:
    """A stored shortcut → its key presses.

    Normally one step ("Control-1"); several space-separated steps form a chord
    ("0 1" = press 0, then 1). Spaces never appear inside a single step, because
    the space bar's keysym is spelled ``space``.
    """
    return [step for step in (sequence or "").split() if step]


def is_chord_capable(step: str) -> bool:
    """Can this key start a two-key chord?

    Only plain keys can: modifiers ("Control-1", "Shift-Tab") and function keys
    (F1…F12) commit immediately, so a quick double tap never turns into a chord.
    """
    step = (step or "").strip()
    if not step:
        return False
    parts = step.split("-")
    # A leading Control/Alt/… means the key already carries a modifier.
    if len(parts) > 1 and parts[0] in _MODIFIER_PREFIXES:
        return False
    if step.startswith("F") and step[1:].isdigit():
        return False
    return True


def format_sequence_step(sequence: str) -> str:
    """Human readable single key ("Shift-Tab" → "Shift+Tab", "a" → "A")."""
    sequence = (sequence or "").strip()
    if not sequence:
        return ""
    parts = sequence.split("-")
    modifiers: list[str] = []
    while len(parts) > 1 and parts[0] in _MODIFIER_PREFIXES:
        prefix = parts.pop(0)
        modifiers.append(_MODIFIER_NAMES.get(prefix, prefix))
    key = "-".join(parts)
    if len(key) == 1:
        key = key.upper()
    else:
        key = _KEY_NAMES.get(key, key)
    return "+".join(modifiers + [key]) if key else ""


def key_sequences(sequence: str) -> list[str]:
    """Tk event patterns to bind for a stored key ("" binds nothing).

    Digits need the explicit ``KeyPress-`` prefix: Tk reads ``<1>`` as the left
    mouse button, not as the "1" key. Punctuation is converted to its keysym
    name, because ``<->`` is not a valid Tk pattern.
    """
    canonical = normalize_step(sequence)
    if not canonical:
        return []
    parts = canonical.split("-")
    if len(parts) == 1:
        key = parts[0]
        if len(key) == 1 and key.isdigit():
            return [f"KeyPress-{key}"]
        if len(key) == 1 and key.isalpha():
            # "a" should also fire on Shift+A, whose keysym is "A".
            return [key.lower(), key.upper()]
        return [key]
    if canonical == "Shift-Tab":
        # X11 reports Shift+Tab as ISO_Left_Tab; Tk on Windows rejects it.
        return ["Shift-Tab", "ISO_Left_Tab"]
    return [canonical]


def normalize_step(step: str) -> str:
    """Canonical form of one key press: "+" → "plus", "Control-+" → "Control-plus"."""
    step = (step or "").strip()
    if not step:
        return ""
    parts = step.split("-")
    modifiers: list[str] = []
    while len(parts) > 1 and parts[0] in _MODIFIER_PREFIXES:
        modifiers.append(parts.pop(0))
    key = "-".join(parts)
    if len(key) == 1:
        if key.isalpha():
            key = key.lower()          # case-insensitive for letters
        else:
            key = CHAR_TO_KEYSYM.get(key, key)
    if not key:
        return ""
    return "-".join(modifiers + [key])


def format_key_name(sequence: str) -> str:
    """Human readable shortcut; chords are joined with an arrow ("0 → 1")."""
    steps = parse_sequence_steps(sequence)
    if not steps:
        return ""
    return " → ".join(format_sequence_step(step) for step in steps)


def _os_modifiers() -> set[str] | None:
    """Modifiers that are *physically* down right now (Windows truth).

    Tk's ``event.state`` is unreliable for some keys (numpad presses report a
    stray Alt bit on Windows), so prefer the real key state when we can get it.
    Returns ``None`` when the OS query is not available.
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        user32 = ctypes.windll.user32

        def down(vk: int) -> bool:
            return bool(user32.GetAsyncKeyState(vk) & 0x8000)

        modifiers: set[str] = set()
        if down(0x11):          # VK_CONTROL
            modifiers.add("Control")
        if down(0x12):          # VK_MENU
            modifiers.add("Alt")
        if down(0x10):          # VK_SHIFT
            modifiers.add("Shift")
        return modifiers
    except Exception:
        return None


def sequence_from_event(event) -> str | None:
    """Tk event → stored key string; ``None`` for modifier-only presses."""
    keysym = getattr(event, "keysym", "") or ""
    if not keysym or keysym in MODIFIER_KEYSYMS:
        return None
    os_mods = _os_modifiers()
    if os_mods is None:
        # Fallback (non-Windows / tests): derive modifiers from the event state.
        state = int(getattr(event, "state", 0) or 0)
        control = bool(state & 0x0004)
        alt = bool(state & 0x0008) or bool(state & 0x20000)
        shift = bool(state & 0x0001)
    else:
        control = "Control" in os_mods
        alt = "Alt" in os_mods
        shift = "Shift" in os_mods
    if keysym == "ISO_Left_Tab":
        keysym, shift = "Tab", True
    # Shift+A already reports keysym "A", so the modifier is implicit.
    if len(keysym) == 1 and keysym.isalpha() and keysym.isupper():
        shift = False
    parts = []
    if control:
        parts.append("Control")
    if alt:
        parts.append("Alt")
    if shift:
        parts.append("Shift")
    parts.append(keysym)
    return "-".join(parts)


_MODE_GROUP_I18N = {
    "VDC": "voltage",
    "ADC": "current",
    "OHM": "resistance",
    "CAP": "capacitance",
    "DIODE": "diode",
    "Hz": "frequency",
}


def _range_label_at(app, index: int) -> str | None:
    """Range name (e.g. ``6V``) for the 1-based index of the current mode."""
    if app is None:
        return None
    try:
        from core.parsing import MODEL
        from core.ranges import ranges_for_kind

        last = app.main_screen._last_display_measurement
        kind = last[0].kind if last else None
        if not kind:
            return None
        items = ranges_for_kind(kind, MODEL.model_name)
        if 1 <= index <= len(items):
            return items[index - 1][0]
    except Exception:
        return None
    return None


def action_label(action: str, app=None) -> str:
    """Translated label shown on the HOTKEYS screen (plain-language)."""
    from core.i18n import t

    if action.startswith("range_index_"):
        index = int(action.rsplit("_", 1)[1])
        label = _range_label_at(app, index)
        if label:
            return t("hotkeys.action_range_index_named", label=label)
        return t("hotkeys.action_range_index", n=index)
    if action.startswith("mode_"):
        index = int(action.rsplit("_", 1)[1]) - 1
        if 0 <= index < len(MODE_CYCLE_GROUPS):
            group = MODE_CYCLE_GROUPS[index][0]
            key = _MODE_GROUP_I18N.get(group)
            name = t(f"hotkeys.group_{key}") if key else group
            return t("hotkeys.action_mode_named", name=name)
        return t("hotkeys.action_mode", n=index + 1)
    return t(f"hotkeys.action_{action}")


# ----------------------------------------------------------------------
# Manager
# ----------------------------------------------------------------------

class HotkeyManager:
    """Binds the configured keys on the root window and runs their actions."""

    def __init__(self, app) -> None:
        self.app = app
        self.capturing = False
        # Set by the HOTKEYS screen while one of its rows is armed.
        self.capture_sink = None
        self._bound: list[str] = []
        # Half-typed chord: first key pressed, waiting for the rest.
        self._chord_action: str | None = None
        self._chord_rest: list[str] = []
        self._chord_after: str | None = None
        self.apply_map()
        # Fallback for keys that have no action bound: Tk only runs the most
        # specific binding, so mapped keys are routed via their own handler.
        self.app.root.bind("<Key>", self._on_generic_key, add="+")

    # -- settings -------------------------------------------------------

    @property
    def map(self) -> dict[str, str]:
        """Effective map: defaults merged with the user's overrides."""
        return normalize_map(self.app.settings.get("hotkey_map"))

    @property
    def enabled(self) -> bool:
        return bool(self.app.settings.get("hotkeys", True))

    @property
    def disabled(self) -> set[str]:
        """Actions switched off individually on the HOTKEYS screen."""
        return normalize_disabled(self.app.settings.get("hotkey_disabled"))

    def is_action_enabled(self, action: str) -> bool:
        return action not in self.disabled

    def enabled_actions(self) -> list[str]:
        disabled = self.disabled
        return [action for action in ACTION_ORDER if action not in disabled]

    def set_action_enabled(self, action: str, enabled: bool) -> None:
        """Switch a single action on/off.

        Switching an action **off also clears its key** – the row stops working
        and the shortcut is freed for something else.
        """
        if action not in ACTION_ORDER:
            return
        disabled = self.disabled
        mapping = self.map
        if enabled:
            disabled.discard(action)
        else:
            disabled.add(action)
            mapping[action] = ""
        self.app.settings["hotkey_disabled"] = [
            item for item in ACTION_ORDER if item in disabled
        ]
        self._store(mapping)

    def set_key(self, action: str, sequence: str) -> str | None:
        """Assign ``sequence`` to ``action`` ("" = unbound).

        A key already used by another action is swapped over, so the user never
        ends up with two actions on one key. Returns the action it displaced.
        """
        mapping = self.map
        sequence = (sequence or "").strip()
        previous = mapping.get(action, "")
        swapped: str | None = None
        if sequence:
            for other, other_sequence in mapping.items():
                if other == action or not other_sequence:
                    continue
                if other_sequence.lower() == sequence.lower():
                    mapping[other] = previous
                    swapped = other
                    break
        mapping[action] = sequence
        self._store(mapping)
        return swapped

    def reset_map(self) -> None:
        """Back to :data:`DEFAULT_HOTKEY_MAP` (clears keys and per-action switches)."""
        self.app.settings["hotkey_disabled"] = []
        self._store(dict(DEFAULT_HOTKEY_MAP))

    def _store(self, mapping: dict[str, str]) -> None:
        self.app.settings["hotkey_map"] = {
            action: sequence
            for action, sequence in mapping.items()
            if DEFAULT_HOTKEY_MAP.get(action, "") != sequence
        }
        save_settings(self.app.settings)
        self.apply_map()

    # -- binding --------------------------------------------------------

    def apply_map(self) -> None:
        """(Re)bind every configured key, dropping the previous bindings."""
        for pattern in self._bound:
            try:
                self.app.root.unbind(f"<{pattern}>")
            except tk.TclError:
                pass
        self._bound.clear()

        seen: set[str] = set()
        disabled = self.disabled
        for action, sequence in self.map.items():
            if action in disabled:
                continue
            steps = parse_sequence_steps(sequence)
            if not steps:
                continue
            # A chord ("0 1") binds only its first step; the rest is matched
            # by the chord state machine when that key is pressed.
            handler = (
                self._handler_for(action) if len(steps) == 1
                else self._chord_starter_for(action, steps[1:])
            )
            for pattern in key_sequences(steps[0]):
                if pattern in seen:
                    continue
                try:
                    self.app.root.bind(f"<{pattern}>", handler, add="+")
                except tk.TclError:
                    continue  # keysym not known on this platform
                seen.add(pattern)
                self._bound.append(pattern)

    # -- chords ---------------------------------------------------------

    def _chord_starter_for(self, action: str, rest: list[str]):
        """Handler for the first key of a chord: arms the remaining steps."""

        def on_key(event: tk.Event | None = None) -> str | None:
            if self.capturing:
                self._route_capture(event)
                return "break"
            if not self.enabled:
                return None
            if self._text_field_focused():
                return None
            self._start_chord(action, rest)
            return "break"

        return on_key

    def _start_chord(self, action: str, rest: list[str]) -> None:
        self._clear_chord()
        self._chord_action = action
        self._chord_rest = list(rest)
        self._chord_after = self.app.root.after(CHORD_TIMEOUT_MS, self._chord_expired)

    def _chord_expired(self) -> None:
        """No second key in time – the chord is abandoned."""
        self._clear_chord()

    def _clear_chord(self) -> None:
        if self._chord_after is not None:
            try:
                self.app.root.after_cancel(self._chord_after)
            except tk.TclError:
                pass
            self._chord_after = None
        self._chord_action = None
        self._chord_rest = []

    def _consume_chord(self, event: tk.Event | None) -> str | None:
        """Feed a key press to a pending chord; ``"break"`` if one was armed."""
        action = self._chord_action
        rest = self._chord_rest
        if action is None:
            return None
        self._clear_chord()
        pressed = sequence_from_event(event) if event is not None else None
        if (
            pressed is not None
            and rest
            and normalize_step(pressed) == normalize_step(rest[0])
        ):
            try:
                self.run_action(action)
            except (tk.TclError, KeyError):
                pass
        return "break"  # swallow the key either way

    def _handler_for(self, action: str):
        def on_key(event: tk.Event | None = None) -> str | None:
            if self.capturing:
                self._route_capture(event)
                return "break"
            if self._consume_chord(event) is not None:
                return "break"
            if not self.enabled:
                return None
            if self._text_field_focused():
                return None
            try:
                handled = self.run_action(action)
            except (tk.TclError, KeyError):
                return None
            return "break" if handled else None

        return on_key

    def _on_generic_key(self, event: tk.Event) -> str | None:
        """Catches keys that are not bound to any action (setup screen)."""
        if self.capturing:
            self._route_capture(event)
            return "break"
        return self._consume_chord(event)

    def _route_capture(self, event: tk.Event | None) -> None:
        sink = self.capture_sink
        if sink is not None and event is not None:
            sink(event)

    # -- guards ---------------------------------------------------------

    def _screen(self) -> str:
        return getattr(self.app, "_current_screen", "main")

    def _text_field_focused(self) -> bool:
        """True when a widget that accepts typed text owns the keyboard focus."""
        try:
            widget = self.app.root.focus_get()
        except (KeyError, tk.TclError):
            return False
        if widget is None:
            return False
        try:
            return widget.winfo_class() in TYPING_WIDGET_CLASSES
        except tk.TclError:
            return False

    def _active_kind(self, screens: tuple[str, ...]) -> str | None:
        if self._screen() not in screens:
            return None
        return self.app.mode_state.get_active_kind()

    # -- dispatch -------------------------------------------------------

    def run_action(self, action: str) -> bool:
        """Run one action by id; returns True when something happened."""
        if action == "range_next":
            return self.cycle_range(1)
        if action == "range_prev":
            return self.cycle_range(-1)
        if action == "range_auto":
            return self.jump_to_auto()
        if action == "range_auto_plus":
            return self.jump_to_auto_plus()
        if action == "save_reading":
            return self.save_reading()
        if action == "clear_readings":
            return self.clear_readings()
        if action == "hold":
            return self.toggle_hold()
        if action == "toggle_rel":
            return self.app.main_screen.toggle_relative()
        if action == "toggle_global":
            return self.toggle_global()
        if action == "toggle_fullscreen":
            return self.toggle_fullscreen()
        if action.startswith("range_index_"):
            return self.jump_to_range(int(action.rsplit("_", 1)[1]) - 1)
        if action.startswith("mode_"):
            index = int(action.rsplit("_", 1)[1]) - 1
            if 0 <= index < len(MODE_CYCLE_GROUPS):
                return self.cycle_mode(MODE_CYCLE_GROUPS[index][0])
            return False
        if action == "back":
            return self.back_to_main()
        return False

    # -- actions --------------------------------------------------------

    def cycle_range(self, step: int) -> bool:
        """Move to the next/previous range of the active mode."""
        kind = self._active_kind(RANGE_SCREENS)
        if kind is None:
            return False
        flag = cycle_range_flag(kind, self.app.current_range_flag, step)
        if flag is None:
            return False
        self.app.select_range_flag(flag)
        return True

    def jump_to_range(self, index: int) -> bool:
        """Select range at 0-based ``index`` of the RANGE list."""
        kind = self._active_kind(RANGE_SCREENS)
        flag = flag_at_index(kind, index)
        if flag is None:
            return False
        self.app.select_range_flag(flag)
        return True

    def jump_to_auto(self) -> bool:
        kind = self._active_kind(RANGE_SCREENS)
        flag = auto_range_flag(kind)
        if flag is None:
            return False
        self.app.select_range_flag(flag)
        return True

    def jump_to_auto_plus(self) -> bool:
        kind = self._active_kind(RANGE_SCREENS)
        flag = auto_plus_range_flag(kind)
        if flag is None:
            return False
        self.app.select_range_flag(flag)
        return True

    def cycle_mode(self, group_id: str) -> bool:
        """Same effect as clicking a MODE button on the main screen."""
        if self._screen() not in MODE_SCREENS:
            return False
        self.app.cycle_mode(group_id)
        return True

    def save_reading(self) -> bool:
        """Store the current measurement in the save slots (clicking the digits)."""
        if self._screen() not in MODE_SCREENS:
            return False
        self.app.save_reading()
        return True

    def clear_readings(self) -> bool:
        """Wipe all saved readings (same as the top-bar 清空 button)."""
        if self._screen() not in MODE_SCREENS:
            return False
        self.app.clear_readings()
        return True

    def sequence_is_bound(self, sequence: str) -> bool:
        """True when this key press is an enabled shortcut we will act on."""
        pressed = normalize_step(sequence)
        if not pressed:
            return False
        for action, key in self.map.items():
            if not key or action in self.disabled:
                continue
            if " → " in key:                     # chord – only the first step is captured
                key = key.split(" → ")[0]
            if normalize_step(key) == pressed:
                return True
        return False

    def toggle_global(self) -> bool:
        """Turn "works while another window is focused" on or off."""
        self.app.set_global_hotkeys(not self.app.settings.get("global_hotkeys", False))
        return True

    def toggle_fullscreen(self) -> bool:
        """Full screen ⇄ windowed."""
        self.app.toggle_fullscreen()
        return True

    def run_global_action(self, action: str) -> None:
        """Run an action that arrived from a system-wide hotkey."""
        if not self.enabled or action in self.disabled:
            return
        try:
            self.run_action(action)
        except (tk.TclError, KeyError):
            pass

    def dispatch_sequence(self, sequence: str) -> bool:
        """Handle one key press coming from the background keyboard hook."""
        if not self.enabled:
            return False
        pressed = normalize_step(sequence)
        if not pressed:
            return False
        disabled = self.disabled
        mapping = self.map

        # The on/off switch keeps working even while background mode is off.
        toggle = mapping.get("toggle_global", "")
        if (
            toggle and "toggle_global" not in disabled
            and normalize_step(toggle) == pressed
        ):
            return self.toggle_global()

        if not self.app.settings.get("global_hotkeys"):
            return False

        # Finish a half-typed chord first.
        if self._chord_action is not None:
            action = self._chord_action
            rest = self._chord_rest
            self._clear_chord()
            if rest and normalize_step(rest[0]) == pressed:
                try:
                    self.run_action(action)
                except (tk.TclError, KeyError):
                    pass
            return True

        for action, stored in mapping.items():
            if action in disabled:
                continue
            steps = parse_sequence_steps(stored)
            if not steps or normalize_step(steps[0]) != pressed:
                continue
            if len(steps) > 1:
                self._start_chord(action, steps[1:])
            else:
                try:
                    self.run_action(action)
                except (tk.TclError, KeyError):
                    pass
            return True
        return False

    def toggle_hold(self) -> bool:
        """RUN ⇄ HOLD, exactly like clicking the top-bar HOLD area."""
        if self._screen() not in RANGE_SCREENS:
            return False
        self.app.toggle_hold()
        return True

    def back_to_main(self) -> bool:
        """Leave the RANGE screen, or step back out of SETTINGS / HOTKEYS.

        The CONNECT screen is a dead end (there is nothing behind it), so Esc
        does nothing there.
        """
        screen = self._screen()
        if screen == "range":
            self.app.show_main_screen()
            return True
        if screen == "hotkeys":
            self.app.show_settings_screen()
            return True
        if screen == "settings":
            # Respects where Settings was opened from (main or connect screen).
            self.app.go_back_from_settings()
            return True
        return False


__all__ = [
    "ACTION_ORDER",
    "CHORD_TIMEOUT_MS",
    "DEFAULT_HOTKEY_MAP",
    "HotkeyManager",
    "TYPING_WIDGET_CLASSES",
    "action_label",
    "format_key_name",
    "format_sequence_step",
    "is_chord_capable",
    "key_sequences",
    "normalize_disabled",
    "normalize_map",
    "normalize_step",
    "parse_sequence_steps",
    "sequence_from_event",
]
