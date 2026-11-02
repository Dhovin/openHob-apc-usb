import pytest
from openhop_apc_ups.config import Settings
from openhop_apc_ups.ups.base import BaseUPSDriver, UPSData, UPSStatus
from openhop_apc_ups.ups.monitor import (
    EVENT_LOW_BATTERY,
    EVENT_POWER_LOST,
    EVENT_POWER_RESTORED,
    UpsMonitor,
)


class MockDriver(BaseUPSDriver):
    def __init__(self, data: UPSData) -> None:
        self.data = data

    async def connect(self) -> bool:
        return True

    async def read_status(self) -> UPSData:
        return self.data

    async def disconnect(self) -> None:
        pass


def make_data(status: str, status_enum: UPSStatus, bcharge: float, timeleft: float, linev: float) -> UPSData:
    return UPSData(
        model="APC Test",
        status=status,
        status_enum=status_enum,
        battery_charge_pct=bcharge,
        time_left_minutes=timeleft,
        line_voltage=linev,
        output_voltage=120.0,
        load_pct=15.0,
        battery_voltage=27.0,
        internal_temp_c=25.0,
        line_freq_hz=60.0,
        last_transfer_reason="None",
        serial_number="TEST",
        firmware="1.0",
        timestamp=1000.0,
        driver_type="test",
    )


@pytest.mark.asyncio
async def test_monitor_state_transitions():
    settings = Settings(
        driver="simulator",
        low_battery_threshold_percent=20.0,
        low_battery_threshold_minutes=5.0,
    )
    monitor = UpsMonitor(settings)

    events: list[tuple[str, UPSData]] = []
    monitor.add_listener(lambda ev, data: events.append((ev, data)))

    # 1. Initial poll: ONLINE
    data1 = make_data("ONLINE", UPSStatus.ONLINE, 100.0, 45.0, 120.0)
    driver = MockDriver(data1)
    monitor.driver = driver
    await monitor.poll_once()
    assert len(events) == 0

    # 2. Power lost: ONBATT
    data2 = make_data("ONBATT", UPSStatus.ON_BATTERY, 95.0, 40.0, 0.0)
    driver.data = data2
    await monitor.poll_once()
    assert len(events) == 1
    assert events[0][0] == EVENT_POWER_LOST

    # 3. Battery drops to critical: LOWBATT
    data3 = make_data("ONBATT LOWBATT", UPSStatus.LOW_BATTERY, 18.0, 4.0, 0.0)
    driver.data = data3
    await monitor.poll_once()
    assert len(events) == 2
    assert events[1][0] == EVENT_LOW_BATTERY

    # 4. Power restored: ONLINE
    data4 = make_data("ONLINE", UPSStatus.ONLINE, 22.0, 10.0, 121.0)
    driver.data = data4
    await monitor.poll_once()
    assert len(events) == 3
    assert events[2][0] == EVENT_POWER_RESTORED
