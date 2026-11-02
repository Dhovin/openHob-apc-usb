"""Base data models and abstract driver definition for APC UPS."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class UPSStatus(str, Enum):
    ONLINE = "ONLINE"                # Running on AC power
    ON_BATTERY = "ON_BATTERY"        # AC power lost, running on battery
    LOW_BATTERY = "LOW_BATTERY"      # Battery charge/runtime critically low
    CHARGING = "CHARGING"            # AC present, battery charging
    OVERLOAD = "OVERLOAD"            # Output load exceeded
    COMM_LOST = "COMM_LOST"          # Communication with UPS lost
    UNKNOWN = "UNKNOWN"              # Unknown / initializing


@dataclass(frozen=True)
class UPSData:
    model: str
    status: str                       # Raw status string (e.g., "ONLINE", "ONBATT", "ONLINE SLAVE")
    status_enum: UPSStatus
    battery_charge_pct: float         # 0.0 - 100.0%
    time_left_minutes: float          # Estimated runtime in minutes
    line_voltage: float               # Input AC line voltage (Volts)
    output_voltage: float             # Output AC voltage (Volts)
    load_pct: float                   # Load on UPS (0.0 - 100.0%)
    battery_voltage: float            # Internal battery bank voltage (Volts)
    internal_temp_c: float | None     # Temperature in Celsius (if supported)
    line_freq_hz: float | None        # Line frequency in Hz (if supported)
    last_transfer_reason: str         # e.g., "Low line voltage", "Automatic self test"
    serial_number: str
    firmware: str
    timestamp: float                  # Epoch timestamp of this reading
    driver_type: str                  # "nis", "usb_hid", "simulator"

    @property
    def is_on_battery(self) -> bool:
        """True if the UPS is running on battery."""
        return self.status_enum in {UPSStatus.ON_BATTERY, UPSStatus.LOW_BATTERY} or "ONBATT" in self.status

    @property
    def is_online(self) -> bool:
        """True if normal AC utility power is driving the load."""
        return "ONLINE" in self.status and not self.is_on_battery

    @property
    def is_low_battery(self) -> bool:
        """True if battery is flagged as low."""
        return self.status_enum == UPSStatus.LOW_BATTERY or "LOWBATT" in self.status

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status_enum"] = self.status_enum.value
        d["is_on_battery"] = self.is_on_battery
        d["is_online"] = self.is_online
        d["is_low_battery"] = self.is_low_battery
        return d

    def format_mesh_summary(self) -> str:
        """Compact single-line string optimized for low-bandwidth LoRa radio packets."""
        status_tag = self.status_enum.value
        batt = f"{self.battery_charge_pct:.0f}%"
        rem = f"{self.time_left_minutes:.0f}m"
        line = f"{self.line_voltage:.0f}V" if self.line_voltage > 0 else "0V"
        load = f"{self.load_pct:.0f}%"
        temp = f" {self.internal_temp_c:.0f}C" if self.internal_temp_c is not None else ""
        return f"[UPS] {status_tag} | Batt: {batt} ({rem}) | In: {line} | Load: {load}{temp}"


class BaseUPSDriver(ABC):
    """Abstract interface for APC UPS monitoring drivers."""

    @abstractmethod
    async def connect(self) -> bool:
        """Initialize or connect to the UPS. Returns True if successful."""
        ...

    @abstractmethod
    async def read_status(self) -> UPSData:
        """Fetch current telemetry and status from the UPS."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect or release resources."""
        ...
