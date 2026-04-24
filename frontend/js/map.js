// Leaflet setup, network rendering, route drawing, endpoint markers.

let map;
let networkLayer;       // L.LayerGroup for line segments + station markers
let routeLayer;         // L.LayerGroup for the computed route + endpoint pins
let stationMarkers = {}; // station_id -> L.CircleMarker (for admin click-to-close)
let networkData = null;  // cached /api/network response

function initMap(elementId = "map") {
  map = L.map(elementId).setView(MAP_CENTER, MAP_ZOOM);
  L.tileLayer(TILE_URL, { attribution: TILE_ATTRIBUTION, maxZoom: 19 }).addTo(map);
  networkLayer = L.layerGroup().addTo(map);
  routeLayer = L.layerGroup().addTo(map);
  return map;
}

async function loadNetwork() {
  const resp = await fetch(`${API_BASE}/api/network`);
  if (!resp.ok) throw new Error(`Network load failed: ${resp.status}`);
  networkData = await resp.json();
  renderNetwork(networkData);
  return networkData;
}

function renderNetwork(data) {
  networkLayer.clearLayers();
  stationMarkers = {};

  for (const seg of data.segments) {
    L.polyline(
      [
        [seg.from_lat, seg.from_lng],
        [seg.to_lat, seg.to_lng],
      ],
      {
        color: colorForLine(seg.line_id),
        weight: 4,
        opacity: 0.85,
      }
    ).addTo(networkLayer);
  }

  for (const st of data.stations) {
    const marker = L.circleMarker([st.lat, st.lng], {
      radius: 4,
      color: "#222",
      weight: 1,
      fillColor: "#fff",
      fillOpacity: 1,
    })
      .bindTooltip(`<b>${st.name}</b><br>Lines: ${st.lines.join(", ")}`)
      .addTo(networkLayer);
    marker.stationId = st.id;
    marker.stationName = st.name;
    marker.stationLines = st.lines;
    stationMarkers[st.id] = marker;
  }
}

function drawRoute(coords) {
  clearRoute();
  if (!coords || coords.length < 2) return;
  const latlngs = coords.map((c) => [c[0], c[1]]);
  L.polyline(latlngs, { color: "#1f3b8b", weight: 6, opacity: 0.9 }).addTo(routeLayer);
}

function setEndpointMarker(kind, lat, lng) {
  const existing = routeLayer.getLayers().find((l) => l.endpointKind === kind);
  if (existing) routeLayer.removeLayer(existing);
  const color = kind === "start" ? "#2e9e42" : "#c62828";
  const marker = L.circleMarker([lat, lng], {
    radius: 8,
    color,
    weight: 2,
    fillColor: color,
    fillOpacity: 0.9,
  }).addTo(routeLayer);
  marker.endpointKind = kind;
}

function clearRoute() {
  routeLayer.clearLayers();
}

function getStationMarker(stationId) {
  return stationMarkers[stationId];
}

function getNetworkData() {
  return networkData;
}
