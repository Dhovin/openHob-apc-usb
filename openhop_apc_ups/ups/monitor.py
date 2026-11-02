"""UPS Monitor Coordinator and State Machine.

Supervises driver polling, state transitions (online <-> on battery <-> low battery),
telemetry history, and event notification.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import struct
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..config import Settings
from .base import BaseUPSDriver, UPSData, UPSStatus
from .installer import ensure_turnkey_apcupsd
from .nis_client import ApcNisClient
from .simulator import UpsSimulator
from .usb_hid import DirectUsbHidDriver

logger = logging.getLogger(__name__)

EVENT_POWER_LOST = "power_lost"
EVENT_POWER_RESTORED = "power_restored"
EVENT_LOW_BATTERY = "low_battery"


def get_nis_candidate_hosts(primary_host: str) -> list[str]:
    """Return list of candidate hosts to probe for apcupsd NIS daemon.

    Checks primary_host first. If set to localhost/127.0.0.1, also checks Docker host
    candidates (default bridge gateway from /proc/net/route, 172.17.0.1, host.docker.internal)
    so plugins running inside containerized openHop can reach the host apcupsd.
    """
    hosts = [primary_host]
    if primary_host in ("127.0.0.1", "localhost"):
        candidates: list[str] = []
        try:
            route_path = Path("/proc/net/route")
            if route_path.is_file():
                for line in route_path.read_text().splitlines()[1:]:
                    fields = line.strip().split()
                    if len(fields) >= 3 and fields[1] == "00000000":
                        gw_hex = fields[2]
                        gw_ip = socket.inet_ntoa(struct.pack("<L", int(gw_hex, 16)))
                        if gw_ip not in candidates and gw_ip != "0.0.0.0":
                            candidates.append(gw_ip)
        except Exception:
            pass

        for default_cand in ("172.17.0.1", "host.docker.internal"):
            if default_cand not in candidates:
                candidates.append(default_cand)

        for c in candidates:
            if c not in hosts:
                hosts.append(c)
    return hosts


class UpsMonitor:
    """Supervises UPS driver polling and event lifecycle."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.driver: BaseUPSDriver | None = None
        self._current_data: UPSData | None = None
        self._previous_data: UPSData | None = None
        self._low_battery_alert_fired = False

        self._history: deque[dict[str, Any]] = deque(maxlen=60)
        self._events: deque[dict[str, Any]] = deque(maxlen=30)
        self._listeners: list[Callable[[str, UPSData], None]] = []
        self._last_nis_probe: float = time.time()

    def add_listener(self, listener: Callable[[str, UPSData], None]) -> None:
        self._listeners.append(listener)

    @property
    def current_data(self) -> UPSData | None:
        return self._current_data

    @property
    def history(self) -> list[dict[str, Any]]:
        return list(self._history)

    @property
    def recent_events(self) -> list[dict[str, Any]]:
        return list(self._events)

    async def initialize_driver(self) -> BaseUPSDriver:
        """Select and initialize driver according to configuration."""
        driver_mode = self.settings.driver.lower()

        if self.settings.simulation_mode or driver_mode == "simulator":
            logger.info("Using APC UPS Simulator driver")
            sim = UpsSimulator()
            await sim.connect()
            self.driver = sim
            return sim

        if driver_mode == "nis":
            client = ApcNisClient(host=self.settings.nis_host, port=self.settings.nis_port)
            connected = await client.connect()
            if not connected:
                logger.warning("Configured NIS daemon at %s:%s is not responding", self.settings.nis_host, self.settings.nis_port)
            self.driver = client
            return client

        if driver_mode == "usb":
            vid = int(self.settings.usb_vendor_id, 16) if self.settings.usb_vendor_id else 0x051D
            usb_driver = DirectUsbHidDriver(vendor_id=vid, device_path=self.settings.usb_device_path)
            connected = await usb_driver.connect()
            if not connected:
                logger.warning("Direct USB APC device not found")
            self.driver = usb_driver
            return usb_driver

        # "auto" mode: Try NIS first (apcupsd USB), then direct USB, fallback to simulator if nothing responds
        logger.info("Auto-detecting APC UPS connection...")
        candidate_hosts = get_nis_candidate_hosts(self.settings.nis_host)
        for cand_host in candidate_hosts:
            nis = ApcNisClient(host=cand_host, port=self.settings.nis_port)
            if await nis.connect():
                logger.info("Auto-detection selected APC NIS daemon at %s:%s (apcupsd USB)", cand_host, self.settings.nis_port)
                self.driver = nis
                return nis

        # Turnkey helper: try to start or install apcupsd automatically
        logger.info("APC NIS daemon not responding. Running turnkey apcupsd supervisor...")
        success, msg = ensure_turnkey_apcupsd()
        if success:
            logger.info("Turnkey supervisor: %s", msg)
            for cand_host in candidate_hosts:
                nis = ApcNisClient(host=cand_host, port=self.settings.nis_port)
                if await nis.connect():
                    logger.info("Connected to apcupsd NIS daemon at %s:%s following turnkey setup!", cand_host, self.settings.nis_port)
                    self.driver = nis
                    return nis
        else:
            logger.debug("Turnkey supervisor notice: %s", msg)

        vid = int(self.settings.usb_vendor_id, 16) if self.settings.usb_vendor_id else 0x051D
        usb_driver = DirectUsbHidDriver(vendor_id=vid, device_path=self.settings.usb_device_path)
        if await usb_driver.connect():
            logger.info("Auto-detection selected Direct USB HID")
            self.driver = usb_driver
            return usb_driver

        logger.warning(
            "No active APC UPS found on NIS (%s:%s) or USB sysfs/hiddev. "
            "To monitor via USB: 1) Ensure APC USB is plugged in, "
            "2) Start apcupsd (sudo apt install apcupsd && sudo systemctl start apcupsd), "
            "or set 'simulation_mode': true in plugin settings to test. Defaulting to NIS auto-reconnect.",
            self.settings.nis_host,
            self.settings.nis_port,
        )
        self.driver = nis
        return nis

    async def poll_once(self) -> UPSData | None:
        """Fetch status and trigger any state change events."""
        if self.driver is None:
            await self.initialize_driver()
        elif isinstance(self.driver, DirectUsbHidDriver) and (time.time() - self._last_nis_probe > 10.0):
            self._last_nis_probe = time.time()
            for cand_host in get_nis_candidate_hosts(self.settings.nis_host):
                nis = ApcNisClient(host=cand_host, port=self.settings.nis_port)
                if await nis.connect():
                    logger.info("APC NIS daemon (apcupsd) became available at %s:%s! Switching to live NIS telemetry.", cand_host, self.settings.nis_port)
                    self.driver = nis
                    break

        try:
            assert self.driver is not None
            data = await self.driver.read_status()
        except Exception as exc:
            logger.debug("UPS read error: %s", exc)
            now = time.time()
            data = UPSData(
                model="APC UPS (Communication Lost)",
                status="COMMLOST",
                status_enum=UPSStatus.COMM_LOST,
                battery_charge_pct=0.0,
                time_left_minutes=0.0,
                line_voltage=0.0,
                output_voltage=0.0,
                load_pct=0.0,
                battery_voltage=0.0,
                internal_temp_c=None,
                line_freq_hz=None,
                last_transfer_reason="Communication lost",
                serial_number="",
                firmware="",
                timestamp=now,
                driver_type=self.settings.driver,
            )

        self._previous_data = self._current_data
        self._current_data = data

        # Record history sample
        self._history.append({
            "timestamp": data.timestamp,
            "battery_charge_pct": data.battery_charge_pct,
            "time_left_minutes": data.time_left_minutes,
            "line_voltage": data.line_voltage,
            "load_pct": data.load_pct,
            "status": data.status_enum.value,
        })

        self._check_transitions(data)
        return data

    def _record_event(self, event_name: str, message: str, data: UPSData) -> None:
        entry = {
            "timestamp": time.time(),
            "event": event_name,
            "message": message,
            "battery_pct": data.battery_charge_pct,
            "runtime_min": data.time_left_minutes,
            "line_v": data.line_voltage,
        }
        self._events.append(entry)
        logger.info("[UPS EVENT] %s: %s", event_name, message)

        for listener in self._listeners:
            try:
                listener(event_name, data)
            except Exception as exc:
                logger.exception("Error in UPS event listener: %s", exc)

    def _check_transitions(self, data: UPSData) -> None:
        prev = self._previous_data
        if prev is None:
            return

        # Check for Power Loss
        if not prev.is_on_battery and data.is_on_battery:
            msg = f"Utility power lost! Running on battery ({data.battery_charge_pct:.0f}%, ~{data.time_left_minutes:.0f} min remaining)"
            self._record_event(EVENT_POWER_LOST, msg, data)

        # Check for Power Restored
        if prev.is_on_battery and not data.is_on_battery:
            self._low_battery_alert_fired = False
            msg = f"Utility power restored! Line voltage: {data.line_voltage:.0f}V, Battery: {data.battery_charge_pct:.0f}%"
            self._record_event(EVENT_POWER_RESTORED, msg, data)

        # Check for Low Battery warning
        is_low = (
            data.is_on_battery and (
                data.battery_charge_pct <= self.settings.low_battery_threshold_percent or
                data.time_left_minutes <= self.settings.low_battery_threshold_minutes or
                data.is_low_battery
            )
        )

        if is_low and not self._low_battery_alert_fired:
            self._low_battery_alert_fired = True
            msg = f"Low battery warning: {data.battery_charge_pct:.0f}% (~{data.time_left_minutes:.0f} min remaining)! Impending node shutdown"
            self._record_event(EVENT_LOW_BATTERY, msg, data)

    async def run(self, stop_event: asyncio.Event) -> None:
        """Continuous polling loop until stop_event is set."""
        logger.info("Starting UPS monitor polling loop (interval=%ss)...", self.settings.poll_interval_seconds)
        while not stop_event.is_set():
            await self.poll_once()
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self.settings.poll_interval_seconds)
            except asyncio.TimeoutError:
                pass

        if self.driver is not None:
            await self.driver.disconnect()
        logger.info("UPS monitor stopped")
