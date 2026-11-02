"""MeshCore message handler, query responder, and alert dispatcher."""

from __future__ import annotations

import asyncio
import logging
import time

from ..config import Settings
from ..ups.base import UPSData, UPSStatus
from ..ups.monitor import EVENT_LOW_BATTERY, EVENT_POWER_LOST, EVENT_POWER_RESTORED, UpsMonitor
from .client import IncomingMessage, MeshCoreClient
from .text import clean_for_radio

logger = logging.getLogger(__name__)


class MeshHandler:
    """Dispatches UPS alerts and handles radio query commands."""

    def __init__(self, settings: Settings, monitor: UpsMonitor, mesh_client: MeshCoreClient) -> None:
        self.settings = settings
        self.monitor = monitor
        self.mesh_client = mesh_client
        self._last_beacon_time = time.time()

    async def on_incoming_message(self, msg: IncomingMessage) -> None:
        """Handle incoming MeshCore messages and answer UPS queries."""
        if not self.settings.respond_to_queries:
            return

        cleaned = clean_for_radio(msg.text).lower()
        matched = any(
            cleaned == trigger or cleaned.startswith(f"{trigger} ")
            for trigger in self.settings.query_trigger_words
        )

        if not matched:
            return

        current = self.monitor.current_data
        if current is None:
            reply = "[UPS] Status unavailable (monitoring initializing)"
        else:
            reply = current.format_mesh_summary()

        logger.info("Answering UPS radio query from %s: %s", msg.sender_prefix[:6].hex(), reply)

        if msg.is_direct:
            await self.mesh_client.send_direct_text(msg.sender_prefix, reply)
        elif msg.channel_idx is not None:
            await self.mesh_client.send_channel_text(msg.channel_idx, reply)
        else:
            await self.mesh_client.send_channel_text(self.settings.meshcore_channel_idx, reply)

    def on_ups_event(self, event_type: str, data: UPSData) -> None:
        """Schedule mesh broadcast for UPS state changes."""
        if not self.settings.meshcore_enabled or not self.mesh_client.connected:
            return

        if event_type == EVENT_POWER_LOST and self.settings.alert_on_power_loss:
            text = (
                f"[UPS ALERT] AC Power Lost! Running on UPS battery "
                f"({data.battery_charge_pct:.0f}%, ~{data.time_left_minutes:.0f}m runtime)"
            )
            asyncio.create_task(self._broadcast(text))

        elif event_type == EVENT_POWER_RESTORED and self.settings.alert_on_power_restore:
            text = (
                f"[UPS NOTICE] AC Power Restored. Line: {data.line_voltage:.0f}V. "
                f"Battery: {data.battery_charge_pct:.0f}% (charging)"
            )
            asyncio.create_task(self._broadcast(text))

        elif event_type == EVENT_LOW_BATTERY and self.settings.alert_on_low_battery:
            text = (
                f"[UPS CRITICAL] Battery Low: {data.battery_charge_pct:.0f}% "
                f"(~{data.time_left_minutes:.0f}m remaining)! Node shutdown imminent"
            )
            asyncio.create_task(self._broadcast(text))

    async def _broadcast(self, text: str) -> None:
        await self.mesh_client.send_channel_text(self.settings.meshcore_channel_idx, text)

    async def run_beacon_loop(self, stop_event: asyncio.Event) -> None:
        """Periodic telemetry beacon loop over MeshCore channel."""
        interval = self.settings.telemetry_beacon_interval_seconds
        if interval <= 0:
            return

        logger.info("MeshCore telemetry beacon enabled (interval=%ss)", interval)
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

            if stop_event.is_set():
                break

            if self.settings.meshcore_enabled and self.mesh_client.connected:
                data = self.monitor.current_data
                if data is not None and data.status_enum != UPSStatus.COMM_LOST:
                    beacon_text = f"[BEACON] {data.format_mesh_summary()}"
                    await self._broadcast(beacon_text)
