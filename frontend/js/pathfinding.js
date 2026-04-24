// User-page controller: click start/end on map, fetch /api/path, render itinerary.

let clickMode = null; // "start" | "end" | null
let startPt = null;   // {lat, lng}
let endPt = null;

function setClickMode(mode) {
  clickMode = mode;
  updateModeButtons();
  document.getElementById("map").style.cursor = mode ? "crosshair" : "";
}

function updateModeButtons() {
  const sb = document.getElementById("btn-pick-start");
  const eb = document.getElementById("btn-pick-end");
  sb.classList.toggle("active", clickMode === "start");
  eb.classList.toggle("active", clickMode === "end");
}

function onMapClick(e) {
  if (!clickMode) return;
  const { lat, lng } = e.latlng;
  if (clickMode === "start") {
    startPt = { lat, lng };
    setEndpointMarker("start", lat, lng);
    document.getElementById("start-coord").textContent = fmtCoord(lat, lng);
  } else if (clickMode === "end") {
    endPt = { lat, lng };
    setEndpointMarker("end", lat, lng);
    document.getElementById("end-coord").textContent = fmtCoord(lat, lng);
  }
  setClickMode(null);
}

function fmtCoord(lat, lng) {
  return `${lat.toFixed(5)}, ${lng.toFixed(5)}`;
}

function fmtDuration(seconds) {
  const s = Math.round(seconds);
  const m = Math.floor(s / 60);
  const rem = s % 60;
  if (m === 0) return `${rem}s`;
  return `${m}m ${rem}s`;
}

async function findPath() {
  const banner = document.getElementById("result-banner");
  const stepsEl = document.getElementById("result-steps");
  banner.className = "";
  banner.textContent = "";
  stepsEl.innerHTML = "";

  if (!startPt || !endPt) {
    banner.className = "error";
    banner.textContent = "Pick a start point and an end point first.";
    return;
  }

  banner.textContent = "Searching...";
  try {
    const resp = await fetch(`${API_BASE}/api/path`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        lat_start: startPt.lat,
        lng_start: startPt.lng,
        lat_end: endPt.lat,
        lng_end: endPt.lng,
      }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: "Request failed" }));
      banner.className = "error";
      banner.textContent = err.detail || "No route found";
      clearRoute();
      return;
    }
    const data = await resp.json();
    renderItinerary(data);
    drawRoute(data.coords);
    setEndpointMarker("start", startPt.lat, startPt.lng);
    setEndpointMarker("end", endPt.lat, endPt.lng);
  } catch (e) {
    banner.className = "error";
    banner.textContent = `Error: ${e.message}`;
  }
}

function renderItinerary(data) {
  const banner = document.getElementById("result-banner");
  const stepsEl = document.getElementById("result-steps");
  banner.className = "success";
  banner.textContent = `Total: ${fmtDuration(data.total_time_s)}`;

  stepsEl.innerHTML = "";
  for (const s of data.steps) {
    const li = document.createElement("li");
    li.className = `step step-${s.kind}`;
    if (s.line_id) {
      const badge = document.createElement("span");
      badge.className = "line-badge";
      badge.style.backgroundColor = colorForLine(s.line_id);
      badge.textContent = s.line_id;
      li.appendChild(badge);
    }
    const text = document.createElement("span");
    text.textContent = `${s.description} (${fmtDuration(s.duration_s)})`;
    li.appendChild(text);
    stepsEl.appendChild(li);
  }
}

async function loadDisruptionBanner() {
  const el = document.getElementById("disruption-banner");
  try {
    const resp = await fetch(`${API_BASE}/api/scenarios`);
    if (!resp.ok) return;
    const scenarios = await resp.json();
    if (scenarios.length === 0) {
      el.style.display = "none";
      return;
    }
    el.style.display = "block";
    el.textContent = `${scenarios.length} active disruption${scenarios.length > 1 ? "s" : ""} — routes may differ.`;
  } catch {
    // ignore; banner stays hidden
  }
}

function resetSelection() {
  startPt = null;
  endPt = null;
  clearRoute();
  document.getElementById("start-coord").textContent = "—";
  document.getElementById("end-coord").textContent = "—";
  document.getElementById("result-banner").textContent = "";
  document.getElementById("result-banner").className = "";
  document.getElementById("result-steps").innerHTML = "";
}

document.addEventListener("DOMContentLoaded", async () => {
  initMap("map");
  map.on("click", onMapClick);

  document.getElementById("btn-pick-start").addEventListener("click", () => setClickMode("start"));
  document.getElementById("btn-pick-end").addEventListener("click", () => setClickMode("end"));
  document.getElementById("btn-find").addEventListener("click", findPath);
  document.getElementById("btn-reset").addEventListener("click", resetSelection);

  try {
    await loadNetwork();
  } catch (e) {
    const banner = document.getElementById("result-banner");
    banner.className = "error";
    banner.textContent = `Failed to load network: ${e.message}`;
  }
  loadDisruptionBanner();
});
