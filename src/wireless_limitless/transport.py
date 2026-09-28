"""BLE transport for QCY earbuds on top of bleak (WinRT backend on Windows).

Owns the BleakClient: scanning by manufacturer data, connecting with retries,
resolving characteristics strictly inside service 0xA001 (service 0x7033
reuses the same characteristic UUIDs), and raw reads / writes / notifies.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.exc import BleakBluetoothNotAvailableError, BleakError

from . import protocol as p

log = logging.getLogger(__name__)

CONNECT_ATTEMPTS = 3
CONNECT_TIMEOUT_S = 20.0
GATT_TIMEOUT_S = 5.0


class TransportError(Exception):
    """Failure with a stable machine-readable code the UI maps to a message."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def mask_address(address: str | None) -> str:
    """Keep only the last two bytes of a Bluetooth address for logs and UI."""
    if not address:
        return "-"
    parts = address.split(":")
    return ":".join(["**"] * (len(parts) - 2) + parts[-2:]) if len(parts) == 6 else "**"


@dataclass
class FoundDevice:
    ble_device: BLEDevice
    address: str
    vendor_id: int
    rssi: int
    advert: p.Advert


async def scan(timeout: float, prefer_address: str | None = None,
               supported: Callable[[int], bool] = lambda _vid: True) -> list[FoundDevice]:
    """Scan for QCY advertisers (company id 0x521C).

    Returns early once the preferred address is seen, or ~1.5 s after the
    first supported device so a second nearby QCY device can still show up.
    """
    found: dict[str, FoundDevice] = {}
    done = asyncio.Event()
    loop = asyncio.get_running_loop()
    first_hit: list[float] = []

    def on_adv(device: BLEDevice, adv) -> None:
        payload = (adv.manufacturer_data or {}).get(p.COMPANY_ID)
        if payload is None:
            return
        advert = p.parse_advert(bytes(payload))
        if advert is None:
            return
        found[device.address] = FoundDevice(device, device.address, advert.vendor_id, adv.rssi, advert)
        if prefer_address and device.address.upper() == prefer_address.upper():
            done.set()
        elif supported(advert.vendor_id) and not first_hit:
            first_hit.append(loop.time())

    try:
        async with BleakScanner(detection_callback=on_adv, scanning_mode="active"):
            deadline = loop.time() + timeout
            while not done.is_set() and loop.time() < deadline:
                if first_hit and loop.time() - first_hit[0] > (4.0 if prefer_address else 1.5):
                    break
                try:
                    await asyncio.wait_for(done.wait(), 0.25)
                except TimeoutError:
                    pass
    except BleakBluetoothNotAvailableError as exc:
        raise TransportError("bluetooth_unavailable", str(exc)) from exc
    except (BleakError, OSError) as exc:
        raise TransportError("scan_failed", str(exc)) from exc

    return sorted(found.values(), key=lambda d: d.rssi, reverse=True)


