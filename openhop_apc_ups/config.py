"""Configuration loader and schema validation for openhop-apcups."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ConfigError(ValueError):
    """Raised when configuration validation fails."""


@dataclass(frozen=True)
class Settings:
    driver: str = "auto"  # "auto", "nis", "usb", "simulator"
    poll_interval_seconds: int = 10
    nis_host: str = "127.0.0.1"
    nis_port: int = 3551
    usb_vendor_id: str = "051d"
    usb_device_path: str | None = None
    simulation_mode: bool = False
    meshcore_enabled: bool = True
    meshcore_host: str = "127.0.0.1"
    meshcore_port: int = 5050
    meshcore_channel_idx: int = 0
    alert_on_power_loss: bool = True
    alert_on_power_restore: bool = True
    alert_on_low_battery: bool = True
    alert_on_outage_update: bool = True
    alert_on_overload: bool = True
    alert_on_replace_battery: bool = True
    alert_on_comm_lost: bool = True
    low_battery_threshold_percent: float = 25.0
    low_battery_threshold_minutes: float = 10.0
    outage_update_interval_seconds: int = 600
    telemetry_beacon_interval_seconds: int = 0
    respond_to_queries: bool = True
    query_trigger_words: tuple[str, ...] = ("!ups", "/ups", "ups", "ups status")
    direct_recipient_pubkey: str | None = None
    direct_recipient_name: str | None = None
    log_level: str = "INFO"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Settings:
        if not isinstance(data, dict):
            raise ConfigError("Configuration must be a JSON dictionary")

        driver = str(data.get("driver", "auto")).lower()
        if driver not in {"auto", "nis", "usb", "simulator"}:
            raise ConfigError(f"Invalid driver '{driver}': expected auto, nis, usb, or simulator")

        poll_interval = int(data.get("poll_interval_seconds", 10))
        if poll_interval < 1:
            raise ConfigError("poll_interval_seconds must be at least 1 second")

        nis_host = str(data.get("nis_host", "127.0.0.1")).strip()
        nis_port = int(data.get("nis_port", 3551))
        if not (1 <= nis_port <= 65535):
            raise ConfigError(f"Invalid nis_port {nis_port}: must be between 1 and 65535")

        usb_vendor_id = str(data.get("usb_vendor_id", "051d")).strip().lower()
        usb_device_path = data.get("usb_device_path")
        if usb_device_path is not None:
            usb_device_path = str(usb_device_path).strip() or None

        simulation_mode = bool(data.get("simulation_mode", False))

        meshcore_enabled = bool(data.get("meshcore_enabled", True))
        meshcore_host = str(data.get("meshcore_host", "127.0.0.1")).strip()
        meshcore_port = int(data.get("meshcore_port", 5050))
        if not (1 <= meshcore_port <= 65535):
            raise ConfigError(f"Invalid meshcore_port {meshcore_port}: must be between 1 and 65535")

        meshcore_channel_idx = int(data.get("meshcore_channel_idx", 0))
        if meshcore_channel_idx < 0:
            raise ConfigError("meshcore_channel_idx must be non-negative")

        alert_on_power_loss = bool(data.get("alert_on_power_loss", True))
        alert_on_power_restore = bool(data.get("alert_on_power_restore", True))
        alert_on_low_battery = bool(data.get("alert_on_low_battery", True))
        alert_on_outage_update = bool(data.get("alert_on_outage_update", True))
        alert_on_overload = bool(data.get("alert_on_overload", True))
        alert_on_replace_battery = bool(data.get("alert_on_replace_battery", True))
        alert_on_comm_lost = bool(data.get("alert_on_comm_lost", True))

        low_battery_threshold_percent = float(data.get("low_battery_threshold_percent", 25.0))
        if not (0.0 <= low_battery_threshold_percent <= 100.0):
            raise ConfigError("low_battery_threshold_percent must be between 0 and 100")

        low_battery_threshold_minutes = float(data.get("low_battery_threshold_minutes", 10.0))
        if low_battery_threshold_minutes < 0:
            raise ConfigError("low_battery_threshold_minutes must be non-negative")

        outage_update_interval_seconds = int(data.get("outage_update_interval_seconds", 600))
        if outage_update_interval_seconds < 0:
            raise ConfigError("outage_update_interval_seconds must be non-negative")

        telemetry_beacon_interval = int(data.get("telemetry_beacon_interval_seconds", 0))
        respond_to_queries = bool(data.get("respond_to_queries", True))

        raw_triggers = data.get("query_trigger_words", ("!ups", "/ups", "ups", "ups status"))
        if isinstance(raw_triggers, (list, tuple)):
            query_trigger_words = tuple(str(w).strip().lower() for w in raw_triggers if str(w).strip())
        else:
            query_trigger_words = ("!ups", "/ups", "ups", "ups status")

        log_level = str(data.get("log_level", "INFO")).upper()
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            log_level = "INFO"

        direct_recipient_pubkey = data.get("direct_recipient_pubkey")
        if direct_recipient_pubkey is not None:
            direct_recipient_pubkey = str(direct_recipient_pubkey).strip().lower()
            if not direct_recipient_pubkey:
                direct_recipient_pubkey = None
            else:
                try:
                    bytes.fromhex(direct_recipient_pubkey)
                except ValueError:
                    raise ConfigError(f"Invalid direct_recipient_pubkey '{direct_recipient_pubkey}': must be valid hex")
                if len(direct_recipient_pubkey) < 12:
                    raise ConfigError("direct_recipient_pubkey must be at least 6 bytes (12 hex characters)")

        direct_recipient_name = data.get("direct_recipient_name")
        if direct_recipient_name is not None:
            direct_recipient_name = str(direct_recipient_name).strip() or None

        return cls(
            driver=driver,
            poll_interval_seconds=poll_interval,
            nis_host=nis_host,
            nis_port=nis_port,
            usb_vendor_id=usb_vendor_id,
            usb_device_path=usb_device_path,
            simulation_mode=simulation_mode,
            meshcore_enabled=meshcore_enabled,
            meshcore_host=meshcore_host,
            meshcore_port=meshcore_port,
            meshcore_channel_idx=meshcore_channel_idx,
            alert_on_power_loss=alert_on_power_loss,
            alert_on_power_restore=alert_on_power_restore,
            alert_on_low_battery=alert_on_low_battery,
            alert_on_outage_update=alert_on_outage_update,
            alert_on_overload=alert_on_overload,
            alert_on_replace_battery=alert_on_replace_battery,
            alert_on_comm_lost=alert_on_comm_lost,
            low_battery_threshold_percent=low_battery_threshold_percent,
            low_battery_threshold_minutes=low_battery_threshold_minutes,
            outage_update_interval_seconds=outage_update_interval_seconds,
            telemetry_beacon_interval_seconds=telemetry_beacon_interval,
            respond_to_queries=respond_to_queries,
            query_trigger_words=query_trigger_words,
            direct_recipient_pubkey=direct_recipient_pubkey,
            direct_recipient_name=direct_recipient_name,
            log_level=log_level,
        )


def load_settings(data_dir: Path | None = None) -> Settings:
    """Load settings from OPENHOP_PLUGIN_DATA / config.json, or fallback to defaults."""
    if data_dir is None:
        data_env = os.environ.get("OPENHOP_PLUGIN_DATA")
        data_dir = Path(data_env) if data_env else Path.cwd()

    config_file = data_dir / "config.json"
    if config_file.is_file():
        try:
            raw = json.loads(config_file.read_text(encoding="utf-8"))
            logger.info("Loaded configuration from %s", config_file)
            return Settings.from_dict(raw)
        except Exception as exc:
            logger.warning("Failed to parse %s (%s); falling back to default configuration", config_file, exc)

    return Settings()
