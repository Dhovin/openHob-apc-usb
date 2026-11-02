"""Atomic writer for OPENHOP_PLUGIN_DATA / runtime.json."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from ..config import Settings
from ..ups.base import UPSData
from ..ups.monitor import UpsMonitor

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

        payload: dict[str, Any] = {
            "plugin_id": "openhop.apcups",
            "updated_at": time.time(),
            "meshcore": {
                "enabled": settings.meshcore_enabled,
                "connected": mesh_connected,
                "host": settings.meshcore_host,
                "port": settings.meshcore_port,
                "channel_idx": settings.meshcore_channel_idx,
            },
            "ups": ups_dict,
            "events": monitor.recent_events,
            "history": monitor.history,
        }

        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            # Write to temporary file first then replace atomically
            temp_path = self.data_dir / f".runtime.{os.getpid()}.tmp"
            temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            temp_path.replace(self.runtime_file)
        except Exception as exc:
            logger.debug("Failed to write runtime.json: %s", exc)

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
