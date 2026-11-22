"""Checks for BLE discovery / address helpers – no Bluetooth hardware needed."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import ble.discovery as discovery
from gui.manual_connect import normalize_address

checks = 0


def check(name: str, got, want) -> None:
    global checks
    checks += 1
    if got != want:
        raise SystemExit(f"FAILED - {name}: got {got!r}, want {want!r}")


class FakeAdv:
    def __init__(self, rssi: int) -> None:
        self.rssi = rssi


class FakeDevice:
    def __init__(self, address: str, name: str) -> None:
        self.address = address
        self.name = name


class FakeScanner:
    @staticmethod
    async def discover(*, timeout: float = 10.0, return_adv: bool = False):
        return {
            "42:F3:79:29:C8:84": (FakeDevice("42:F3:79:29:C8:84", ""), FakeAdv(-55)),
            "AA:BB:CC:DD:EE:FF": (FakeDevice("AA:BB:CC:DD:EE:FF", "DM40C"), FakeAdv(-62)),
        }


def main() -> None:
    discovery.BleakScanner = FakeScanner

    devices = asyncio.run(discovery.scan_ble_devices(timeout=1, include_unknown=True))
    check("keeps unknown devices", len(devices), 2)
    check("DM40 first", [d.known for d in devices], [True, False])
    check("model from name", devices[0].model_name, "DM40C")
    check("unknown has no model", devices[1].model_name, "")
    check("unknown label keeps the address", devices[1].list_label().endswith("42:F3:79:29:C8:84)"), True)

    dm40_only = asyncio.run(discovery.scan_dm40_devices(timeout=1))
    check("filtered scan", len(dm40_only), 1)
    check("filtered model", dm40_only[0].model_name, "DM40C")

    check("colon address", normalize_address("aa:bb:cc:dd:ee:ff"), "AA:BB:CC:DD:EE:FF")
    check("bare address", normalize_address("AABBCCDDEEFF"), "AA:BB:CC:DD:EE:FF")
    check("dashed address", normalize_address("AA-BB-CC-DD-EE-FF"), "AA:BB:CC:DD:EE:FF")
    check("spaced address", normalize_address(" AA BB CC DD EE FF "), "AA:BB:CC:DD:EE:FF")
    check("too short", normalize_address("9E:0F"), None)
    check("bad digits", normalize_address("ZZ:0F:71:18:E0:EE"), None)
    check("empty", normalize_address(""), None)

    print(f"OK - {checks} discovery checks passed")


if __name__ == "__main__":
    main()
