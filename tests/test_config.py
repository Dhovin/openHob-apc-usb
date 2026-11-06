import pytest
from openhop_apc_ups.config import ConfigError, Settings, load_settings


def test_default_settings():
    s = Settings()
    assert s.driver == "auto"
    assert s.poll_interval_seconds == 10
    assert s.nis_host == "127.0.0.1"
    assert s.nis_port == 3551
    assert s.meshcore_enabled is True
    assert s.meshcore_port == 5050
    assert s.meshcore_channel_idx == 0
    assert s.alert_on_power_loss is True
    assert s.alert_on_power_restore is True
    assert s.alert_on_low_battery is True
    assert s.alert_on_outage_update is True
    assert s.alert_on_overload is True
    assert s.alert_on_replace_battery is True
    assert s.alert_on_comm_lost is True
    assert s.low_battery_threshold_percent == 25.0
    assert s.outage_update_interval_seconds == 600
    assert s.telemetry_beacon_interval_seconds == 0


def test_custom_settings():
    data = {
        "driver": "nis",
        "poll_interval_seconds": 5,
        "nis_host": "192.168.1.50",
        "nis_port": 3551,
        "meshcore_channel_idx": 1,
        "low_battery_threshold_percent": 30.0,
        "query_trigger_words": ["!ups", "!power"],
    }
    s = Settings.from_dict(data)
    assert s.driver == "nis"
    assert s.poll_interval_seconds == 5
    assert s.nis_host == "192.168.1.50"
    assert s.meshcore_channel_idx == 1
    assert s.low_battery_threshold_percent == 30.0
    assert "!power" in s.query_trigger_words


def test_invalid_driver():
    with pytest.raises(ConfigError, match="Invalid driver"):
        Settings.from_dict({"driver": "invalid_driver"})


def test_invalid_port():
    with pytest.raises(ConfigError, match="Invalid nis_port"):
        Settings.from_dict({"nis_port": 70000})


def test_invalid_interval():
    with pytest.raises(ConfigError, match="poll_interval_seconds must be at least 1"):
        Settings.from_dict({"poll_interval_seconds": 0})

    with pytest.raises(ConfigError, match="outage_update_interval_seconds must be non-negative"):
        Settings.from_dict({"outage_update_interval_seconds": -5})


def test_direct_recipient_settings():
    # 'p' is not valid hex -> raises ConfigError
    with pytest.raises(ConfigError, match="must be valid hex"):
        Settings.from_dict({"direct_recipient_pubkey": "4b2116p11398"})

    # Valid hex
    valid_s = Settings.from_dict({
        "direct_recipient_pubkey": "4b2116fa9812",
        "direct_recipient_name": "Operator Node",
    })
    assert valid_s.direct_recipient_pubkey == "4b2116fa9812"
    assert valid_s.direct_recipient_name == "Operator Node"

    # Hex too short (< 12 chars / 6 bytes)
    with pytest.raises(ConfigError, match="at least 6 bytes"):
        Settings.from_dict({"direct_recipient_pubkey": "4b2116"})
