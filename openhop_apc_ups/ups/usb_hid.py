"""Direct USB HID detection and diagnostics for APC UPS devices.

Targets APC USB devices (Vendor ID 0x051d - American Power Conversion).
Scans Linux sysfs (/sys/bus/usb/devices), /sys/class/power_supply, /dev/usb/hiddev*, and optional hidapi/pyusb.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

from .base import BaseUPSDriver, UPSData, UPSStatus

logger = logging.getLogger(__name__)

APC_USB_VENDOR_ID = 0x051D
APC_USB_VENDOR_ID_HEX = "051d"


def find_apc_sysfs_device() -> dict[str, str] | None:
    """Scan Linux /sys/bus/usb/devices for an APC USB UPS (VID 0x051d)."""
    sysfs_usb = Path("/sys/bus/usb/devices")
    if not sysfs_usb.is_dir():
        return None

    try:
        for dev_path in sysfs_usb.iterdir():
            vendor_file = dev_path / "idVendor"
            if not vendor_file.is_file():
                continue
            try:
                vid = vendor_file.read_text(encoding="utf-8").strip().lower()
                if vid == APC_USB_VENDOR_ID_HEX:
                    product_file = dev_path / "product"
                    product = product_file.read_text(encoding="utf-8").strip() if product_file.is_file() else "APC USB UPS"

                    mfg_file = dev_path / "manufacturer"
                    mfg = mfg_file.read_text(encoding="utf-8").strip() if mfg_file.is_file() else "American Power Conversion"

                    serial_file = dev_path / "serial"
                    serial = serial_file.read_text(encoding="utf-8").strip() if serial_file.is_file() else ""

                    pid_file = dev_path / "idProduct"
                    pid = pid_file.read_text(encoding="utf-8").strip() if pid_file.is_file() else "0002"

                    return {
                        "path": str(dev_path),
                        "vendor_id": vid,
                        "product_id": pid,
                        "product": product,
                        "manufacturer": mfg,
                        "serial": serial,
                    }
            except (OSError, PermissionError):
                continue
    except Exception as exc:
        logger.debug("Error scanning sysfs USB: %s", exc)

    return None


def find_linux_power_supply_ups() -> dict[str, Any] | None:
    """Scan /sys/class/power_supply for a UPS device node created by kernel hid-generic."""
    ps_dir = Path("/sys/class/power_supply")
    if not ps_dir.is_dir():
        return None

    try:
        for node in ps_dir.iterdir():
            type_file = node / "type"
            type_val = type_file.read_text().strip().upper() if type_file.is_file() else ""
            node_name = node.name.lower()
            if type_val == "UPS" or "051d" in node_name or "apc" in node_name:
                data: dict[str, Any] = {"path": str(node)}
                for prop in ("capacity", "status", "voltage_now", "time_to_empty_now", "model_name"):
                    f = node / prop
                    if f.is_file():
                        data[prop] = f.read_text().strip()
                return data
    except Exception as exc:
        logger.debug("Error scanning /sys/class/power_supply: %s", exc)

    return None


class DirectUsbHidDriver(BaseUPSDriver):
    """Direct USB interface for APC UPS devices."""

    def __init__(self, vendor_id: int = APC_USB_VENDOR_ID, device_path: str | None = None) -> None:
        self.vendor_id = vendor_id
        self.device_path = device_path
        self._device = None
        self._sysfs_info: dict[str, str] | None = None
        self._connected = False

    async def connect(self) -> bool:
        """Attempt to locate and connect to the APC USB device."""
        # 1. Scan Linux sysfs
        sysfs = find_apc_sysfs_device()
        if sysfs:
            self._sysfs_info = sysfs
            self._connected = True
            logger.info(
                "Found APC USB device via sysfs: %s (%s) S/N: %s",
                sysfs["product"],
                sysfs["manufacturer"],
                sysfs["serial"] or "N/A",
            )
            return True

        # 2. Check for Linux hiddev nodes (/dev/usb/hiddev* or /dev/hiddev*)
        if os.name == "posix":
            candidate_paths = [
                "/dev/usb/hiddev0",
                "/dev/usb/hiddev1",
                "/dev/hiddev0",
                "/dev/hiddev1",
            ]
            for path in candidate_paths:
                if os.path.exists(path):
                    logger.info("Found Linux USB HID device node at %s", path)
                    self._connected = True
                    return True

        # 3. Try hidapi if installed
        try:
            import hid  # type: ignore

            devices = hid.enumerate(self.vendor_id, 0)
            if devices:
                target = devices[0]
                self._device = hid.device()
                self._device.open_path(target["path"])
                self._connected = True
                logger.info(
                    "Direct USB HID connected to APC device: %s (PID: %04x)",
                    target.get("product_string", "APC UPS"),
                    target.get("product_id", 0),
                )
                return True
        except ImportError:
            pass
        except Exception as exc:
            logger.debug("hidapi probe failed: %s", exc)

        # 4. Try pyusb if installed
        try:
            import usb.core  # type: ignore

            dev = usb.core.find(idVendor=self.vendor_id)
            if dev is not None:
                self._device = dev
                self._connected = True
                logger.info("Direct USB connected via pyusb to APC device (VID: %04x)", self.vendor_id)
                return True
        except ImportError:
            pass
        except Exception as exc:
            logger.debug("pyusb probe failed: %s", exc)

        self._connected = False
        return False

    async def read_status(self) -> UPSData:
        """Read telemetry for the detected APC USB device."""
        if not self._connected:
            raise RuntimeError("Direct USB driver is not connected")

        model = "APC Back-UPS (USB)"
        serial = ""
        if self._sysfs_info:
            model = self._sysfs_info.get("product") or model
            serial = self._sysfs_info.get("serial", "")

        # Default telemetry values when connected via raw USB HID
        battery_pct = 100.0
        status_str = "ONLINE (USB Connected - Start apcupsd for live telemetry)"
        status_enum = UPSStatus.ONLINE
        time_left = 30.0
        line_v = 120.0
        batt_v = 13.5  # Typical single 12V SLA battery in ES 600M1
        load_val = 0.0
        temp_val = None

        # Check if Linux kernel exposed power_supply metrics
        ps = find_linux_power_supply_ups()
        if ps:
            if "capacity" in ps:
                try:
                    battery_pct = float(ps["capacity"])
                except ValueError:
                    pass
            if "status" in ps:
                raw_st = ps["status"].upper()
                if "DISCHARG" in raw_st:
                    status_str = "ONBATT"
                    status_enum = UPSStatus.ON_BATTERY
                    line_v = 0.0
                elif "CHARG" in raw_st or "FULL" in raw_st:
                    status_str = "ONLINE"
                    status_enum = UPSStatus.ONLINE
            if "voltage_now" in ps:
                try:
                    # Linux voltage_now is in microvolts
                    batt_v = round(float(ps["voltage_now"]) / 1e6, 2)
                except ValueError:
                    pass
            if "time_to_empty_now" in ps:
                try:
                    # Linux time_to_empty_now is in seconds
                    time_left = round(float(ps["time_to_empty_now"]) / 60.0, 1)
                except ValueError:
                    pass

        return UPSData(
            model=model,
            status=status_str,
            status_enum=status_enum,
            battery_charge_pct=battery_pct,
            time_left_minutes=time_left,
            line_voltage=line_v,
            output_voltage=120.0,
            load_pct=load_val,
            battery_voltage=batt_v,
            internal_temp_c=temp_val,
            line_freq_hz=60.0,
            last_transfer_reason="None",
            serial_number=serial,
            firmware="USB-HID",
            timestamp=time.time(),
            driver_type="usb_hid",
        )

    async def disconnect(self) -> None:
        if self._device is not None:
            try:
                if hasattr(self._device, "close"):
                    self._device.close()
            except Exception:
                pass
            self._device = None
        self._connected = False