class QcyTransport:
    def __init__(self,
                 on_frame: Callable[[bytes], None],
                 on_battery: Callable[[bytes], None],
                 on_disconnect: Callable[[], None]):
        self._on_frame = on_frame
        self._on_battery = on_battery
        self._on_disconnect = on_disconnect
        self._client: BleakClient | None = None
        self._chars: dict[str, BleakGATTCharacteristic] = {}
        self._established = False
        self._closing = False
        self.mtu = 0

    @property
    def connected(self) -> bool:
        return self._established and self._client is not None and self._client.is_connected

    async def connect(self, device: FoundDevice) -> None:
        last_exc: Exception | None = None
        for attempt in range(1, CONNECT_ATTEMPTS + 1):
            client = BleakClient(device.ble_device, disconnected_callback=self._handle_disconnect,
                                 timeout=CONNECT_TIMEOUT_S)
            self._closing = False
            try:
                await client.connect()
                await asyncio.sleep(0.4)  # WinRT may accept, then drop an unauthorised link
                if not client.is_connected:
                    raise TransportError("dropped", "link dropped right after connect")
                self._chars = self._resolve_characteristics(client)
                await self._subscribe(client)
                self._client = client
                self._established = True
                self.mtu = client.mtu_size
                log.info("connected to %s (mtu %s)", mask_address(device.address), self.mtu)
                return
            except TransportError as exc:
                last_exc = exc
                if exc.code == "service_missing":
                    await self._safe_disconnect(client)
                    raise
            except (BleakError, OSError, TimeoutError) as exc:
                last_exc = exc
            log.warning("connect attempt %d failed: %s", attempt, last_exc)
            await self._safe_disconnect(client)
            await asyncio.sleep(0.5 * attempt)
        raise TransportError("connect_failed", str(last_exc))

    @staticmethod
    def _resolve_characteristics(client: BleakClient) -> dict[str, BleakGATTCharacteristic]:
        service = client.services.get_service(p.SERVICE_UUID)
        if service is None:
            raise TransportError("service_missing", "QCY control service 0xA001 not found")
        chars = {c.uuid.lower(): c for c in service.characteristics}
        for required in (p.CHAR_COMMAND, p.CHAR_NOTIFY):
            if required not in chars:
                raise TransportError("service_missing", f"characteristic {required} missing")
        return chars

    async def _subscribe(self, client: BleakClient) -> None:
        await client.start_notify(self._chars[p.CHAR_NOTIFY], self._handle_notify)
        battery = self._chars.get(p.CHAR_BATTERY)
        if battery is not None and "notify" in battery.properties:
            try:
                await client.start_notify(battery, self._handle_battery)
            except (BleakError, OSError) as exc:  # battery push is optional
                log.info("battery notify unavailable: %s", exc)

    def _handle_notify(self, _char: BleakGATTCharacteristic, data: bytearray) -> None:
        self._on_frame(bytes(data))

    def _handle_battery(self, _char: BleakGATTCharacteristic, data: bytearray) -> None:
        self._on_battery(bytes(data))

    def _handle_disconnect(self, client: BleakClient) -> None:
        # Ignore drops of half-open attempts and of links we are closing on purpose.
        if client is not self._client or not self._established:
            return
        self._client = None
        self._established = False
        if not self._closing:
            log.info("link lost")
            self._on_disconnect()

    async def disconnect(self) -> None:
        self._closing = True
        client, self._client = self._client, None
        self._established = False
        if client is not None:
            await self._safe_disconnect(client)

    @staticmethod
    async def _safe_disconnect(client: BleakClient) -> None:
        try:
            await asyncio.wait_for(client.disconnect(), GATT_TIMEOUT_S)
        except (BleakError, OSError, TimeoutError):
            pass

    def _require(self) -> BleakClient:
        if not self.connected:
            raise TransportError("not_connected")
        assert self._client is not None
        return self._client

    async def write_command(self, frame: bytes) -> None:
        client = self._require()
        try:
            await asyncio.wait_for(
                client.write_gatt_char(self._chars[p.CHAR_COMMAND], frame, response=False), GATT_TIMEOUT_S)
        except (BleakError, OSError, TimeoutError) as exc:
            raise TransportError("write_failed", str(exc)) from exc

    async def write_touch(self, data: bytes) -> None:
        client = self._require()
        char = self._chars.get(p.CHAR_TOUCH)
        if char is None:
            raise TransportError("unsupported", "touch characteristic missing")
        try:
            await asyncio.wait_for(client.write_gatt_char(char, data, response=False), GATT_TIMEOUT_S)
        except (BleakError, OSError, TimeoutError) as exc:
            raise TransportError("write_failed", str(exc)) from exc

    async def read(self, uuid: str) -> bytes | None:
        """Read a characteristic of service 0xA001; None if absent."""
        client = self._require()
        char = self._chars.get(uuid)
        if char is None or "read" not in char.properties:
            return None
        try:
            return bytes(await asyncio.wait_for(client.read_gatt_char(char), GATT_TIMEOUT_S))
        except (BleakError, OSError, TimeoutError) as exc:
            raise TransportError("read_failed", str(exc)) from exc
