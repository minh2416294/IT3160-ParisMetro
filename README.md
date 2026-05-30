# Paris Metro Navigator

A localhost web application that finds the fastest walk + metro itinerary between any two points in central Paris, with an admin dashboard for simulating real-world disruptions (closed stations, closed segments, full line closures).

The backend models the city as a single weighted graph (walking + metro fused) and runs **A\*** search with a great-circle-distance heuristic. The frontend is a Leaflet map that shows the live Paris metro network and the computed route.

---

## Screenshots

**User page** — click a start and an end point, get a step-by-step itinerary:

![User page](docs/img/user-page.png)

---

## Features

- **Multi-modal routing** — walk to the nearest station, ride the metro (with transfers), walk to the destination.
- **Time-optimal A\*** — admissible heuristic guarantees the shortest-time path.
- **Real Paris data** — IDFM GTFS feed for the metro + OpenStreetMap for the walking graph.
- **Two ways to pick endpoints** — click on the map, or type a station name in an accent-insensitive search box with line-badge autocomplete (up to 8 matches).
- **Admin scenarios** — close a station, a segment of a line, or an entire line. Routes reroute automatically and the map shows the closures live: closed stations get a red ✕, closed segments and lines are hidden.
- **Smart map decluttering** — the network is hidden by default; after a route is found, only the lines used by that itinerary are revealed automatically.
- **Line filter** — toggle individual metro lines on/off, or show/hide all at once.
- **Disruption banner** — the user page surfaces the count of active disruptions when scenarios are in effect.
- **Tunable ride speed** — a single `RIDE_TIME_FACTOR` constant scales all ride times (default `0.75`) while keeping the A\* heuristic admissible.
- **Unified admin UX** — the admin dashboard mounts the same route planner and line filter as the user page, so admins can test the impact of closures without leaving the tab.
- **No build step** — vanilla JS + Leaflet from a CDN.

---

## How it works

**Graph model.** The city is represented as a single directed weighted graph with five kinds of edges:

| Edge kind | From → To | Weight |
|---|---|---|
| Walk | walk-node ↔ walk-node | `haversine / 1.4 m·s⁻¹` |
| Ride | platform → platform (same line, consecutive stops) | GTFS median travel time × `RIDE_TIME_FACTOR` (default `0.75`) |
| Transfer | platform → platform (same station, different line) | 180 s (flat) |
| Entrance | platform ↔ nearest walk-node (up to 3 within 150 m) | `haversine / 1.4 m·s⁻¹` |
| Virtual endpoint | temporary start/end → graph (snaps to platform if within 100 m) | per-query, rolled back after search |

Each station has **one platform node per line** it serves (so Châtelet has ~5). Transfers are first-class edges, which lets A\* decide whether a transfer is worth the time cost.

**Search.** A\* is run with `f(n) = g(n) + h(n)` where `g` is the true cost so far (seconds) and `h` is the great-circle distance from the current node to the goal divided by a fast upper-bound speed (`V_MAX_MPS`). Dividing by an over-estimate of the fastest edge speed keeps the heuristic **admissible** — A\* is guaranteed to find the optimal path.

**Ride-time scaling.** All ride edges are multiplied by `RIDE_TIME_FACTOR` (default `0.75`) at load time to calibrate the synthetic travel times against perceived metro speed. `V_MAX_MPS` is scaled by `1 / RIDE_TIME_FACTOR` in lockstep, so the heuristic stays admissible regardless of the chosen factor.

**Scenarios.** Admin-created closures are stored in SQLite and compiled into an **in-memory edge mask** at query time. The base graph in RAM is never mutated, so toggling scenarios is instant and safe. Walk, entrance, ride, and transfer edges are all checked against the mask so closures propagate uniformly.

**Virtual endpoints.** When an endpoint is picked (map click or station search), the backend snaps it to the nearest walk node and, if it falls within `STATION_SNAP_R_M = 100 m` of a real platform, links it directly to that platform too. This prevents routes from awkwardly terminating at a nearby walk node when the user really meant the station itself. All temporary state is rolled back after the A\* run — transaction-style.

**Entrance augmentation.** The base graph ships one entrance edge per platform (its single nearest walk node). At load time, up to `ENTRANCE_K = 3` extra entrances within `ENTRANCE_R_MAX_M = 150 m` are added per platform so A\* can enter or leave from a closer street rather than jumping across a block.

---

## Tech stack

| Layer | Tool |
|---|---|
| Language | Python 3.11+ |
| Backend framework | FastAPI + Uvicorn |
| Validation | Pydantic v2, pydantic-settings |
| Auth | JWT (`python-jose`) + bcrypt (`passlib`) |
| Database | SQLite (stdlib) |
| Spatial lookup | `scipy.spatial.cKDTree` |
| GTFS preprocessing | pandas |
| OSM query | Overpass API (`requests`) |
| Frontend | Vanilla JS + Leaflet 1.9.4 (CDN) |
| Map tiles | OpenStreetMap |
| Tests | pytest |

