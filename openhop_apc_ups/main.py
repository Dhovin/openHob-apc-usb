"""Main service entrypoint for openhop-apc-ups."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from .config import load_settings
from .mesh.client import MeshCoreClient
from .mesh.handler import MeshHandler
from .ups.monitor import UpsMonitor
from .web.runtime_writer import RuntimeWriter

logger = logging.getLogger("openhop_apc_ups")


async def async_main() -> None:
    # Resolve plugin data directory
    data_dir_env = os.environ.get("OPENHOP_PLUGIN_DATA")
    data_dir = Path(data_dir_env) if data_dir_env else Path.cwd()

    settings = load_settings(data_dir)

    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )

    logger.info("Starting openHop APC UPS Monitor (PID: %s, data: %s)", os.getpid(), data_dir)

    stop_event = asyncio.Event()

    # Signal handlers for clean shutdown (POSIX & Windows compatible)
    def _sig_handler(*_: object) -> None:
        logger.info("Shutdown signal received, stopping service...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, _sig_handler)
    else:
        signal.signal(signal.SIGINT, _sig_handler)
        signal.signal(signal.SIGTERM, _sig_handler)

    # Initialize components
    monitor = UpsMonitor(settings)
    mesh_client = MeshCoreClient(host=settings.meshcore_host, port=settings.meshcore_port)
    mesh_handler = MeshHandler(settings, monitor, mesh_client)
    runtime_writer = RuntimeWriter(data_dir)

    # Connect monitor events to mesh handler
    monitor.add_listener(mesh_handler.on_ups_event)

    tasks: list[asyncio.Task] = []

    # 1. UPS monitor loop
    tasks.append(asyncio.create_task(monitor.run(stop_event), name="ups-monitor"))

    # 2. MeshCore client loop (if enabled)
    if settings.meshcore_enabled:
        tasks.append(
            asyncio.create_task(
                mesh_client.run(mesh_handler.on_incoming_message, stop_event),
                name="meshcore-client",
            )
        )
        tasks.append(
            asyncio.create_task(
                mesh_handler.run_beacon_loop(stop_event),
                name="meshcore-beacon",
            )
        )

    # 3. Runtime writer loop
    tasks.append(
        asyncio.create_task(
            runtime_writer.run(
                monitor,
                lambda: mesh_client.connected,
                settings,
                stop_event,
                interval=3.0,
            ),
            name="runtime-writer",
        )
    )

    logger.info("Service initialized. Running until termination signal...")

    # Wait for stop signal
    await stop_event.wait()

    logger.info("Cleaning up tasks and closing connections...")
    await mesh_client.close()

    for task in tasks:
        task.cancel()

    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info("Service stopped gracefully.")


def main() -> None:
    """Console script entrypoint."""
    try:
        asyncio.run(async_main())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
