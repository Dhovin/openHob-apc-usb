# openHop APC UPS Monitor Plugin (`openhop.apcups`)

An official-specification plugin for **openHop Repeater** and **MeshCore** that connects to an **APC UPS via USB**, monitors battery and power telemetry, publishes live metrics to the Repeater web UI, and broadcasts alerts over the MeshCore LoRa radio mesh.

---

## Features

- **USB Connection to APC UPS:**
  - **APC NIS Engine (`apcupsd`):** Connects to `apcupsd` running on the host or container (`127.0.0.1:3551`), providing reliable USB HID monitoring for APC Back-UPS, Smart-UPS, and Pro models without requiring root privileges.
  - **Direct USB HID Engine:** Direct communication support for APC USB vendor ID `0x051d`.
  - **Simulation Mode:** Built-in battery discharge and power event simulator for testing without hardware.
- **MeshCore Radio Integration:**
  - **Automatic Broadcast Alerts:**
    - 🚨 **AC Power Loss Alert:** Broadcasts when utility power is lost (`[UPS ALERT] AC Power Lost! Running on UPS battery (85%, ~42m runtime)`).
    - ✅ **AC Power Restored Notice:** Broadcasts when power returns (`[UPS NOTICE] AC Power Restored. Line: 120V. Battery charging`).
    - ⚠️ **Critical Low Battery Warning:** Broadcasts when battery drops below threshold before node shutdown.
  - **Periodic Mesh Telemetry Beacon:** Optional compact single-line beacon over MeshCore channels.
  - **Interactive Mesh Queries:** Responds to radio queries like `!ups`, `/ups`, or `ups` with live status.
- **Modern Web Dashboard:**
  - Integrated into the openHop Repeater UI at `/plugins/openhop.apcups/`.
  - Displays real-time battery gauge, estimated runtime, utility line voltage, load percentage, internal temperature, and an event log.
- **Compliance with openHop Plugin Standards:**
  - Conforms to openHop Repeater **Schema 1** manifest and packaging guidelines.
  - Runs out-of-process with its own virtualenv and clean SIGTERM/SIGINT signal lifecycle handling.
  - Atomic `runtime.json` generation for the Repeater runtime endpoint (`GET /api/plugins/runtime?id=openhop.apcups`).

---

## Architecture