---

## Setup

### Prerequisites
- Python 3.11 or newer
- Git
- ~200 MB free disk (GTFS zip + OSM walk graph + SQLite DB)

### Windows (PowerShell)

```powershell
git clone https://github.com/minh2416294/IT3160-ParisMetro
cd IT3160-ParisMetro

python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt

Copy-Item .env.example .env
# then open .env and set ADMIN_USERNAME, ADMIN_PASSWORD, JWT_SECRET
```

### macOS / Linux (bash)

```bash
git clone https://github.com/minh2416294/IT3160-ParisMetro
cd IT3160-ParisMetro

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
# then edit .env: set ADMIN_USERNAME, ADMIN_PASSWORD, JWT_SECRET
```

### One-time data build (~5–10 min, downloads ~100 MB)

```bash
python scripts/download_gtfs.py       # IDFM GTFS feed → backend/data/raw/
python scripts/download_walk_osm.py   # Overpass walking graph → backend/data/raw/
python scripts/build_graph.py         # GTFS + OSM → SQLite (platforms, ride/transfer/walk/entrance edges)
python scripts/init_db.py             # create admin table, bcrypt-hash the password from .env
```

### Run the app

```bash
uvicorn backend.app.main:app --reload --port 8000
```

Then open:

- **User page:** http://localhost:8000/
- **Admin page:** http://localhost:8000/admin.html — log in with the credentials from `.env`.

---

## Usage

**User page.** Set the start in one of two ways: click **Pick start** then click a point on the map, *or* type a station name in the search box and pick from the dropdown (accent-insensitive, up to 8 matches, line badges shown next to each result). Repeat for the end, then click **Find path**. The route is drawn in dark blue with green/red endpoint pins, and the itinerary is listed on the left (walk duration/distance, metro line, transfers, exit walk). The map starts with the network hidden — only the lines used by your route are revealed. Use the **Filter lines** panel or **Show all** / **Hide all** to override.

If any scenarios are active, a disruption banner appears at the top of the sidebar with the count.

**Admin page.** Log in, then:

- **Close station** — click the button, then click any station on the map. Closed stations get a red ✕ overlay.
- **Close segment** — pick the line, click the button, then click two adjacent stations on that line. The closed segment is hidden from its line layer.
- **Close line** — pick the line from the dropdown, click **Close line**. The entire line layer is removed from the map.

Active scenarios appear in the list; delete them individually or clear all. The admin page also includes the same route planner and line filter as the user page, so you can immediately test how a closure reroutes a path without switching tabs.

---

## API endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/network` | public | Stations (id, name, lat/lng, lines) + segments (line_id, from/to station ids, from/to lat/lng) for map rendering and closure overlays |
| `POST` | `/api/path` | public | Body `{lat_start, lng_start, lat_end, lng_end}` → itinerary with steps (walk / enter / ride / transfer / exit), per-step distance and duration, and total time |
| `POST` | `/api/auth/login` | public | Body `{username, password}` → JWT |
| `GET` | `/api/scenarios` | public | List active scenarios |
| `POST` | `/api/scenarios` | admin | Create a scenario (`type: "station" \| "segment" \| "line"`) |
| `DELETE` | `/api/scenarios/{id}` | admin | Delete one scenario |
| `DELETE` | `/api/scenarios` | admin | Clear all scenarios |

Interactive docs are available at http://localhost:8000/docs while the app is running.

---

## Known limitations / out of scope

- **No real-time data.** We use median travel times from a static GTFS snapshot; no live delays, no strike feed.
- **No schedule-aware routing.** Travel times do not depend on time of day.
- **Metro only.** RER, buses, trams, Transilien, and Noctilien are not modelled.
- **Central Paris only.** The walking graph covers roughly the 48.82–48.90 × 2.27–2.42 bounding box.
- **No address geocoding.** Endpoints can be chosen by map click or station-name search, but arbitrary street addresses are not resolved.
- **Single best route.** The app returns the optimal path; no alternatives are suggested.
- **No accessibility data.** Stairs/elevators are not modelled.
- **Desktop only.** The layout is not responsive for mobile.
- **Localhost only.** No deployment, Docker, or CI configuration is included.

---

## License & attribution

Course project for IT3160 — provided as-is for educational use.

Third-party data and libraries:

- **Map tiles:** © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors, served from `tile.openstreetmap.org`.
- **Walking graph:** Derived from OpenStreetMap via the [Overpass API](https://overpass-api.de/), under the [ODbL](https://www.openstreetmap.org/copyright).
- **Metro network:** [IDFM GTFS feed](https://data.iledefrance-mobilites.fr/) (Île-de-France Mobilités), under the [Licence Ouverte 2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence).
- **Leaflet** © Vladimir Agafonkin — [BSD-2-Clause](https://github.com/Leaflet/Leaflet/blob/main/LICENSE).
- **FastAPI, Uvicorn, Pydantic, SciPy, pandas** — their respective open-source licenses.
