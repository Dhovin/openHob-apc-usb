"""Simulator driver for APC UPS testing and development."""

from __future__ import annotations

import logging
import random
import time
from typing import Any

from .base import BaseUPSDriver, UPSData, UPSStatus

logger = logging.getLogger(__name__)


class UpsSimulator(BaseUPSDriver):
    """Simulates an APC Back-UPS Pro 1500 for testing without physical hardware."""

    def __init__(
        self,
        initial_charge: float = 100.0,
        initial_runtime: float = 45.0,
        simulate_outage: bool = False,
    ) -> None:
        self.battery_charge_pct = initial_charge
        self.time_left_minutes = initial_runtime
        self.simulate_outage = simulate_outage
        self.line_voltage = 0.0 if simulate_outage else 121.5
        self.output_voltage = 120.0
        self.load_pct = 18.0
        self.battery_voltage = 26.8
        self.internal_temp_c = 28.5
        self.last_update = time.time()
        self._connected = True

    async def connect(self) -> bool:
        self._connected = True
        logger.info("APC UPS Simulator initialized (simulate_outage=%s)", self.simulate_outage)
        return True

    def trigger_power_loss(self) -> None:
        """Trigger simulated utility power loss."""
        self.simulate_outage = True
        self.line_voltage = 0.0
        logger.warning("[SIMULATOR] Simulated AC power loss triggered!")

    def trigger_power_restore(self) -> None:
        """Trigger simulated utility power restoration."""
        self.simulate_outage = False
        self.line_voltage = 121.5
        logger.info("[SIMULATOR] Simulated AC power restoration triggered!")

    async def read_status(self) -> UPSData:
        now = time.time()
        dt = max(0.1, now - self.last_update)
        self.last_update = now

        # Fluctuate line voltage slightly if online
        if not self.simulate_outage:
            self.line_voltage = round(120.0 + random.uniform(-1.5, 1.5), 1)
            # Recharging
            if self.battery_charge_pct < 100.0:
                self.battery_charge_pct = min(100.0, self.battery_charge_pct + (dt * 0.5))
                self.time_left_minutes = min(45.0, (self.battery_charge_pct / 100.0) * 45.0)
            status_str = "ONLINE"
            status_enum = UPSStatus.ONLINE
            reason = "Automatic self test"
        else:
            self.line_voltage = 0.0
            # Discharging
            drain_rate = 0.2  # % per second for simulation
            self.battery_charge_pct = max(0.0, self.battery_charge_pct - (dt * drain_rate))
            self.time_left_minutes = max(0.0, (self.battery_charge_pct / 100.0) * 45.0)

            if self.battery_charge_pct <= 20.0:
                status_str = "ONBATT LOWBATT"
                status_enum = UPSStatus.LOW_BATTERY
            else:
                status_str = "ONBATT"
                status_enum = UPSStatus.ON_BATTERY
            reason = "Low line voltage"

        return UPSData(
            model="APC Back-UPS Pro 1500 (Simulated)",
            status=status_str,
            status_enum=status_enum,
            battery_charge_pct=round(self.battery_charge_pct, 1),
            time_left_minutes=round(self.time_left_minutes, 1),
            line_voltage=self.line_voltage,
            output_voltage=self.output_voltage,
            load_pct=round(self.load_pct + random.uniform(-0.5, 0.5), 1),
            battery_voltage=round(24.0 + (self.battery_charge_pct / 100.0) * 3.2, 2),
            internal_temp_c=round(self.internal_temp_c + random.uniform(-0.2, 0.2), 1),
            line_freq_hz=60.0 if not self.simulate_outage else 0.0,
            last_transfer_reason=reason,
            serial_number="SIM-APC-12345",
            firmware="SIM-FW-1.0",
            timestamp=now,
            driver_type="simulator",
        )

    async def disconnect(self) -> None:
        self._connected = False
