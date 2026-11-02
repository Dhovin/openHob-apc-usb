// openHop APC UPS Dashboard Application
(function () {
  const RUNTIME_ENDPOINT = "/api/plugins/runtime?id=openhop.apcups";
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
      return (
        window.localStorage.getItem("pymc_jwt_token") ||
        window.localStorage.getItem("token") ||
        window.sessionStorage.getItem("pymc_jwt_token") ||
        ""
      );
    } catch (_) {
      return "";
    }
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

    if (minutesLeft !== undefined && minutesLeft !== null) {
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
      const headers = { Accept: "application/json" };
      const token = getJwtToken();
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }

      const resp = await fetch(RUNTIME_ENDPOINT, { headers, cache: "no-store" });
      if (resp.status === 401) {
        elStatusBadge.textContent = "Auth Required";
        elStatusBadge.className = "badge offline";
        console.warn("openHop runtime API returned 401 Unauthorized. Ensure you are logged into openHop or pass ?token=YOUR_TOKEN.");
        return;
      }
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
      }
      const raw = await resp.json();
      render(raw);
    } catch (err) {
      console.debug("Runtime API poll error:", err.message);
    }
  }

  function render(raw) {
    if (!raw) return;

    // openHop manager wraps plugin runtime under raw.runtime
    const data = raw.runtime || raw;

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
      elLoadPct.textContent = (ups.load_pct !== null && ups.load_pct !== undefined) ? `${ups.load_pct.toFixed(1)}%` : "--%";
      elBatteryVoltage.textContent = (ups.battery_voltage !== null && ups.battery_voltage !== undefined && ups.battery_voltage > 0)
        ? `${ups.battery_voltage.toFixed(1)} V`
        : "-- V";
      elInternalTemp.textContent = (ups.internal_temp_c !== null && ups.internal_temp_c !== undefined)
        ? `${ups.internal_temp_c.toFixed(1)} C`
        : "N/A";
      elDriverType.textContent = (ups.driver_type || "auto").toUpperCase();
    }

    updateEvents(data.events);
  }

  // Initial fetch and interval
  fetchTelemetry();
  setInterval(fetchTelemetry, POLL_INTERVAL_MS);
})();
