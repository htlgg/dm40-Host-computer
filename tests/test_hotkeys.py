"""Range (挡位) selection helpers used by the keyboard shortcuts.

Runs without Tk or Bluetooth:

    python tests/test_hotkeys.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.parsing import apply_model
from core.ranges import (
    auto_plus_range_flag,
    auto_range_flag,
    cycle_range_flag,
    flag_at_index,
    flag_index,
    make_range_cmd,
    range_flags,
    ranges_for_kind,
)

_checks = 0


def check(label: str, actual, expected) -> None:
    global _checks
    _checks += 1
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_range_tables() -> None:
    # DM40C: 60000 counts → 600mV / 6V / ...
    check("VDC flags", range_flags("VDC"), [0x00, 0x08, 0x10, 0x18, 0x20, 0x28, 0x30])
    check(
        "VDC labels",
        [label for label, _flag in ranges_for_kind("VDC", "DM40C")],
        ["600mV", "6V", "60V", "600V", "1000V", "AUTO", "AUTO+"],
    )
    check(
        "ADC flags",
        range_flags("ADC"),
        [0x01, 0x09, 0x11, 0x19, 0x21, 0x29, 0x31, 0x39],
    )
    check("RES flags", range_flags("RES"), [0x02, 0x0A, 0x12, 0x1A, 0x22, 0x2A, 0x32])
    # Modes without selectable ranges must stay empty (no-op hotkeys).
    check("CAP has no ranges", range_flags("CAP"), [])
    check("None kind has no ranges", range_flags(None), [])

    # DM40A/B differ only by labels, never by flags.
    check(
        "DM40A labels",
        [label for label, _flag in ranges_for_kind("VDC", "DM40A")],
        ["400mV", "4V", "40V", "400V", "1000V", "AUTO", "AUTO+"],
    )


def test_cycling() -> None:
    check("next from first", cycle_range_flag("VDC", 0x00, 1), 0x08)
    check("next wraps AUTO+ → first", cycle_range_flag("VDC", 0x30, 1), 0x00)
    check("prev from first wraps to last", cycle_range_flag("VDC", 0x00, -1), 0x30)
    check("prev from middle", cycle_range_flag("VDC", 0x10, -1), 0x08)
    # Stale flag from another mode: forward starts at the first entry, backward at the last.
    check("unknown flag forward", cycle_range_flag("VDC", 0x99, 1), 0x00)
    check("unknown flag backward", cycle_range_flag("VDC", 0x99, -1), 0x30)
    check("no ranges → None", cycle_range_flag("CAP", 0x03, 1), None)
    check("None kind → None", cycle_range_flag(None, 0, 1), None)

    # Every step of a full cycle visits each entry exactly once.
    seen, flag = [], 0x00
    for _ in range(len(range_flags("VDC"))):
        seen.append(flag)
        flag = cycle_range_flag("VDC", flag, 1)
    check("full cycle returns home", flag, 0x00)
    check("full cycle is complete", sorted(seen), sorted(range_flags("VDC")))


def test_indexing() -> None:
    check("index 0", flag_at_index("VDC", 0), 0x00)
    check("index 5 is AUTO", flag_at_index("VDC", 5), 0x28)
    check("index 6 is AUTO+", flag_at_index("VDC", 6), 0x30)
    check("index past end", flag_at_index("VDC", 7), None)
    check("negative index", flag_at_index("VDC", -1), None)
    check("index on range-less mode", flag_at_index("CAP", 0), None)
    check("flag_index round trip", flag_index("ADC", 0x11), 2)
    check("flag_index unknown", flag_index("ADC", 0x30), None)


def test_auto_flags() -> None:
    check("VDC AUTO", auto_range_flag("VDC"), 0x28)
    check("VDC AUTO+", auto_plus_range_flag("VDC"), 0x30)
    check("ADC AUTO+", auto_plus_range_flag("ADC"), 0x39)
    check("RES has no AUTO+", auto_plus_range_flag("RES"), None)
    check("RES AUTO", auto_range_flag("RES"), 0x32)
    check("CAP has no AUTO", auto_range_flag("CAP"), None)
    check("None kind has no AUTO", auto_range_flag(None), None)


def test_range_command_crc() -> None:
    """Every range command must satisfy the frame checksum (sum % 256 == 0)."""
    for kind in ("VDC", "VAC", "VDC+AC", "ADC", "AAC", "ADC+AC", "RES", "RES_ONLINE"):
        for flag in range_flags(kind):
            packet = make_range_cmd(flag)
            check(f"{kind} 0x{flag:02X} header", packet[:5], bytes([0xAF, 0x05, 0x03, 0x06, 0x01]))
            check(f"{kind} 0x{flag:02X} flag byte", packet[5], flag)
            check(f"{kind} 0x{flag:02X} length", len(packet), 7)
            check(f"{kind} 0x{flag:02X} checksum", sum(packet) & 0xFF, 0)


def test_settings_bom() -> None:
    """A settings.json saved by Notepad/PowerShell (UTF-8 BOM) must still load."""
    import shutil
    import tempfile

    import gui.settings as settings_module

    original = settings_module.SETTINGS_PATH
    tmpdir = Path(tempfile.mkdtemp())
    path = tmpdir / "settings.json"
    path.write_bytes(b"\xef\xbb\xbf" + b'{"language": "zh-CN", "hotkeys": false}')
    try:
        settings_module.SETTINGS_PATH = path
        loaded = settings_module.load_settings()
    finally:
        settings_module.SETTINGS_PATH = original
        shutil.rmtree(tmpdir, ignore_errors=True)

    check("BOM settings still load", loaded.get("language"), "zh-CN")
    check("BOM settings keep other keys", loaded.get("hotkeys"), False)
    check("BOM settings fill defaults", loaded.get("gui_font"), "Arial")


def main() -> int:
    apply_model("DM40C", 60000)
    test_range_tables()
    test_cycling()
    test_indexing()
    test_auto_flags()
    test_range_command_crc()
    test_settings_bom()
    print(f"OK - {_checks} range-binding checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
