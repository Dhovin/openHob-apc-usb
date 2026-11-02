"""Atomic writer for OPENHOP_PLUGIN_DATA / runtime.json."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from ..config import Settings
from ..ups.base import UPSData
from ..ups.installer import is_apcupsd_installed
from ..ups.monitor import UpsMonitor
from ..ups.nis_client import ApcNisClient

logger = logging.getLogger(__name__)


class RuntimeWriter:
    """Publishes live UPS metrics to runtime.json for openHop web dashboard."""

    def __init__(self, data_dir: Path | None = None) -> None:
        if data_dir is None:
            data_env = os.environ.get("OPENHOP_PLUGIN_DATA")
            data_dir = Path(data_env) if data_env else Path.cwd()
        self.data_dir = data_dir
        self.runtime_file = self.data_dir / "runtime.json"

    def write_runtime(
        self,
        monitor: UpsMonitor,
        mesh_connected: bool,
        settings: Settings,
    ) -> None:
        """Atomically dump state into runtime.json."""
        current = monitor.current_data
        ups_dict = current.to_dict() if current is not None else None

        is_nis = isinstance(monitor.driver, ApcNisClient) and bool(
            getattr(monitor.driver, "_connected", True)
        )

        payload: dict[str, Any] = {
            "plugin_id": "openhop.apcups",
            "updated_at": time.time(),
            "meshcore": {
                "enabled": settings.meshcore_enabled,
                "connected": mesh_connected,
                "host": settings.meshcore_host,
                "port": settings.meshcore_port,
                "channel_idx": settings.meshcore_channel_idx,
                "direct_recipient_pubkey": settings.direct_recipient_pubkey,
                "direct_recipient_name": settings.direct_recipient_name,
            },
            "apcupsd": {
                "installed": is_apcupsd_installed(),
                "nis_connected": is_nis,
                "command": "sudo apt update && sudo apt install -y apcupsd && sudo sed -i 's/ISCONFIGURED=no/ISCONFIGURED=yes/' /etc/default/apcupsd && sudo systemctl restart apcupsd",
            },
            "ups": ups_dict,
            "events": monitor.recent_events,
            "history": monitor.history,
        }

        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            # 1. Write runtime.json atomically
            temp_path = self.data_dir / f".runtime.{os.getpid()}.tmp"
            temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            temp_path.replace(self.runtime_file)

            # 2. Publish _runtime into config.json (matches openHop Prometheus / settings standard)
            config_path = self.data_dir / "config.json"
            raw_cfg: dict[str, Any] = {}
            if config_path.is_file():
                try:
                    loaded = json.loads(config_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        raw_cfg = loaded
                except (OSError, ValueError):
                    raw_cfg = {}
            raw_cfg["_runtime"] = payload
            tmp_cfg = self.data_dir / f".config.{os.getpid()}.tmp"
            tmp_cfg.write_text(json.dumps(raw_cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            tmp_cfg.replace(config_path)
        except Exception as exc:
            logger.debug("Failed to write runtime / config snapshot: %s", exc)

    async def run(
        self,
        monitor: UpsMonitor,
        mesh_connected_fn: Any,
        settings: Settings,
        stop_event: Any,
        interval: float = 3.0,
    ) -> None:
        """Periodic background writer loop."""
        while not stop_event.is_set():
            connected = mesh_connected_fn() if callable(mesh_connected_fn) else bool(mesh_connected_fn)
            self.write_runtime(monitor, connected, settings)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
