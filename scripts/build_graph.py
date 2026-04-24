from __future__ import annotations

import json
import logging
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from statistics import median

import pandas as pd
from scipy.spatial import cKDTree

from backend.app.config import PROJECT_ROOT
from backend.app.database import get_db_connection, init_tables

logger = logging.getLogger(__name__)

RAW_DIR = PROJECT_ROOT / "backend" / "data" / "raw"
GTFS_DIR = RAW_DIR / "gtfs"
WALK_JSON = RAW_DIR / "walk.osm.json"

# Central Paris bounding box (south, west, north, east)
BBOX = (48.82, 2.27, 48.90, 2.42)

WALK_SPEED_MPS = 1.4
TRANSFER_TIME_S = 180.0
EARTH_RADIUS_M = 6_371_000
MAX_PLAUSIBLE_RIDE_S = 1800  # drop outliers from bad GTFS data


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    lat1r, lat2r = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1r) * math.cos(lat2r) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def parse_gtfs_time(t: str) -> int:
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def in_bbox(lat: float, lng: float) -> bool:
    s, w, n, e = BBOX
    return s <= lat <= n and w <= lng <= e


def wipe(conn: sqlite3.Connection) -> None:
    # Delete children before parents to respect FKs.
    for tbl in (
        "entrance_edges",
        "transfer_edges",
        "ride_edges",
        "walk_edges",
        "walk_nodes",
        "platforms",
    ):
        conn.execute(f"DELETE FROM {tbl}")


def build_metro(conn: sqlite3.Connection) -> None:
    print("Loading GTFS CSVs...")
    stops = pd.read_csv(GTFS_DIR / "stops.txt", dtype=str, low_memory=False)
    routes = pd.read_csv(GTFS_DIR / "routes.txt", dtype=str, low_memory=False)
    trips = pd.read_csv(
        GTFS_DIR / "trips.txt",
        dtype=str,
        low_memory=False,
        usecols=["trip_id", "route_id"],
    )
    stop_times = pd.read_csv(
        GTFS_DIR / "stop_times.txt",
        dtype=str,
        low_memory=False,
        usecols=["trip_id", "stop_id", "stop_sequence", "arrival_time", "departure_time"],
    )

    stops["stop_lat"] = stops["stop_lat"].astype(float)
    stops["stop_lon"] = stops["stop_lon"].astype(float)

    metro_routes = routes[routes["route_type"] == "1"].copy()
    metro_routes["line_id"] = metro_routes["route_short_name"].str.strip()
    print(f"  metro routes: {len(metro_routes)}")

    # Resolve station_id: parent_station if present, else stop_id itself.
    parent = stops["parent_station"].fillna("").str.strip()
    stops["station_id"] = parent.where(parent != "", stops["stop_id"])

    # Build name map: prefer a name from a station row (location_type=1).
    name_map: dict[str, str] = {}
    for _, row in stops.iterrows():
        sid = row["station_id"]
        if sid not in name_map or str(row.get("location_type", "")) == "1":
            name_map[sid] = row["stop_name"]

    # Join stop_times -> trips -> metro routes.
    st = stop_times.merge(trips, on="trip_id", how="inner")
    st = st.merge(metro_routes[["route_id", "line_id"]], on="route_id", how="inner")
    st = st.merge(
        stops[["stop_id", "station_id", "stop_lat", "stop_lon"]],
        on="stop_id",
        how="inner",
    )

    # Central-Paris bbox filter.
    s, w, n, e = BBOX
    st = st[(st.stop_lat >= s) & (st.stop_lat <= n) & (st.stop_lon >= w) & (st.stop_lon <= e)].copy()
    st["stop_sequence"] = st["stop_sequence"].astype(int)
    print(f"  metro stop_times in bbox: {len(st):,}")

    # One platform per (station_id, line_id). Use mean coords across its stops.
    plat_df = (
        st.groupby(["station_id", "line_id"])
        .agg(lat=("stop_lat", "mean"), lng=("stop_lon", "mean"))
        .reset_index()
    )
    plat_df["station_name"] = plat_df["station_id"].map(name_map).fillna(plat_df["station_id"])

    platform_pk: dict[tuple[str, str], int] = {}
    cur = conn.cursor()
    for _, row in plat_df.iterrows():
        cur.execute(
            "INSERT INTO platforms (station_id, station_name, line_id, lat, lng)"
            " VALUES (?, ?, ?, ?, ?)",
            (row.station_id, row.station_name, row.line_id, float(row.lat), float(row.lng)),
        )
        platform_pk[(row.station_id, row.line_id)] = cur.lastrowid
    print(f"  platforms: {len(platform_pk)}")

    # Ride edges: per-trip consecutive pairs, take median travel time per (station_a, station_b, line).
    st = st.sort_values(["trip_id", "stop_sequence"])
    st["arrival_s"] = st["arrival_time"].apply(parse_gtfs_time)
    st["departure_s"] = st["departure_time"].apply(parse_gtfs_time)

    times_by_pair: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for _, group in st.groupby("trip_id", sort=False):
        rows = group.to_dict("records")
        for a, b in zip(rows, rows[1:]):
            if a["line_id"] != b["line_id"]:
                continue
            dt = b["arrival_s"] - a["departure_s"]
            if 0 < dt <= MAX_PLAUSIBLE_RIDE_S:
                times_by_pair[(a["station_id"], b["station_id"], a["line_id"])].append(dt)

    ride_count = 0
    for (sa, sb, line), times in times_by_pair.items():
        fp = platform_pk.get((sa, line))
        tp = platform_pk.get((sb, line))
        if fp is None or tp is None or fp == tp:
            continue
        conn.execute(
            "INSERT OR REPLACE INTO ride_edges (from_platform, to_platform, travel_time_s, line_id)"
            " VALUES (?, ?, ?, ?)",
            (fp, tp, float(median(times)), line),
        )
        ride_count += 1
    print(f"  ride_edges: {ride_count}")

    # Transfer edges: within each station, all ordered line pairs.
    by_station: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for (sid, line), pk in platform_pk.items():
        by_station[sid].append((line, pk))

    transfer_count = 0
    for pfs in by_station.values():
        for a_line, a_pk in pfs:
            for b_line, b_pk in pfs:
                if a_line == b_line:
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO transfer_edges"
                    " (from_platform, to_platform, transfer_time_s) VALUES (?, ?, ?)",
                    (a_pk, b_pk, TRANSFER_TIME_S),
                )
                transfer_count += 1
    print(f"  transfer_edges: {transfer_count}")


