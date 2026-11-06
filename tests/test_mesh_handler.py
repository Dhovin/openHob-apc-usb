"""Tests for MeshHandler encrypted direct message alerting."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from openhop_apc_ups.config import Settings
from openhop_apc_ups.mesh.handler import MeshHandler
from openhop_apc_ups.ups.base import UPSData, UPSStatus
from openhop_apc_ups.ups.monitor import (
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


@pytest.mark.asyncio
async def test_mesh_handler_direct_alert_when_recipient_configured():
    settings = Settings.from_dict({
        "direct_recipient_pubkey": "7e554f70a1b2",
        "direct_recipient_name": "Dhovin-Phone",
        "meshcore_enabled": True,
    })
    monitor = UpsMonitor(settings)
    mesh_client = MagicMock()
    mesh_client.connected = True
    mesh_client.send_direct_text = AsyncMock(return_value=True)
    mesh_client.send_channel_text = AsyncMock()

    handler = MeshHandler(settings, monitor, mesh_client)

    test_data = UPSData(
        model="Back-UPS ES 600M1",
        status="ONBATT",
        status_enum=UPSStatus.ON_BATTERY,
        battery_charge_pct=85.0,
        time_left_minutes=350.0,
        line_voltage=0.0,
        output_voltage=120.0,
        load_pct=0.0,
        battery_voltage=12.5,
        internal_temp_c=None,
        line_freq_hz=None,
        last_transfer_reason="Power failure",
        serial_number="4B2116P11398",
        firmware="928.a8",
        timestamp=1000.0,
        driver_type="nis",
    )

    # Trigger event
    handler.on_ups_event(EVENT_POWER_LOST, test_data)

    # Allow async task to run
    await asyncio.sleep(0.01)

    # send_direct_text should be called with recipient prefix
    expected_prefix = bytes.fromhex("7e554f70a1b2")
    mesh_client.send_direct_text.assert_called_once()
    call_args = mesh_client.send_direct_text.call_args[0]
    assert call_args[0] == expected_prefix
    assert "AC Power Lost" in call_args[1]

    # send_channel_text must NOT be called (no public channel broadcasts)
    mesh_client.send_channel_text.assert_not_called()


@pytest.mark.asyncio
async def test_mesh_handler_skips_when_no_recipient_configured():
    settings = Settings.from_dict({
        "direct_recipient_pubkey": None,
        "meshcore_enabled": True,
    })
    monitor = UpsMonitor(settings)
    mesh_client = MagicMock()
    mesh_client.connected = True
    mesh_client.send_direct_text = AsyncMock()
    mesh_client.send_channel_text = AsyncMock()

    handler = MeshHandler(settings, monitor, mesh_client)

    test_data = UPSData(
        model="Back-UPS ES 600M1",
        status="ONLINE",
        status_enum=UPSStatus.ONLINE,
        battery_charge_pct=100.0,
        time_left_minutes=500.0,
        line_voltage=122.0,
        output_voltage=120.0,
        load_pct=0.0,
        battery_voltage=13.3,
        internal_temp_c=None,
        line_freq_hz=None,
        last_transfer_reason="None",
        serial_number="4B2116P11398",
        firmware="928.a8",
        timestamp=1000.0,
        driver_type="nis",
    )

    handler.on_ups_event(EVENT_POWER_RESTORED, test_data)
    await asyncio.sleep(0.01)

    # Neither direct text nor channel text should be called
    mesh_client.send_direct_text.assert_not_called()
    mesh_client.send_channel_text.assert_not_called()


@pytest.mark.asyncio
async def test_send_test_direct_alert():
    settings = Settings.from_dict({
        "direct_recipient_pubkey": "7e554f70a1b2",
        "direct_recipient_name": "Dhovin-Phone",
        "meshcore_enabled": True,
    })
    monitor = UpsMonitor(settings)
    mesh_client = MagicMock()
    mesh_client.connected = True
    mesh_client.send_direct_text = AsyncMock(return_value=True)

    handler = MeshHandler(settings, monitor, mesh_client)
    ok, msg = await handler.send_test_direct_alert()

    assert ok is True
    assert "Dhovin-Phone" in msg
    mesh_client.send_direct_text.assert_called_once()


@pytest.mark.asyncio
async def test_mesh_handler_targeted_events():
    settings = Settings.from_dict({
        "direct_recipient_pubkey": "7e554f70a1b2",
        "meshcore_enabled": True,
    })
    monitor = UpsMonitor(settings)
    mesh_client = MagicMock()
    mesh_client.connected = True
    mesh_client.send_direct_text = AsyncMock(return_value=True)

    handler = MeshHandler(settings, monitor, mesh_client)

    test_data = UPSData(
        model="Back-UPS ES 600M1",
        status="ONLINE",
        status_enum=UPSStatus.ONLINE,
        battery_charge_pct=85.0,
        time_left_minutes=350.0,
        line_voltage=120.0,
        output_voltage=120.0,
        load_pct=105.0,
        battery_voltage=12.5,
        internal_temp_c=None,
        line_freq_hz=None,
        last_transfer_reason="None",
        serial_number="4B2116P11398",
        firmware="928.a8",
        timestamp=1000.0,
        driver_type="nis",
    )

    # 1. EVENT_OUTAGE_UPDATE
    handler.on_ups_event(EVENT_OUTAGE_UPDATE, test_data, "Outage ongoing (10m on battery). Battery: 85%")
    await asyncio.sleep(0.01)
    call_msg = mesh_client.send_direct_text.call_args[0][1]
    assert "[UPS UPDATE]" in call_msg
    assert "10m on battery" in call_msg

    # 2. EVENT_OVERLOAD
    mesh_client.send_direct_text.reset_mock()
    handler.on_ups_event(EVENT_OVERLOAD, test_data)
    await asyncio.sleep(0.01)
    call_msg = mesh_client.send_direct_text.call_args[0][1]
    assert "[UPS CRITICAL] Overload Detected!" in call_msg

    # 3. EVENT_REPLACE_BATTERY
    mesh_client.send_direct_text.reset_mock()
    handler.on_ups_event(EVENT_REPLACE_BATTERY, test_data)
    await asyncio.sleep(0.01)
    call_msg = mesh_client.send_direct_text.call_args[0][1]
    assert "[UPS ALERT] Battery Replacement Needed" in call_msg

    # 4. EVENT_COMM_LOST
    mesh_client.send_direct_text.reset_mock()
    handler.on_ups_event(EVENT_COMM_LOST, test_data)
    await asyncio.sleep(0.01)
    call_msg = mesh_client.send_direct_text.call_args[0][1]
    assert "[UPS WARNING] Communication Lost with UPS!" in call_msg


@pytest.mark.asyncio
async def test_beacon_loop_silent_when_interval_zero():
    settings = Settings.from_dict({
        "direct_recipient_pubkey": "7e554f70a1b2",
        "telemetry_beacon_interval_seconds": 0,
        "meshcore_enabled": True,
    })
    monitor = UpsMonitor(settings)
    mesh_client = MagicMock()
    mesh_client.connected = True
    mesh_client.send_direct_text = AsyncMock()

    handler = MeshHandler(settings, monitor, mesh_client)
    stop_event = asyncio.Event()

    # run_beacon_loop should return immediately
    await handler.run_beacon_loop(stop_event)
    mesh_client.send_direct_text.assert_not_called()
