"""Discover DM40 multimeters over BLE (Bleak)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from bleak import BleakScanner

from core.protocol_constants import MODEL_TABLE


@dataclass(frozen=True)
class DM40Device:
    address: str
    name: str
    model_name: str
    device_counts: int
    known: bool = True          # False = scanned but the name is not a DM40 one

    def list_label(self) -> str:
        if not self.known:
            label = self.name or "—"
            return f"{label}  ({self.address})"
        return f"{self.name or self.model_name}  ({self.address})"


def model_from_ble_name(name: str) -> tuple[str, int] | None:
    upper = (name or "").upper()
    for model_name, device_counts in MODEL_TABLE:
        if model_name in upper:
            return model_name, device_counts
    return None


async def scan_ble_devices(
    *, timeout: float = 10.0, include_unknown: bool = False,
) -> list[DM40Device]:
    """Return nearby BLE devices; DM40 models first when unknown ones are kept."""
    found: dict[str, DM40Device] = {}
    try:
        discovered = await BleakScanner.discover(timeout=timeout, return_adv=True)
        items = discovered.items()
    except TypeError:
        devices = await BleakScanner.discover(timeout=timeout)
        items = ((d.address, (d, None)) for d in devices)

    for address, (device, adv) in items:
        name = device.name or (getattr(adv, "local_name", None) if adv else None) or ""
        parsed = model_from_ble_name(name)
        if parsed is None and not include_unknown:
            continue
        model_name, device_counts = parsed if parsed else ("", 0)
        key = address.upper()
        if key in found:
            continue
        found[key] = DM40Device(
            address=address,
            name=name.strip(),
            model_name=model_name,
            device_counts=device_counts,
            known=parsed is not None,
        )
    return sorted(
        found.values(),
        key=lambda d: (not d.known, (d.name or d.address).lower()),
    )


async def scan_dm40_devices(*, timeout: float = 10.0) -> list[DM40Device]:
    """Return discovered DM40A/B/C devices (matched by BLE name)."""
    return await scan_ble_devices(timeout=timeout, include_unknown=False)


def scan_dm40_devices_sync(*, timeout: float = 10.0) -> list[DM40Device]:
    return asyncio.run(scan_dm40_devices(timeout=timeout))


def scan_ble_devices_sync(
    *, timeout: float = 10.0, include_unknown: bool = False,
) -> list[DM40Device]:
    return asyncio.run(scan_ble_devices(timeout=timeout, include_unknown=include_unknown))
