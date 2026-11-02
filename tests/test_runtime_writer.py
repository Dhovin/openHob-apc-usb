"""Unit tests for RuntimeWriter."""

import json
from pathlib import Path

from openhop_apc_ups.config import Settings
from openhop_apc_ups.ups.base import UPSData, UPSStatus
from openhop_apc_ups.ups.monitor import UpsMonitor
from openhop_apc_ups.web.runtime_writer import RuntimeWriter


def test_runtime_writer_outputs(tmp_path: Path) -> None:
    settings = Settings()
    monitor = UpsMonitor(settings)

    test_data = UPSData(
        model="Back-UPS ES 600M1",
        status="ONLINE",
        status_enum=UPSStatus.ONLINE,
        battery_charge_pct=95.0,
        time_left_minutes=35.0,
        line_voltage=121.5,
        output_voltage=120.0,
        load_pct=15.0,
        battery_voltage=13.6,
        internal_temp_c=29.0,
        line_freq_hz=60.0,
        last_transfer_reason="Automatic",
        serial_number="4B12345678",
        firmware="928.a8",
        timestamp=1730000000.0,
        driver_type="nis",
    )
    monitor._current_data = test_data

    # Pre-create config.json to test _runtime enrichment
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"driver": "auto", "nis_port": 3551}), encoding="utf-8")

    writer = RuntimeWriter(data_dir=tmp_path)
    writer.write_runtime(monitor, mesh_connected=False, settings=settings)

    # 1. Verify runtime.json exists and has valid payload
    runtime_file = tmp_path / "runtime.json"
    assert runtime_file.is_file()
    runtime_data = json.loads(runtime_file.read_text(encoding="utf-8"))

    assert runtime_data["plugin_id"] == "openhop.apcups"
    assert runtime_data["ups"]["model"] == "Back-UPS ES 600M1"
    assert runtime_data["ups"]["battery_charge_pct"] == 95.0
    assert runtime_data["apcupsd"]["command"] is not None

    # 2. Verify config.json has _runtime injected without losing config keys
    config_data = json.loads(config_file.read_text(encoding="utf-8"))
    assert config_data["driver"] == "auto"
    assert "_runtime" in config_data
    assert config_data["_runtime"]["ups"]["battery_charge_pct"] == 95.0


async def test_runtime_writer_run_loop(tmp_path: Path) -> None:
    import asyncio
    settings = Settings()
    monitor = UpsMonitor(settings)
    writer = RuntimeWriter(data_dir=tmp_path)
    stop_event = asyncio.Event()

    task = asyncio.create_task(writer.run(monitor, False, settings, stop_event, interval=0.01))
    await asyncio.sleep(0.05)
    stop_event.set()
    await task

    runtime_file = tmp_path / "runtime.json"
    assert runtime_file.is_file()