def build_walk(conn: sqlite3.Connection) -> None:
    print("Loading OSM walking graph...")
    data = json.loads(WALK_JSON.read_text(encoding="utf-8"))
    elements = data["elements"]

    node_coords: dict[int, tuple[float, float]] = {}
    for el in elements:
        if el["type"] == "node":
            node_coords[el["id"]] = (el["lat"], el["lon"])

    raw_edges: list[tuple[int, int]] = []
    for el in elements:
        if el["type"] != "way":
            continue
        ns = el.get("nodes", [])
        for a, b in zip(ns, ns[1:]):
            if a in node_coords and b in node_coords and a != b:
                raw_edges.append((a, b))

    # Adjacency (undirected) for connectivity check.
    adj: dict[int, set[int]] = defaultdict(set)
    for a, b in raw_edges:
        adj[a].add(b)
        adj[b].add(a)

    # Largest connected component via iterative BFS.
    seen: set[int] = set()
    largest: set[int] = set()
    for start in adj:
        if start in seen:
            continue
        comp: set[int] = set()
        stack = [start]
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            comp.add(n)
            stack.extend(adj[n] - seen)
        if len(comp) > len(largest):
            largest = comp
    print(f"  walk nodes kept (largest component): {len(largest):,} / {len(adj):,}")

    # Insert nodes.
    for nid in largest:
        lat, lng = node_coords[nid]
        conn.execute(
            "INSERT INTO walk_nodes (id, lat, lng) VALUES (?, ?, ?)",
            (nid, lat, lng),
        )

    # Insert edges (bidirectional), dedup.
    emitted: set[tuple[int, int]] = set()
    edge_count = 0
    for a, b in raw_edges:
        if a not in largest or b not in largest:
            continue
        key = (a, b) if a < b else (b, a)
        if key in emitted:
            continue
        emitted.add(key)
        la, lga = node_coords[a]
        lb, lgb = node_coords[b]
        t = haversine_m(la, lga, lb, lgb) / WALK_SPEED_MPS
        conn.execute(
            "INSERT OR IGNORE INTO walk_edges (from_node, to_node, travel_time_s) VALUES (?, ?, ?)",
            (a, b, t),
        )
        conn.execute(
            "INSERT OR IGNORE INTO walk_edges (from_node, to_node, travel_time_s) VALUES (?, ?, ?)",
            (b, a, t),
        )
        edge_count += 2
    print(f"  walk_edges: {edge_count}")


def build_entrances(conn: sqlite3.Connection) -> None:
    print("Snapping platforms to nearest walk nodes...")
    walk_rows = conn.execute("SELECT id, lat, lng FROM walk_nodes").fetchall()
    platforms = conn.execute("SELECT id, lat, lng FROM platforms").fetchall()
    if not walk_rows or not platforms:
        print("  no walk nodes or platforms; skipping entrances.")
        return

    walk_ids = [r["id"] for r in walk_rows]
    coords = [(r["lat"], r["lng"]) for r in walk_rows]
    tree = cKDTree(coords)

    count = 0
    for p in platforms:
        _, idx = tree.query((p["lat"], p["lng"]), k=1)
        wnid = walk_ids[idx]
        wlat, wlng = coords[idx]
        t = haversine_m(p["lat"], p["lng"], wlat, wlng) / WALK_SPEED_MPS
        conn.execute(
            "INSERT INTO entrance_edges (platform_id, walk_node_id, travel_time_s)"
            " VALUES (?, ?, ?)",
            (p["id"], wnid, t),
        )
        count += 1
    print(f"  entrance_edges: {count}")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not GTFS_DIR.is_dir():
        print(f"ERROR: {GTFS_DIR} missing. Run scripts/download_gtfs.py first.", file=sys.stderr)
        return 1
    if not WALK_JSON.is_file():
        print(f"ERROR: {WALK_JSON} missing. Run scripts/download_walk_osm.py first.", file=sys.stderr)
        return 1

    init_tables()
    print("Schema ready.")
    with get_db_connection() as conn:
        wipe(conn)
        build_metro(conn)
        build_walk(conn)
        build_entrances(conn)
    print("Graph build complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
