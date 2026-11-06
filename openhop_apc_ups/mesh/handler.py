"""MeshCore message handler, query responder, and alert dispatcher."""

from __future__ import annotations

import asyncio
import logging
import time

from ..config import Settings
from ..ups.base import UPSData, UPSStatus
from ..ups.monitor import (
    EVENT_COMM_LOST,
    EVENT_COMM_RESTORED,
    EVENT_LOW_BATTERY,
    EVENT_OUTAGE_UPDATE,
    EVENT_OVERLOAD,
    EVENT_OVERLOAD_CLEARED,
    EVENT_POWER_LOST,
    EVENT_POWER_RESTORED,
    EVENT_REPLACE_BATTERY,
    UpsMonitor,
)
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

    def _get_recipient_prefix(self) -> bytes | None:
        """Extract at least 6 bytes from configured recipient public key hex."""
        if not self.settings.direct_recipient_pubkey:
            return None
        try:
            prefix = bytes.fromhex(self.settings.direct_recipient_pubkey)
            if len(prefix) >= 6:
                return prefix[:6]
        except ValueError:
            pass
        return None

    def on_ups_event(self, event_type: str, data: UPSData, message: str | None = None) -> None:
        """Schedule encrypted direct message alert for UPS state changes."""
        if not self.settings.meshcore_enabled or not self.mesh_client.connected:
            return

        recipient_prefix = self._get_recipient_prefix()
        if recipient_prefix is None:
            logger.info("UPS event '%s' occurred, but no direct recipient is configured (alerts muted).", event_type)
            return

        text: str | None = None
        if event_type == EVENT_POWER_LOST and self.settings.alert_on_power_loss:
            text = (
                f"[UPS ALERT] AC Power Lost! Running on UPS battery "
                f"({data.battery_charge_pct:.0f}%, ~{data.time_left_minutes:.0f}m runtime)"
            )
        elif event_type == EVENT_OUTAGE_UPDATE and self.settings.alert_on_outage_update:
            text = f"[UPS UPDATE] {message}" if message else (
                f"[UPS UPDATE] Outage ongoing. Battery: {data.battery_charge_pct:.0f}%, "
                f"~{data.time_left_minutes:.0f}m runtime remaining"
            )
        elif event_type == EVENT_POWER_RESTORED and self.settings.alert_on_power_restore:
            text = f"[UPS NOTICE] {message}" if message else (
                f"[UPS NOTICE] AC Power Restored. Line: {data.line_voltage:.0f}V. "
                f"Battery: {data.battery_charge_pct:.0f}% (charging)"
            )
        elif event_type == EVENT_LOW_BATTERY and self.settings.alert_on_low_battery:
            text = (
                f"[UPS CRITICAL] Battery Low: {data.battery_charge_pct:.0f}% "
                f"(~{data.time_left_minutes:.0f}m remaining)! Node shutdown imminent"
            )
        elif event_type == EVENT_OVERLOAD and self.settings.alert_on_overload:
            text = f"[UPS CRITICAL] Overload Detected! UPS load: {data.load_pct:.0f}% exceeds capacity! Reduce load immediately."
        elif event_type == EVENT_OVERLOAD_CLEARED and self.settings.alert_on_overload:
            text = f"[UPS NOTICE] UPS Overload Cleared. Load: {data.load_pct:.0f}%."
        elif event_type == EVENT_REPLACE_BATTERY and self.settings.alert_on_replace_battery:
            text = "[UPS ALERT] Battery Replacement Needed: UPS reported bad battery or failed self-test (Replace Battery flag set)."
        elif event_type == EVENT_COMM_LOST and self.settings.alert_on_comm_lost:
            text = "[UPS WARNING] Communication Lost with UPS! Daemon cannot communicate with UPS hardware."
        elif event_type == EVENT_COMM_RESTORED and self.settings.alert_on_comm_lost:
            text = f"[UPS NOTICE] Communication Restored with UPS hardware ({data.model})."

        if text is not None:
            asyncio.create_task(self._send_direct_alert(recipient_prefix, text))

    async def _send_direct_alert(self, recipient_prefix: bytes, text: str) -> None:
        success = await self.mesh_client.send_direct_text(recipient_prefix, text)
        if success:
            logger.info("Dispatched encrypted direct alert to %s: %s", recipient_prefix.hex(), text)
        else:
            logger.warning("Failed to dispatch encrypted direct alert to %s", recipient_prefix.hex())

    async def send_test_direct_alert(self) -> tuple[bool, str]:
        """Dispatch a test encrypted direct message to the configured recipient."""
        if not self.settings.meshcore_enabled:
            return False, "MeshCore radio is disabled in settings"
        if not self.mesh_client.connected:
            return False, "MeshCore Companion server is not connected"

        prefix = self._get_recipient_prefix()
        if prefix is None:
            return False, "No recipient selected. Please select a contact and click Save Recipient."

        name = self.settings.direct_recipient_name or prefix.hex()[:8]
        test_msg = f"[UPS TEST] Encrypted alert test from openHop APC UPS Monitor to {name}. Power monitoring is active."
        success = await self.mesh_client.send_direct_text(prefix, test_msg)
        if success:
            logger.info("Sent test encrypted direct message to %s (%s)", name, prefix.hex())
            return True, f"Test alert successfully sent to {name}"
        return False, f"Companion rejected direct message to {name}"

    async def run_beacon_loop(self, stop_event: asyncio.Event) -> None:
        """Periodic telemetry beacon loop sent only to configured direct recipient."""
        interval = self.settings.telemetry_beacon_interval_seconds
        if interval <= 0:
            logger.info("MeshCore periodic telemetry heartbeat beacon disabled (interval=0)")
            return

        recipient_prefix = self._get_recipient_prefix()
        if recipient_prefix is None:
            logger.info("MeshCore direct beacon disabled (no recipient configured)")
            return

        logger.info("MeshCore telemetry direct beacon enabled for %s (interval=%ss)", recipient_prefix.hex(), interval)
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
                    await self._send_direct_alert(recipient_prefix, beacon_text)
