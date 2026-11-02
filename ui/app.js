// openHop APC UPS Dashboard Application
(function () {
  "use strict";

  const RUNTIME_API = "/api/plugins/runtime?id=openhop.apcups";
  const SETTINGS_API = "/api/plugins/settings?id=openhop.apcups";
  const POLL_INTERVAL_MS = 2500;

  // DOM Elements
  const elStatusBadge = document.getElementById("status-badge");
  const elUpsModel = document.getElementById("ups-model");
  const elMeshDot = document.getElementById("mesh-dot");
  const elMeshLabel = document.getElementById("mesh-label");
  const elBatteryCharge = document.getElementById("battery-charge");
  const elProgressBar = document.getElementById("progress-bar");
  const elTimeLeft = document.getElementById("time-left");
  const elLineVoltage = document.getElementById("line-voltage");
  const elLoadPct = document.getElementById("load-pct");
  const elBatteryVoltage = document.getElementById("battery-voltage");
  const elInternalTemp = document.getElementById("internal-temp");
  const elEventsBody = document.getElementById("events-body");
  const elDriverType = document.getElementById("driver-type");

  // Notice banner elements
  const elNoticeBanner = document.getElementById("notice-banner");
  const elNoticeIcon = document.getElementById("notice-icon");
  const elNoticeTitle = document.getElementById("notice-title");
  const elNoticeMsg = document.getElementById("notice-msg");
  const elNoticeCmdBox = document.getElementById("notice-cmd-box");
  const elNoticeCmd = document.getElementById("notice-cmd");
  const elCopyCmdBtn = document.getElementById("copy-cmd-btn");

  function formatTime(timestamp) {
    if (!timestamp) return "-";
    const d = new Date(timestamp * 1000);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  function getJwtToken() {
    try {
      const urlParams = new URLSearchParams(window.location.search);
      const queryToken = urlParams.get("token");
      if (queryToken) {
        window.localStorage.setItem("pymc_jwt_token", queryToken);
        return queryToken;
      }
      if (window.localStorage.getItem("pymc_jwt_token")) {
        return window.localStorage.getItem("pymc_jwt_token");
      }
      if (window.localStorage.getItem("token")) {
        return window.localStorage.getItem("token");
      }
      if (window.sessionStorage.getItem("pymc_jwt_token")) {
        return window.sessionStorage.getItem("pymc_jwt_token");
      }
      if (window.parent && window.parent.localStorage) {
        return window.parent.localStorage.getItem("pymc_jwt_token") || "";
      }
    } catch (_) {}
    return "";
  }

  async function apiFetch(url, options = {}) {
    const headers = new Headers(options.headers || {});
    headers.set("Accept", "application/json");
    const token = getJwtToken();
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }
    return fetch(url, { ...options, headers, cache: "no-store" });
  }

  function showNotice(title, message, isWarn = false, cmd = null) {
    if (!elNoticeBanner) return;
    elNoticeBanner.classList.remove("hidden", "warn", "error");
    if (isWarn) elNoticeBanner.classList.add("warn");
    if (elNoticeIcon) elNoticeIcon.textContent = isWarn ? "⚠️" : "ℹ️";
    if (elNoticeTitle) elNoticeTitle.textContent = title;
    if (elNoticeMsg) elNoticeMsg.textContent = message;

    if (cmd && elNoticeCmdBox && elNoticeCmd) {
      elNoticeCmd.textContent = cmd;
      elNoticeCmdBox.classList.remove("hidden");
    } else if (elNoticeCmdBox) {
      elNoticeCmdBox.classList.add("hidden");
    }
  }

  function hideNotice() {
    if (elNoticeBanner) elNoticeBanner.classList.add("hidden");
  }

  function updateStatusBadge(statusEnum, rawStatus) {
    elStatusBadge.className = "badge";
    const s = (statusEnum || "UNKNOWN").toUpperCase();

    if (s === "ONLINE" || s.includes("ONLINE")) {
      elStatusBadge.textContent = "Online";
      elStatusBadge.classList.add("online");
    } else if (s === "ON_BATTERY" || s.includes("ONBATT")) {
      elStatusBadge.textContent = "On Battery";
      elStatusBadge.classList.add("on-battery");
    } else if (s === "LOW_BATTERY" || s.includes("LOWBATT")) {
      elStatusBadge.textContent = "Low Battery";
      elStatusBadge.classList.add("low-battery");
    } else {
      elStatusBadge.textContent = rawStatus || "Offline";
      elStatusBadge.classList.add("offline");
    }
  }

  function updateBatteryUI(chargePct, minutesLeft) {
    const charge = Math.round(chargePct || 0);
    elBatteryCharge.textContent = `${charge}%`;
    elProgressBar.style.width = `${Math.min(100, Math.max(0, charge))}%`;

    elBatteryCharge.className = "charge-value";
    elProgressBar.style.backgroundColor = "var(--accent-green)";

    if (charge <= 20) {
      elBatteryCharge.classList.add("critical");
      elProgressBar.style.backgroundColor = "var(--accent-red)";
    } else if (charge <= 35) {
      elBatteryCharge.classList.add("warning");
      elProgressBar.style.backgroundColor = "var(--accent-yellow)";
    }

    if (minutesLeft !== undefined && minutesLeft !== null && minutesLeft > 0) {
      elTimeLeft.textContent = `${Math.round(minutesLeft)} min`;
    } else {
      elTimeLeft.textContent = "-- min";
    }
  }

  function updateEvents(events) {
    if (!events || events.length === 0) {
      elEventsBody.innerHTML = `<tr><td colspan="4" class="empty-state">No power events recorded yet</td></tr>`;
      return;
    }

    const rows = events
      .slice(-10)
      .reverse()
      .map((ev) => {
        return `
          <tr>
            <td>${formatTime(ev.timestamp)}</td>
            <td><strong>${(ev.event || "").replace("_", " ").toUpperCase()}</strong></td>
            <td>${ev.message || "-"}</td>
            <td>${ev.battery_pct !== undefined ? ev.battery_pct + "%" : "-"}</td>
          </tr>
        `;
      })
      .join("");

    elEventsBody.innerHTML = rows;
  }

  async function fetchTelemetry() {
    try {
      // 1. Query runtime endpoint
      const resp = await apiFetch(RUNTIME_API);

      if (resp.status === 401) {
        showNotice(
          "Dashboard Authentication Required",
          "Your openHop session has expired or requires authentication. Please log in to the openHop Repeater web interface and launch the plugin from the Plugins manager.",
          true
        );
        elStatusBadge.textContent = "Auth Required";
        elStatusBadge.className = "badge offline";
        return;
      }

      let payload = null;
      if (resp.ok) {
        const json = await resp.json();
        // openHop manager returns { id, exists, runtime: { ... } }
        if (json && json.runtime && json.runtime.ups) {
          payload = json.runtime;
        } else if (json && json.ups) {
          payload = json;
        }
      }

      // 2. Fallback to settings endpoint if runtime endpoint has not initialized yet
      if (!payload) {
        const settingsResp = await apiFetch(SETTINGS_API);
        if (settingsResp.ok) {
          const sJson = await settingsResp.json();
          const cfg = (sJson && sJson.config) ? sJson.config : sJson;
          if (cfg && cfg._runtime && cfg._runtime.ups) {
            payload = cfg._runtime;
          }
        }
      }

      if (payload) {
        render(payload);
      }
    } catch (err) {
      console.debug("Runtime API poll error:", err.message);
    }
  }

  function render(data) {
    if (!data) return;

    // MeshCore indicator
    if (data.meshcore && data.meshcore.enabled) {
      if (data.meshcore.connected) {
        elMeshDot.classList.add("connected");
        elMeshLabel.textContent = `MeshCore (Port ${data.meshcore.port})`;
      } else {
        elMeshDot.classList.remove("connected");
        elMeshLabel.textContent = "MeshCore Disconnected (Radio Optional)";
      }
    } else {
      elMeshDot.classList.remove("connected");
      elMeshLabel.textContent = "Radio Alerts Disabled";
    }

    const ups = data.ups;
    if (ups) {
      elUpsModel.textContent = ups.model || "APC UPS";
      updateStatusBadge(ups.status_enum, ups.status);
      updateBatteryUI(ups.battery_charge_pct, ups.time_left_minutes);

      elLineVoltage.textContent = (ups.line_voltage !== null && ups.line_voltage !== undefined && ups.line_voltage > 0)
        ? `${ups.line_voltage.toFixed(1)} V`
        : "N/A";
      elLoadPct.textContent = (ups.load_pct !== null && ups.load_pct !== undefined && ups.load_pct > 0)
        ? `${ups.load_pct.toFixed(1)}%`
        : "--%";
      elBatteryVoltage.textContent = (ups.battery_voltage !== null && ups.battery_voltage !== undefined && ups.battery_voltage > 0)
        ? `${ups.battery_voltage.toFixed(1)} V`
        : "-- V";
      elInternalTemp.textContent = (ups.internal_temp_c !== null && ups.internal_temp_c !== undefined && ups.internal_temp_c > 0)
        ? `${ups.internal_temp_c.toFixed(1)} C`
        : "N/A";

      const driverMode = (ups.driver_type || "auto").toUpperCase();
      elDriverType.textContent = driverMode;

      // Turnkey helper guidance: if connected only via Direct USB sysfs and NIS is not connected yet
      const apcupsdInfo = data.apcupsd || {};
      if (!apcupsdInfo.nis_connected && (driverMode === "USB" || driverMode === "AUTO")) {
        const cmd = apcupsdInfo.command || "sudo apt update && sudo apt install -y apcupsd && sudo sed -i 's/ISCONFIGURED=no/ISCONFIGURED=yes/' /etc/default/apcupsd && sudo systemctl restart apcupsd";
        showNotice(
          "APC Back-UPS Hardware Detected on USB",
          "Your Back-UPS ES 600M1 was detected on USB! To unlock real-time battery % and electrical stats, ensure apcupsd is installed and active on your repeater host:",
          false,
          cmd
        );
      } else {
        hideNotice();
      }
    }

    updateEvents(data.events);
  }

  // Setup command copy button
  if (elCopyCmdBtn) {
    elCopyCmdBtn.addEventListener("click", async () => {
      if (!elNoticeCmd) return;
      try {
        await navigator.clipboard.writeText(elNoticeCmd.textContent.trim());
        elCopyCmdBtn.textContent = "Copied!";
        setTimeout(() => {
          elCopyCmdBtn.textContent = "Copy";
        }, 2000);
      } catch (_) {
        elCopyCmdBtn.textContent = "Copied!";
        setTimeout(() => {
          elCopyCmdBtn.textContent = "Copy";
        }, 2000);
      }
    });
  }

  // Initial fetch and interval
  fetchTelemetry();
  setInterval(fetchTelemetry, POLL_INTERVAL_MS);
})();