```
                  ┌──────────────────────────────────────────────┐
                  │               APC UPS (USB)                  │
                  └──────────────────────┬───────────────────────┘
                                         │ USB Cable
                  ┌──────────────────────▼───────────────────────┐
                  │   Host USB / apcupsd (port 3551) or HID      │
                  └──────────────────────┬───────────────────────┘
                                         │
┌────────────────────────────────────────▼────────────────────────────────────────┐
│                   openHop APC UPS Plugin (openhop.apcups)                       │
│                                                                                 │
│   ┌────────────────────┐   ┌─────────────────────┐   ┌──────────────────────┐   │
│   │   UPS Monitor      ├───►   Runtime Writer    ├───►  data/runtime.json   │   │
│   │ (State Transitions)│   │ (Atomic JSON Dumps) │   │ (Web UI Endpoint)    │   │
│   └─────────┬──────────┘   └─────────────────────┘   └──────────────────────┘   │
│             │                                                                   │
│             ▼                                                                   │
│   ┌────────────────────┐                                                        │
│   │  MeshCore Handler  │                                                        │
│   │ (Alerts & Queries) │                                                        │
│   └─────────┬──────────┘                                                        │
└─────────────┼───────────────────────────────────────────────────────────────────┘
              │ TCP Frame Protocol (port 5050)
┌─────────────▼───────────────────────────────────────────────────────────────────┐
│                      openHop Repeater Companion Daemon                          │
│                                     │                                           │
│                       MeshCore LoRa Radio Transceiver                           │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Connecting the APC UPS via USB

### Recommended Method: `apcupsd`

On Linux (Raspberry Pi OS, Debian, Ubuntu, etc.), `apcupsd` is the standard daemon for USB APC units:

1. Install `apcupsd`:
   ```bash
   sudo apt-get install apcupsd
   ```
2. Configure `/etc/apcupsd/apcupsd.conf`:
   ```conf
   UPSCABLE usb
   UPSTYPE usb
   DEVICE
   NETSERVER on
   NISIP 127.0.0.1
   NISPORT 3551
   ```
3. Restart `apcupsd`:
   ```bash
   sudo systemctl restart apcupsd
   ```
4. Verify with `apcaccess status`. The plugin will automatically connect to `127.0.0.1:3551`.

---

## Configuration

Settings are managed through the openHop Repeater plugin settings interface or in `<data>/config.json`:

```json
{
  "driver": "auto",
  "poll_interval_seconds": 10,
  "nis_host": "127.0.0.1",
  "nis_port": 3551,
  "usb_vendor_id": "051d",
  "usb_device_path": null,
  "simulation_mode": false,
  "meshcore_enabled": true,
  "meshcore_host": "127.0.0.1",
  "meshcore_port": 5050,
  "meshcore_channel_idx": 0,
  "alert_on_power_loss": true,
  "alert_on_power_restore": true,
  "alert_on_low_battery": true,
  "low_battery_threshold_percent": 25.0,
  "low_battery_threshold_minutes": 10.0,
  "telemetry_beacon_interval_seconds": 3600,
  "respond_to_queries": true,
  "query_trigger_words": ["!ups", "/ups", "ups", "ups status"],
  "log_level": "INFO"
}
```

### Configuration Options

| Key | Default | Description |
|---|---|---|
| `driver` | `"auto"` | `"auto"`, `"nis"`, `"usb"`, or `"simulator"` |
| `poll_interval_seconds` | `10` | Frequency in seconds to query UPS telemetry |
| `nis_host` | `"127.0.0.1"` | IP address of the `apcupsd` NIS server |
| `nis_port` | `3551` | TCP port of the NIS server |
| `meshcore_enabled` | `true` | Enable MeshCore radio integration |
| `meshcore_host` | `"127.0.0.1"` | Host address for Repeater Companion Frame Server |
| `meshcore_port` | `5050` | Port for Companion Frame Server |
| `meshcore_channel_idx` | `0` | MeshCore channel index for broadcast alerts |
| `alert_on_power_loss` | `true` | Broadcast radio alert when utility AC power is lost |
| `alert_on_power_restore`| `true` | Broadcast radio notice when utility power returns |
| `alert_on_low_battery` | `true` | Broadcast critical radio warning on low battery |
| `low_battery_threshold_percent` | `25.0` | Battery charge percentage to trigger critical alert |
| `low_battery_threshold_minutes` | `10.0` | Estimated runtime minutes to trigger critical alert |
| `telemetry_beacon_interval_seconds` | `3600` | Periodic telemetry beacon interval (0 to disable) |
| `respond_to_queries` | `true` | Answer incoming radio queries (`!ups`) |
| `query_trigger_words` | `["!ups", "/ups", "ups"]`| Triggers that prompt a status reply over radio |

---

## Building, Releases & Where `.whl` Files Are Saved

### 1. Local Builds
When building locally with:
```bash
python -m build --wheel
```
The resulting `.whl` package is saved in your local **`dist/`** directory:
```
dist/openhop_apcups_plugin-1.0.0-py3-none-any.whl
```

### 2. Automated GitHub Releases & Wheel Publishing
This repository includes an automated release workflow in [`.github/workflows/release.yml`](.github/workflows/release.yml):
- **On Tag Push:** Pushing any version tag (e.g. `git tag v1.0.0 && git push origin v1.0.0`) automatically:
  1. Runs all unit tests.
  2. Builds the `.whl` package.
  3. Validates the wheel structure against openHop contracts.
  4. Computes the cryptographic **SHA-256** digest.
  5. Publishes a new **GitHub Release** and uploads the `.whl` file as a release asset.
- **Manual Trigger:** You can also trigger a release directly from the GitHub web interface by going to **Actions** -> **Release Plugin Wheel** -> **Run workflow**, entering the tag name, and clicking Run.

The published wheel URL will be:
```text
https://github.com/Dhovin/openHob-apc-usb/releases/download/<tag>/openhop_apcups_plugin-<version>-py3-none-any.whl
```
This is the exact URL and SHA-256 digest format expected by the **openHop Plugin Catalogue** (`catalogue.json`).

---

### 3. Install on openHop Repeater

- **Via Web UI:** Open the openHop Repeater web dashboard, navigate to **Plugins**, and upload the `.whl` from the `dist/` directory.
- **Via API:**
  ```bash
  curl -X POST -H "Authorization: Bearer $TOKEN" \
    -F "wheel=@dist/openhop_apcups_plugin-1.0.0-py3-none-any.whl" \
    http://127.0.0.1:8000/api/plugins/install
  ```
- **Enable the plugin:**
  ```bash
  curl -X POST -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"id":"openhop.apcups"}' \
    http://127.0.0.1:8000/api/plugins/enable
  ```

---

## Running Unit Tests
```bash
python -m pytest
```

---

## License

MIT License. Open-source contribution for openHop and MeshCore communities.
