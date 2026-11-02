"""APC Network Information Server (NIS) Protocol Client.

Communicates with apcupsd over TCP (default 127.0.0.1:3551) to query
APC UPS metrics when connected via USB.
"""

from __future__ import annotations

import asyncio
import logging
import struct
import time
from typing import Any

from .base import BaseUPSDriver, UPSData, UPSStatus

logger = logging.getLogger(__name__)


def parse_apc_status_string(raw_status: str) -> UPSStatus:
    """Map APC raw status flags to UPSStatus enum."""
    s = raw_status.strip().upper()
    if "COMMLOST" in s:
        return UPSStatus.COMM_LOST
    if "OVERLOAD" in s:
        return UPSStatus.OVERLOAD
    if "LOWBATT" in s:
        return UPSStatus.LOW_BATTERY
    if "ONBATT" in s:
        return UPSStatus.ON_BATTERY
    if "ONLINE" in s:
        return UPSStatus.ONLINE
    if "CHARGING" in s:
        return UPSStatus.CHARGING
    return UPSStatus.UNKNOWN


def parse_float_prefix(val: str, default: float = 0.0) -> float:
    """Extract initial float from string like '121.4 Volts' or '100.0 Percent'."""
    val = val.strip()
    parts = val.split()
    if not parts:
        return default
    try:
        return float(parts[0])
    except ValueError:
        return default


class ApcNisClient(BaseUPSDriver):
    """Client for apcupsd NIS daemon (querying APC UPS USB interface)."""

    def __init__(self, host: str = "127.0.0.1", port: int = 3551, timeout: float = 5.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._connected = False

    async def connect(self) -> bool:
        """Test reachability of the apcupsd NIS service."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=self.timeout,
            )
            writer.close()
            await writer.wait_closed()
            self._connected = True
            logger.info("Connected to APC NIS daemon at %s:%s", self.host, self.port)
            return True
        except Exception as exc:
            self._connected = False
            logger.debug("APC NIS daemon not reachable at %s:%s (%s)", self.host, self.port, exc)
            return False

    async def read_raw_status(self) -> dict[str, str]:
        """Fetch raw key-value lines from NIS daemon."""
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port),
            timeout=self.timeout,
        )
        try:
            # Send NIS command 'status' with 2-byte big-endian length prefix
            cmd = b"status"
            writer.write(struct.pack("!H", len(cmd)) + cmd)
            await writer.drain()

            records: dict[str, str] = {}
            while True:
                len_bytes = await reader.readexactly(2)
                pkt_len = struct.unpack("!H", len_bytes)[0]
                if pkt_len == 0:
                    # End of transmission
                    break

                line_bytes = await reader.readexactly(pkt_len)
                line = line_bytes.decode("latin-1", errors="replace").strip()
                if ":" in line:
                    k, v = line.split(":", 1)
                    records[k.strip().upper()] = v.strip()

            return records
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def read_status(self) -> UPSData:
        """Query APC UPS telemetry and return structured UPSData."""
        raw = await self.read_raw_status()

        raw_status = raw.get("STATUS", "UNKNOWN")
        status_enum = parse_apc_status_string(raw_status)

        model = raw.get("MODEL", raw.get("UPSNAME", "APC USB UPS"))
        bcharge = parse_float_prefix(raw.get("BCHARGE", "0.0"))
        timeleft = parse_float_prefix(raw.get("TIMELEFT", "0.0"))
        linev = parse_float_prefix(raw.get("LINEV", "0.0"))
        outputv = parse_float_prefix(raw.get("OUTPUTV", str(linev)))
        loadpct = parse_float_prefix(raw.get("LOADPCT", "0.0"))
        battv = parse_float_prefix(raw.get("BATTV", "0.0"))

        itemp_raw = raw.get("ITEMP")
        itemp = parse_float_prefix(itemp_raw) if itemp_raw else None

        linefreq_raw = raw.get("LINEFREQ")
        linefreq = parse_float_prefix(linefreq_raw) if linefreq_raw else None

        last_transfer = raw.get("LASTXFER", "None")
        serial = raw.get("SERIALNO", "")
        firmware = raw.get("FIRMWARE", "")

        return UPSData(
            model=model,
            status=raw_status,
            status_enum=status_enum,
            battery_charge_pct=bcharge,
            time_left_minutes=timeleft,
            line_voltage=linev,
            output_voltage=outputv,
            load_pct=loadpct,
            battery_voltage=battv,
            internal_temp_c=itemp,
            line_freq_hz=linefreq,
            last_transfer_reason=last_transfer,
            serial_number=serial,
            firmware=firmware,
            timestamp=time.time(),
            driver_type="nis",
        )

    async def disconnect(self) -> None:
        self._connected = False
