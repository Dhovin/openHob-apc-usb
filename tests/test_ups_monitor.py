import pytest
from openhop_apc_ups.config import Settings
from openhop_apc_ups.ups.base import BaseUPSDriver, UPSData, UPSStatus
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
    format_duration,
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


@pytest.mark.asyncio
async def test_outage_periodic_updates_and_duration():
    settings = Settings(
        driver="simulator",
        outage_update_interval_seconds=600,
    )
    monitor = UpsMonitor(settings)

    events: list[tuple[str, UPSData, str]] = []
    monitor.add_listener(lambda ev, data, msg="": events.append((ev, data, msg)))

    # 1. Start ONLINE at t=1000
    driver = MockDriver(make_data("ONLINE", UPSStatus.ONLINE, 100.0, 45.0, 120.0))
    monitor.driver = driver
    await monitor.poll_once()

    # 2. Power lost at t=1000
    driver.data = make_data("ONBATT", UPSStatus.ON_BATTERY, 98.0, 44.0, 0.0)
    await monitor.poll_once()
    assert len(events) == 1
    assert events[0][0] == EVENT_POWER_LOST
    outage_start = monitor._outage_start_time

    # 3. Time advances 300s (5 min) -> no periodic update yet
    monitor._last_outage_update_time = outage_start
    # simulate now is outage_start + 300
    import time
    orig_time = time.time
    try:
        time.time = lambda: outage_start + 300
        await monitor.poll_once()
        assert len(events) == 1

        # 4. Time advances to outage_start + 601s (10 min) -> triggers EVENT_OUTAGE_UPDATE
        time.time = lambda: outage_start + 601
        driver.data = make_data("ONBATT", UPSStatus.ON_BATTERY, 85.0, 38.0, 0.0)
        await monitor.poll_once()
        assert len(events) == 2
        assert events[1][0] == EVENT_OUTAGE_UPDATE
        assert "Outage ongoing (10m on battery)" in events[1][2]

        # 5. Power restored at outage_start + 900s (15 min) -> duration in message
        time.time = lambda: outage_start + 900
        driver.data = make_data("ONLINE", UPSStatus.ONLINE, 88.0, 40.0, 120.0)
        await monitor.poll_once()
        assert len(events) == 3
        assert events[2][0] == EVENT_POWER_RESTORED
        assert "Outage duration: 15m" in events[2][2]
        assert monitor._outage_start_time is None
    finally:
        time.time = orig_time


@pytest.mark.asyncio
async def test_overload_and_clear_transitions():
    settings = Settings(driver="simulator")
    monitor = UpsMonitor(settings)
    events: list[str] = []
    monitor.add_listener(lambda ev, data, msg="": events.append(ev))

    driver = MockDriver(make_data("ONLINE", UPSStatus.ONLINE, 100.0, 45.0, 120.0))
    monitor.driver = driver
    await monitor.poll_once()

    # Enter overload
    overload_data = make_data("ONLINE OVERLOAD", UPSStatus.OVERLOAD, 100.0, 45.0, 120.0)
    driver.data = overload_data
    await monitor.poll_once()
    assert events == [EVENT_OVERLOAD]

    # Clears overload
    driver.data = make_data("ONLINE", UPSStatus.ONLINE, 100.0, 45.0, 120.0)
    await monitor.poll_once()
    assert events == [EVENT_OVERLOAD, EVENT_OVERLOAD_CLEARED]


@pytest.mark.asyncio
async def test_replace_battery_transition():
    settings = Settings(driver="simulator")
    monitor = UpsMonitor(settings)
    events: list[str] = []
    monitor.add_listener(lambda ev, data, msg="": events.append(ev))

    driver = MockDriver(make_data("ONLINE", UPSStatus.ONLINE, 100.0, 45.0, 120.0))
    monitor.driver = driver
    await monitor.poll_once()

    # Battery needs replacement
    driver.data = make_data("ONLINE REPLACEBATT", UPSStatus.ONLINE, 100.0, 45.0, 120.0)
    await monitor.poll_once()
    assert events == [EVENT_REPLACE_BATTERY]


@pytest.mark.asyncio
async def test_comm_lost_debounced_transition():
    settings = Settings(driver="simulator")
    monitor = UpsMonitor(settings)
    events: list[str] = []
    monitor.add_listener(lambda ev, data, msg="": events.append(ev))

    driver = MockDriver(make_data("ONLINE", UPSStatus.ONLINE, 100.0, 45.0, 120.0))
    monitor.driver = driver
    await monitor.poll_once()

    # 1st comm lost poll (debounced, should not trigger yet)
    comm_lost_data = make_data("COMMLOST", UPSStatus.COMM_LOST, 0.0, 0.0, 0.0)
    driver.data = comm_lost_data
    await monitor.poll_once()
    assert len(events) == 0

    # 2nd comm lost poll (triggers EVENT_COMM_LOST)
    await monitor.poll_once()
    assert events == [EVENT_COMM_LOST]

    # Recovers to ONLINE
    driver.data = make_data("ONLINE", UPSStatus.ONLINE, 100.0, 45.0, 120.0)
    await monitor.poll_once()
    assert events == [EVENT_COMM_LOST, EVENT_COMM_RESTORED]
