import pytest
from openhop_apc_ups.ups.base import UPSStatus
from openhop_apc_ups.ups.nis_client import (
    ApcNisClient,
    parse_apc_status_string,
    parse_float_prefix,
)


def test_parse_float_prefix():
    assert parse_float_prefix("120.4 Volts") == 120.4
    assert parse_float_prefix("100.0 Percent") == 100.0
    assert parse_float_prefix("45.0 Minutes") == 45.0
    assert parse_float_prefix("28.5 C") == 28.5
    assert parse_float_prefix("invalid") == 0.0
    assert parse_float_prefix("") == 0.0


def test_parse_apc_status_string():
    assert parse_apc_status_string("ONLINE") == UPSStatus.ONLINE
    assert parse_apc_status_string("ONLINE SLAVE") == UPSStatus.ONLINE
    assert parse_apc_status_string("ONBATT") == UPSStatus.ON_BATTERY
    assert parse_apc_status_string("ONBATT LOWBATT") == UPSStatus.LOW_BATTERY
    assert parse_apc_status_string("COMMLOST") == UPSStatus.COMM_LOST
    assert parse_apc_status_string("OVERLOAD") == UPSStatus.OVERLOAD


@pytest.mark.asyncio
async def test_nis_mock_response(monkeypatch):
    sample_records = {
        "APC": "001,036,0885",
        "MODEL": "Back-UPS RS 1500MS",
        "STATUS": "ONLINE",
        "LINEV": "121.2 Volts",
        "LOADPCT": "14.5 Percent",
        "BCHARGE": "100.0 Percent",
        "TIMELEFT": "48.0 Minutes",
        "OUTPUTV": "120.0 Volts",
        "ITEMP": "29.0 C",
        "BATTV": "27.2 Volts",
        "LASTXFER": "Automatic self test",
        "SERIALNO": "3B1234567890",
        "FIRMWARE": "868.w3.D",
    }

    client = ApcNisClient()

    async def mock_read_raw_status():
        return sample_records

    monkeypatch.setattr(client, "read_raw_status", mock_read_raw_status)

    data = await client.read_status()
    assert data.model == "Back-UPS RS 1500MS"
    assert data.status_enum == UPSStatus.ONLINE
    assert data.is_online is True
    assert data.is_on_battery is False
    assert data.battery_charge_pct == 100.0
    assert data.time_left_minutes == 48.0
    assert data.line_voltage == 121.2
    assert data.load_pct == 14.5
    assert data.internal_temp_c == 29.0
    assert data.serial_number == "3B1234567890"
