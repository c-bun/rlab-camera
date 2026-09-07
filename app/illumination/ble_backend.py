"""Real illumination backend: LED panels over Bluetooth Low Energy (Raspberry Pi).

``bleak`` is imported lazily inside __init__ so this module imports fine on machines
without a working Bluetooth stack; only instantiating the backend needs one. On Linux
bleak talks to BlueZ over D-Bus, which is present on the Pi.

bleak is async, but the app's routes are sync (FastAPI threadpool) — so a dedicated
asyncio event loop runs in a background thread and ``apply``/``off`` submit coroutines to
it. A ``threading.Lock`` serializes access (the ~2 fps preview poll and a capture can call
in at once), matching the camera backend's locking rationale.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from .base import IlluminationBackend, IlluminationControl
from .controls import PANEL_CONTROLS
from .protocol import COMMAND_CHAR_UUID, extract, to_payload

logger = logging.getLogger(__name__)

# Whole-broadcast timeout: connecting + writing every panel must finish within this.
_WRITE_TIMEOUT_S = 10.0
# Connectivity probe timeout for the status endpoint (kept short — the UI polls it).
_STATUS_TIMEOUT_S = 6.0


class BlePanels(IlluminationBackend):
    name = "ble"

    def __init__(self, addresses: list[str]) -> None:
        from bleak import BleakClient  # noqa: PLC0415 (lazy: needs a Bluetooth stack)

        self._BleakClient = BleakClient
        self._addresses = list(addresses)
        self._clients: dict[str, Any] = {}
        # Skip re-sending an identical command (the preview loop calls apply() ~2×/sec).
        self._last_payload: bytes | None = None
        self._lock = threading.Lock()

        # Background event loop for all bleak I/O.
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="ble-illumination", daemon=True)
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _submit(self, coro: Any, timeout: float) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=timeout)

    def get_controls(self) -> list[IlluminationControl]:
        return list(PANEL_CONTROLS)

    def apply(self, settings: dict[str, Any]) -> dict[str, Any]:
        applied = extract(settings)
        payload = to_payload(applied)
        with self._lock:
            if payload != self._last_payload:
                self._broadcast(payload)
        return applied

    def off(self) -> None:
        payload = bytes((0, 0, 0, 0))
        with self._lock:
            self._broadcast(payload)

    def status(self) -> dict[str, Any]:
        configured = len(self._addresses)
        try:
            return self._submit(self._status_probe(), timeout=_STATUS_TIMEOUT_S)
        except Exception:  # noqa: BLE001 (a probe failure must not break the status poll)
            logger.exception("BLE illumination status probe failed")
            return {
                "backend": self.name,
                "configured": configured,
                "connected": 0,
                "panels": [{"address": a, "connected": False} for a in self._addresses],
            }

    async def _status_probe(self) -> dict[str, Any]:
        """Try to (re)connect each panel and report which are reachable.

        Runs on the loop thread so all reads/writes of ``_clients`` stay single-threaded.
        Doubles as a warm-up: a connection opened here is reused by the next apply().
        """
        connected = 0
        panels = []
        for address in self._addresses:
            ok = False
            try:
                client = await self._ensure_connected(address)
                ok = bool(client.is_connected)
            except Exception:  # noqa: BLE001 (an unreachable panel is the case we report)
                self._clients.pop(address, None)
            panels.append({"address": address, "connected": ok})
            if ok:
                connected += 1
        return {
            "backend": self.name,
            "configured": len(self._addresses),
            "connected": connected,
            "panels": panels,
        }

    def _broadcast(self, payload: bytes) -> None:
        """Send one command to every panel; record it as the last-applied on success."""
        try:
            self._submit(self._write_all(payload), timeout=_WRITE_TIMEOUT_S)
            self._last_payload = payload
        except Exception:  # noqa: BLE001 (a panel error must not break a capture)
            logger.exception("BLE illumination write failed")
            # Force a fresh attempt (and reconnect) on the next call.
            self._last_payload = None

    async def _ensure_connected(self, address: str) -> Any:
        client = self._clients.get(address)
        if client is not None and client.is_connected:
            return client
        client = self._BleakClient(address)
        await client.connect()
        self._clients[address] = client
        return client

    async def _write_all(self, payload: bytes) -> None:
        for address in self._addresses:
            try:
                client = await self._ensure_connected(address)
                await client.write_gatt_char(COMMAND_CHAR_UUID, payload, response=False)
            except Exception:  # noqa: BLE001 (one bad panel shouldn't stop the others)
                logger.exception("BLE write to panel %s failed", address)
                self._clients.pop(address, None)  # drop so the next call reconnects

    def close(self) -> None:
        loop = getattr(self, "_loop", None)
        if loop is None or loop.is_closed():
            return
        try:
            self._submit(self._disconnect_all(), timeout=_WRITE_TIMEOUT_S)
        except Exception:  # noqa: BLE001
            logger.exception("BLE disconnect on shutdown failed")
        loop.call_soon_threadsafe(loop.stop)

    async def _disconnect_all(self) -> None:
        for client in list(self._clients.values()):
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                logger.exception("BLE disconnect failed")
        self._clients.clear()
