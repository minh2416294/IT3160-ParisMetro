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
    document.getElementById("input-start").value = "";
  } else if (clickMode === "end") {
    endPt = { lat, lng };
    setEndpointMarker("end", lat, lng);
    document.getElementById("end-coord").textContent = fmtCoord(lat, lng);
    document.getElementById("input-end").value = "";
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

function fmtDistance(meters) {
  if (meters >= 1000) return `${(meters / 1000).toFixed(2)} km`;
  return `${Math.round(meters)} m`;
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
  const totalDist = data.steps.reduce((sum, s) => sum + (s.distance_m || 0), 0);
  banner.textContent = `Total: ${fmtDuration(data.total_time_s)} · ${fmtDistance(totalDist)}`;

  stepsEl.innerHTML = "";
  for (const s of data.steps) {
    const li = document.createElement("li");
    li.className = `step step-${s.kind}`;
    if (s.line_id && (s.kind === "ride" || s.kind === "enter" || s.kind === "transfer")) {
      const badge = document.createElement("span");
      badge.className = "line-badge";
      badge.style.backgroundColor = colorForLine(s.line_id);
      badge.textContent = s.line_id;
      li.appendChild(badge);
    }
    const text = document.createElement("span");
    text.textContent = formatStepText(s);
    li.appendChild(text);
    stepsEl.appendChild(li);
  }
}

function formatStepText(s) {
  // enter/exit: hide time (they're short transitions)
  if (s.kind === "enter" || s.kind === "exit") return s.description;
  const parts = [s.description];
  const extras = [];
  if (s.distance_m && s.distance_m >= 1) extras.push(fmtDistance(s.distance_m));
  if (s.duration_s && s.duration_s >= 1) extras.push(fmtDuration(s.duration_s));
  if (extras.length) parts.push(`— ${extras.join(" · ")}`);
  return parts.join(" ");
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
  document.getElementById("input-start").value = "";
  document.getElementById("input-end").value = "";
  closeDropdown("dropdown-start");
  closeDropdown("dropdown-end");
  document.getElementById("result-banner").textContent = "";
  document.getElementById("result-banner").className = "";
  document.getElementById("result-steps").innerHTML = "";
}

function buildLineFilter() {
  const container = document.getElementById("line-toggles");
  if (!container) return;
  container.innerHTML = "";
  for (const lid of getAllLineIds()) {
    const label = document.createElement("label");
    label.className = "line-toggle";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = true;
    cb.addEventListener("change", () => setLineVisible(lid, cb.checked));
    const badge = document.createElement("span");
    badge.className = "line-badge";
    badge.style.backgroundColor = colorForLine(lid);
    badge.textContent = lid;
    label.appendChild(cb);
    label.appendChild(badge);
    container.appendChild(label);
  }
}

function setAllToggles(visible) {
  setAllLinesVisible(visible);
  const cbs = document.querySelectorAll("#line-toggles input[type=checkbox]");
  cbs.forEach((c) => (c.checked = visible));
}

function normalizeText(str) {
  return str.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();
}

function closeDropdown(dropdownId) {
  const el = document.getElementById(dropdownId);
  if (el) {
    el.innerHTML = "";
    el.classList.remove("open");
  }
}

function setupStationSearch(inputId, dropdownId, role) {
  const input = document.getElementById(inputId);
  const dropdown = document.getElementById(dropdownId);

  input.addEventListener("input", () => {
    const query = normalizeText(input.value.trim());
    dropdown.innerHTML = "";
    if (!query || !networkData) {
      dropdown.classList.remove("open");
      return;
    }

    const matches = networkData.stations
      .filter((st) => normalizeText(st.name).includes(query))
      .sort((a, b) => {
        const aN = normalizeText(a.name).startsWith(query) ? 0 : 1;
        const bN = normalizeText(b.name).startsWith(query) ? 0 : 1;
        return aN - bN || a.name.localeCompare(b.name);
      })
      .slice(0, 8);

    if (matches.length === 0) {
      dropdown.classList.remove("open");
      return;
    }

    for (const st of matches) {
      const li = document.createElement("li");

      const name = document.createElement("span");
      name.textContent = st.name;
      li.appendChild(name);

      for (const lid of st.lines) {
        const badge = document.createElement("span");
        badge.className = "line-badge";
        badge.style.backgroundColor = colorForLine(lid);
        badge.textContent = lid;
        li.appendChild(badge);
      }

      li.addEventListener("mousedown", (e) => {
        e.preventDefault();
        input.value = st.name;
        dropdown.classList.remove("open");
        dropdown.innerHTML = "";

        const coordSpanId = role === "start" ? "start-coord" : "end-coord";
        if (role === "start") {
          startPt = { lat: st.lat, lng: st.lng };
          setEndpointMarker("start", st.lat, st.lng);
        } else {
          endPt = { lat: st.lat, lng: st.lng };
          setEndpointMarker("end", st.lat, st.lng);
        }
        document.getElementById(coordSpanId).textContent = fmtCoord(st.lat, st.lng);
        setClickMode(null);
      });

      dropdown.appendChild(li);
    }

    dropdown.classList.add("open");
  });

  input.addEventListener("blur", () => {
    setTimeout(() => {
      dropdown.classList.remove("open");
      dropdown.innerHTML = "";
    }, 150);
  });

  input.addEventListener("focus", () => {
    if (input.value.trim()) input.dispatchEvent(new Event("input"));
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  initMap("map");
  map.on("click", onMapClick);

  document.getElementById("btn-pick-start").addEventListener("click", () => setClickMode("start"));
  document.getElementById("btn-pick-end").addEventListener("click", () => setClickMode("end"));
  document.getElementById("btn-find").addEventListener("click", findPath);
  document.getElementById("btn-reset").addEventListener("click", resetSelection);
  document.getElementById("btn-show-all-lines").addEventListener("click", () => setAllToggles(true));
  document.getElementById("btn-hide-all-lines").addEventListener("click", () => setAllToggles(false));

  try {
    await loadNetwork();
    buildLineFilter();
    setupStationSearch("input-start", "dropdown-start", "start");
    setupStationSearch("input-end", "dropdown-end", "end");
  } catch (e) {
    const banner = document.getElementById("result-banner");
    banner.className = "error";
    banner.textContent = `Failed to load network: ${e.message}`;
  }
  loadDisruptionBanner();
});
