"""Turnkey auto-installer and service supervisor for apcupsd on Linux."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_APCUPSD_CONF = """# apcupsd.conf auto-configured by openhop.apcups
UPSCABLE usb
UPSTYPE usb
DEVICE
LOCKFILE /var/lock
SCRIPTDIR /etc/apcupsd
PWRFAILDIR /etc/apcupsd
NOLOGINDIR /etc
ONBATTERYDELAY 6
BATTERYLEVEL 5
MINUTES 3
TIMEOUT 0
ANNOY 300
ANNOYDELAY 60
NOLOGON disable
KILLDELAY 0
NETSERVER on
NISIP 127.0.0.1
NISPORT 3551
EVENTSFILE /var/log/apcupsd.events
EVENTSFILEMAX 10
UPSCLASS standalone
UPSMODE disable
STATTIME 0
STATFILE /var/log/apcupsd.status
LOGSTATS off
DATATIME 0
"""


def is_apcupsd_installed() -> bool:
    """Check if apcupsd binary is present on the system."""
    for candidate in ("apcupsd", "/sbin/apcupsd", "/usr/sbin/apcupsd", "/usr/local/sbin/apcupsd"):
        if shutil.which(candidate) or Path(candidate).is_file():
            return True
    return False


def try_configure_apcupsd() -> bool:
    """Ensure /etc/apcupsd/apcupsd.conf has USB and NIS enabled."""
    conf_path = Path("/etc/apcupsd/apcupsd.conf")
    default_conf = Path("/etc/default/apcupsd")

    try:
        if conf_path.parent.is_dir():
            # If conf doesn't exist or is missing UPSCABLE usb, write default
            if not conf_path.is_file() or "UPSCABLE usb" not in conf_path.read_text(errors="ignore"):
                conf_path.write_text(DEFAULT_APCUPSD_CONF, encoding="utf-8")
                logger.info("Configured /etc/apcupsd/apcupsd.conf for USB monitoring")

        # In Debian/Ubuntu, /etc/default/apcupsd requires ISCONFIGURED=yes
        if default_conf.is_file():
            content = default_conf.read_text(errors="ignore")
            if "ISCONFIGURED=no" in content:
                default_conf.write_text(content.replace("ISCONFIGURED=no", "ISCONFIGURED=yes"), encoding="utf-8")
                logger.info("Updated /etc/default/apcupsd: ISCONFIGURED=yes")
        return True
    except (PermissionError, OSError) as exc:
        logger.debug("Could not modify /etc/apcupsd/ (insufficient permissions): %s", exc)
        return False


def try_start_apcupsd() -> bool:
    """Try various methods to start apcupsd if stopped."""
    # 1. systemctl
    for cmd in (
        ["systemctl", "start", "apcupsd"],
        ["sudo", "-n", "systemctl", "start", "apcupsd"],
        ["service", "apcupsd", "start"],
        ["sudo", "-n", "service", "apcupsd", "start"],
    ):
        try:
            res = subprocess.run(cmd, capture_output=True, timeout=5)
            if res.returncode == 0:
                logger.info("Started apcupsd using: %s", " ".join(cmd))
                return True
        except Exception:
            continue

    # 2. Try running binary directly in background
    for binary in ("/sbin/apcupsd", "/usr/sbin/apcupsd", "apcupsd"):
        if shutil.which(binary) or Path(binary).is_file():
            for cmd in ([binary, "-b"], ["sudo", "-n", binary, "-b"]):
                try:
                    res = subprocess.run(cmd, capture_output=True, timeout=5)
                    if res.returncode == 0:
                        logger.info("Started %s in background", binary)
                        return True
                except Exception:
                    continue

    return False


def try_install_apcupsd() -> tuple[bool, str]:
    """Attempt turnkey installation of apcupsd via system package manager."""
    if os.name != "posix":
        return False, "Automated package installation is only supported on Linux"

    logger.info("Attempting turnkey installation of apcupsd...")

    # Check for Debian/Ubuntu apt-get
    if shutil.which("apt-get"):
        commands = [
            # Try without sudo first (e.g. root container)
            ["apt-get", "update", "-qq"],
            ["apt-get", "install", "-y", "-qq", "apcupsd"],
        ]
        sudo_commands = [
            # Try with passwordless sudo
            ["sudo", "-n", "apt-get", "update", "-qq"],
            ["sudo", "-n", "apt-get", "install", "-y", "-qq", "apcupsd"],
        ]

        for plan in (commands, sudo_commands):
            success = True
            for cmd in plan:
                try:
                    res = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
                    if res.returncode != 0:
                        success = False
                        break
                except Exception as exc:
                    success = False
                    break

            if success:
                logger.info("Successfully installed apcupsd via apt-get!")
                try_configure_apcupsd()
                try_start_apcupsd()
                return True, "Successfully installed and started apcupsd"

    # Check for Alpine apk
    elif shutil.which("apk"):
        for cmd in (["apk", "add", "--no-cache", "apcupsd"], ["sudo", "-n", "apk", "add", "--no-cache", "apcupsd"]):
            try:
                res = subprocess.run(cmd, capture_output=True, timeout=60)
                if res.returncode == 0:
                    logger.info("Successfully installed apcupsd via apk!")
                    try_configure_apcupsd()
                    try_start_apcupsd()
                    return True, "Successfully installed apcupsd"
            except Exception:
                continue

    return False, "Package manager requires root privileges. Run: sudo apt install apcupsd && sudo systemctl restart apcupsd"


def ensure_turnkey_apcupsd() -> tuple[bool, str]:
    """Check, configure, start, or install apcupsd automatically."""
    if is_apcupsd_installed():
        try_configure_apcupsd()
        started = try_start_apcupsd()
        if started:
            return True, "apcupsd is installed and started"
        return False, "apcupsd is installed but could not be started"

    return try_install_apcupsd()
