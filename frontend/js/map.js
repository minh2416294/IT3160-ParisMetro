// Leaflet setup, network rendering, route drawing, endpoint markers.

let map;
let stationLayer;        // L.LayerGroup for station markers
let routeLayer;          // L.LayerGroup for the computed route + endpoint pins
let closureLayer;        // L.LayerGroup for X markers on closed stations
let lineLayers = {};     // line_id -> L.LayerGroup of polylines
let lineVisibility = {}; // line_id -> bool
let stationMarkers = {}; // station_id -> L.CircleMarker
let stationVisibility = {}; // station_id -> bool
let segmentLayers = {};  // line_id -> [{fromStationId, toStationId, polyline}]
let closedLines = new Set();    // line_ids admin-closed
let closedSegments = new Set(); // keys "line|from|to"
let closedStations = new Set(); // station_ids admin-closed
let networkData = null;  // cached /api/network response

function initMap(elementId = "map") {
  map = L.map(elementId).setView(MAP_CENTER, MAP_ZOOM);
  L.tileLayer(TILE_URL, { attribution: TILE_ATTRIBUTION, maxZoom: 19 }).addTo(map);
  stationLayer = L.layerGroup().addTo(map);
  routeLayer = L.layerGroup().addTo(map);
  closureLayer = L.layerGroup().addTo(map);
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
  for (const lid of Object.keys(lineLayers)) {
    map.removeLayer(lineLayers[lid]);
  }
  lineLayers = {};
  lineVisibility = {};
  segmentLayers = {};
  stationLayer.clearLayers();
  if (closureLayer) closureLayer.clearLayers();
  stationMarkers = {};
  stationVisibility = {};
  closedLines = new Set();
  closedSegments = new Set();
  closedStations = new Set();

  for (const seg of data.segments) {
    if (!lineLayers[seg.line_id]) {
      lineLayers[seg.line_id] = L.layerGroup();
      lineVisibility[seg.line_id] = false;
      segmentLayers[seg.line_id] = [];
    }
    const polyline = L.polyline(
      [
        [seg.from_lat, seg.from_lng],
        [seg.to_lat, seg.to_lng],
      ],
      {
        color: colorForLine(seg.line_id),
        weight: 4,
        opacity: 0.85,
      }
    ).addTo(lineLayers[seg.line_id]);
    segmentLayers[seg.line_id].push({
      fromStationId: seg.from_station_id,
      toStationId: seg.to_station_id,
      polyline,
    });
  }

  for (const st of data.stations) {
    const marker = L.circleMarker([st.lat, st.lng], {
      radius: 4,
      color: "#222",
      weight: 1,
      fillColor: "#fff",
      fillOpacity: 1,
    }).bindTooltip(`<b>${st.name}</b><br>Lines: ${st.lines.join(", ")}`);
    marker.stationId = st.id;
    marker.stationName = st.name;
    marker.stationLines = st.lines;
    stationMarkers[st.id] = marker;
    stationVisibility[st.id] = false;
  }
}

function setLineVisible(lineId, visible) {
  const layer = lineLayers[lineId];
  if (!layer) return;
  lineVisibility[lineId] = visible;
  const effective = visible && !closedLines.has(lineId);
  if (effective) {
    if (!map.hasLayer(layer)) map.addLayer(layer);
  } else {
    if (map.hasLayer(layer)) map.removeLayer(layer);
  }
}

function applyClosures(scenarios) {
  if (!networkData) return;
  closureLayer.clearLayers();

  for (const lid of closedLines) {
    const segs = segmentLayers[lid] || [];
    for (const s of segs) {
      if (!lineLayers[lid].hasLayer(s.polyline)) lineLayers[lid].addLayer(s.polyline);
    }
  }
  for (const key of closedSegments) {
    const [lid, from, to] = key.split("|");
    const seg = findSegment(lid, from, to);
    if (seg && !lineLayers[lid].hasLayer(seg.polyline)) {
      lineLayers[lid].addLayer(seg.polyline);
    }
  }
  closedLines = new Set();
  closedSegments = new Set();
  closedStations = new Set();

  for (const s of scenarios) {
    if (s.type === "station") {
      const sid = s.payload.station_id;
      closedStations.add(sid);
      const st = networkData.stations.find((x) => x.id === sid);
      if (!st) continue;
      const icon = L.divIcon({
        className: "closure-icon",
        html: "✕",
        iconSize: [18, 18],
        iconAnchor: [9, 9],
      });
      L.marker([st.lat, st.lng], { icon, interactive: false }).addTo(closureLayer);
    } else if (s.type === "line") {
      const lid = s.payload.line_id;
      closedLines.add(lid);
      const layer = lineLayers[lid];
      if (layer && map.hasLayer(layer)) map.removeLayer(layer);
    } else if (s.type === "segment") {
      const lid = s.payload.line_id;
      const from = s.payload.from_station_id;
      const to = s.payload.to_station_id;
      closedSegments.add(`${lid}|${from}|${to}`);
      const seg = findSegment(lid, from, to);
      if (seg && lineLayers[lid].hasLayer(seg.polyline)) {
        lineLayers[lid].removeLayer(seg.polyline);
      }
    }
  }
}

function findSegment(lineId, fromStationId, toStationId) {
  const list = segmentLayers[lineId];
  if (!list) return null;
  for (const s of list) {
    if (
      (s.fromStationId === fromStationId && s.toStationId === toStationId) ||
      (s.fromStationId === toStationId && s.toStationId === fromStationId)
    ) {
      return s;
    }
  }
  return null;
}

function setAllLinesVisible(visible) {
  for (const lid of Object.keys(lineLayers)) setLineVisible(lid, visible);
}

function setStationVisible(stationId, visible) {
  const marker = stationMarkers[stationId];
  if (!marker) return;
  stationVisibility[stationId] = visible;
  if (visible) {
    if (!stationLayer.hasLayer(marker)) stationLayer.addLayer(marker);
  } else {
    if (stationLayer.hasLayer(marker)) stationLayer.removeLayer(marker);
  }
}

function setAllStationsVisible(visible) {
  for (const sid of Object.keys(stationMarkers)) setStationVisible(sid, visible);
}

function setStationsVisibleForLines(lineIds) {
  const wanted = new Set(lineIds);
  if (!networkData) return;
  for (const st of networkData.stations) {
    const show = st.lines.some((l) => wanted.has(l));
    setStationVisible(st.id, show);
  }
}

function currentlyVisibleLineIds() {
  return Object.keys(lineVisibility).filter((lid) => lineVisibility[lid]);
}

function hideAllNetwork() {
  setAllLinesVisible(false);
  setAllStationsVisible(false);
}

function getAllLineIds() {
  return Object.keys(lineLayers).sort(compareLineIds);
}

function compareLineIds(a, b) {
  const na = parseFloat(a);
  const nb = parseFloat(b);
  if (isNaN(na) || isNaN(nb)) return a.localeCompare(b);
  return na - nb || a.localeCompare(b);
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
