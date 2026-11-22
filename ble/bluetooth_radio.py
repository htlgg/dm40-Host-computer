"""Check whether Bluetooth is enabled on Windows (adapter PnP status OK)."""

from __future__ import annotations

import subprocess
import sys
import time

_BT_OFF_ERROR_MARKERS = (
    "bluetooth radio is not powered",
    "bluetooth is powered off",
    "radio is not powered",
    "radio not available",
    "no bluetooth adapter",
    "bluetooth unavailable",
    "bluetooth is turned off",
    "device is not available",
    "bleakbluetoothnotavailable",
)

# "OK" for at least ONE bluetooth device means the radio is up.  A leftover or
# virtual adapter (e.g. "BARROT Bluetooth Adapter" stuck in "Unknown") must not
# make the whole check fail – that used to hide a perfectly working adapter.
_PS_CHECK = r"""
$devices = @(Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue)
if ($devices.Count -eq 0) { exit 2 }
$ok = @($devices | Where-Object { $_.Status -eq 'OK' })
if ($ok.Count -gt 0) { exit 0 }
$bad = @($devices | Where-Object { $_.Status -eq 'Error' -or $_.Status -eq 'Degraded' })
if ($bad.Count -gt 0) { exit 1 }
exit 2
"""

CACHE_SECONDS = 10.0
_cache: tuple[float, bool | None] | None = None


def exception_indicates_bt_off(exc: BaseException) -> bool:
    try:
        from bleak.exc import BleakBluetoothNotAvailableError

        if isinstance(exc, BleakBluetoothNotAvailableError):
            return True
    except ImportError:
        pass
    msg = str(exc).lower()
    return any(marker in msg for marker in _BT_OFF_ERROR_MARKERS)


def _query() -> bool | None:
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", _PS_CHECK],
            capture_output=True,
            timeout=8,
            creationflags=flags,
        )
        if proc.returncode == 0:
            return True
        if proc.returncode == 1:
            return False
        return None
    except Exception:
        return None


def is_bluetooth_enabled(*, force: bool = False) -> bool | None:
    """True = on, False = off, None = unknown (other OS / error).

    The answer is cached for a few seconds – the BLE worker asks repeatedly and
    spawning PowerShell every time is expensive.
    """
    global _cache
    if sys.platform != "win32":
        return None
    now = time.monotonic()
    if not force and _cache is not None and now - _cache[0] < CACHE_SECONDS:
        return _cache[1]
    value = _query()
    _cache = (now, value)
    return value
