// Admin dashboard: login, scenario CRUD (close station/segment/line), list.

let adminMode = null; // "station" | "segment-a" | "segment-b" | null
let segmentFirst = null; // {station_id, line_id} while picking segment end

function showLogin() {
  document.getElementById("login-panel").style.display = "flex";
  document.getElementById("dashboard").style.display = "none";
}

function showDashboard() {
  document.getElementById("login-panel").style.display = "none";
  document.getElementById("dashboard").style.display = "grid";
}

async function handleLogin(e) {
  e.preventDefault();
  const errEl = document.getElementById("login-error");
  errEl.textContent = "";
  const u = document.getElementById("login-username").value.trim();
  const p = document.getElementById("login-password").value;
  try {
    await login(u, p);
    await initDashboard();
  } catch (err) {
    errEl.textContent = err.message;
  }
}

async function initDashboard() {
  showDashboard();
  initMap("map");
  await loadNetwork();
  wireStationClicks();
  populateLineDropdown();
  await refreshScenarios();
}

function wireStationClicks() {
  const data = getNetworkData();
  if (!data) return;
  for (const st of data.stations) {
    const marker = getStationMarker(st.id);
    if (!marker) continue;
    marker.on("click", () => onStationClick(st));
  }
}

function populateLineDropdown() {
  const data = getNetworkData();
  if (!data) return;
  const lines = new Set();
  for (const st of data.stations) for (const l of st.lines) lines.add(l);
  const sel = document.getElementById("line-select");
  sel.innerHTML = "";
  for (const l of [...lines].sort()) {
    const opt = document.createElement("option");
    opt.value = l;
    opt.textContent = `Line ${l}`;
    sel.appendChild(opt);
  }
  const selSeg = document.getElementById("segment-line-select");
  selSeg.innerHTML = sel.innerHTML;
}

function setAdminMode(mode) {
  adminMode = mode;
  segmentFirst = null;
  for (const id of ["btn-mode-station", "btn-mode-segment"]) {
    document.getElementById(id).classList.toggle("active", id === `btn-mode-${mode?.split("-")[0]}`);
  }
  const hint = document.getElementById("admin-hint");
  if (mode === "station") hint.textContent = "Click a station on the map to close it.";
  else if (mode === "segment-a") hint.textContent = "Pick the FIRST station of the segment.";
  else if (mode === "segment-b") hint.textContent = "Now pick the SECOND station on the same line.";
  else hint.textContent = "";
}

async function onStationClick(station) {
  if (adminMode === "station") {
    await createScenario("station", { station_id: station.id });
    setAdminMode(null);
    return;
  }
  if (adminMode === "segment-a") {
    const line = document.getElementById("segment-line-select").value;
    if (!station.lines.includes(line)) {
      alert(`${station.name} is not on Line ${line}.`);
      return;
    }
    segmentFirst = { station_id: station.id, station_name: station.name, line_id: line };
    setAdminMode("segment-b");
    return;
  }
  if (adminMode === "segment-b") {
    const line = segmentFirst.line_id;
    if (!station.lines.includes(line)) {
      alert(`${station.name} is not on Line ${line}.`);
      return;
    }
    await createScenario("segment", {
      line_id: line,
      from_station_id: segmentFirst.station_id,
      to_station_id: station.id,
    });
    segmentFirst = null;
    setAdminMode(null);
  }
}

async function closeLineFromDropdown() {
  const line = document.getElementById("line-select").value;
  await createScenario("line", { line_id: line });
}

async function createScenario(type, payload) {
  try {
    const resp = await fetch(`${API_BASE}/api/scenarios`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ type, payload }),
    });
    if (resp.status === 401) return handleUnauthorized();
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: "Failed" }));
      alert(err.detail || "Failed to create scenario");
      return;
    }
    await refreshScenarios();
  } catch (e) {
    alert(`Error: ${e.message}`);
  }
}

async function deleteScenario(id) {
  try {
    const resp = await fetch(`${API_BASE}/api/scenarios/${id}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    if (resp.status === 401) return handleUnauthorized();
    await refreshScenarios();
  } catch (e) {
    alert(`Error: ${e.message}`);
  }
}

async function clearAllScenarios() {
  if (!confirm("Delete all scenarios?")) return;
  try {
    const resp = await fetch(`${API_BASE}/api/scenarios`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    if (resp.status === 401) return handleUnauthorized();
    await refreshScenarios();
  } catch (e) {
    alert(`Error: ${e.message}`);
  }
}

async function refreshScenarios() {
  const listEl = document.getElementById("scenario-list");
  listEl.innerHTML = "";
  const resp = await fetch(`${API_BASE}/api/scenarios`);
  if (!resp.ok) return;
  const items = await resp.json();
  if (items.length === 0) {
    listEl.innerHTML = "<li class='empty'>No active scenarios.</li>";
    return;
  }
  const data = getNetworkData();
  const stationName = (sid) => data?.stations.find((s) => s.id === sid)?.name || sid;

  for (const s of items) {
    const li = document.createElement("li");
    let label;
    if (s.type === "station") label = `Station closed: ${stationName(s.payload.station_id)}`;
    else if (s.type === "line") label = `Line ${s.payload.line_id} closed`;
    else if (s.type === "segment")
      label = `Segment on Line ${s.payload.line_id}: ${stationName(s.payload.from_station_id)} ↔ ${stationName(s.payload.to_station_id)}`;
    else label = `${s.type}: ${JSON.stringify(s.payload)}`;

    const text = document.createElement("span");
    text.textContent = label;
    li.appendChild(text);

    const del = document.createElement("button");
    del.textContent = "Delete";
    del.className = "danger-btn";
    del.addEventListener("click", () => deleteScenario(s.id));
    li.appendChild(del);

    listEl.appendChild(li);
  }
}

function handleUnauthorized() {
  clearToken();
  alert("Session expired. Please log in again.");
  showLogin();
}

function handleLogout() {
  logout();
  location.reload();
}

document.addEventListener("DOMContentLoaded", async () => {
  document.getElementById("login-form").addEventListener("submit", handleLogin);

  if (isLoggedIn()) {
    try {
      await initDashboard();
    } catch (e) {
      showLogin();
    }
  } else {
    showLogin();
  }

  document.getElementById("btn-mode-station").addEventListener("click", () => setAdminMode("station"));
  document.getElementById("btn-mode-segment").addEventListener("click", () => setAdminMode("segment-a"));
  document.getElementById("btn-close-line").addEventListener("click", closeLineFromDropdown);
  document.getElementById("btn-clear-all").addEventListener("click", clearAllScenarios);
  document.getElementById("btn-logout").addEventListener("click", handleLogout);
});
