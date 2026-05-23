from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter
from pydantic import BaseModel

from backend.app.database import get_db_connection

router = APIRouter(prefix="/api", tags=["network"])


class Station(BaseModel):
    id: str
    name: str
    lat: float
    lng: float
    lines: list[str]


class Segment(BaseModel):
    line_id: str
    from_station_id: str
    to_station_id: str
    from_lat: float
    from_lng: float
    to_lat: float
    to_lng: float


class NetworkResponse(BaseModel):
    stations: list[Station]
    segments: list[Segment]


@router.get("/network", response_model=NetworkResponse)
def get_network() -> NetworkResponse:
    with get_db_connection() as conn:
        platform_rows = conn.execute(
            "SELECT id, station_id, station_name, line_id, lat, lng FROM platforms"
        ).fetchall()
        ride_rows = conn.execute(
            "SELECT from_platform, to_platform, line_id FROM ride_edges"
        ).fetchall()

    # Aggregate platforms into unique stations.
    station_map: dict[str, dict] = {}
    lines_by_station: dict[str, set[str]] = defaultdict(set)
    platform_info: dict[int, tuple[float, float, str, str]] = {}

    for r in platform_rows:
        sid = r["station_id"]
        lines_by_station[sid].add(r["line_id"])
        platform_info[r["id"]] = (r["lat"], r["lng"], r["line_id"], sid)
        if sid not in station_map:
            station_map[sid] = {
                "id": sid,
                "name": r["station_name"],
                "lat": r["lat"],
                "lng": r["lng"],
            }

    stations = [
        Station(**info, lines=sorted(lines_by_station[sid]))
        for sid, info in station_map.items()
    ]

    # One segment per directed ride edge. Frontend dedups by coloring.
    seen: set[tuple[int, int]] = set()
    segments: list[Segment] = []
    for r in ride_rows:
        a, b = r["from_platform"], r["to_platform"]
        key = (a, b) if a < b else (b, a)
        if key in seen:
            continue
        seen.add(key)
        if a not in platform_info or b not in platform_info:
            continue
        la, lga, _, sa = platform_info[a]
        lb, lgb, _, sb = platform_info[b]
        segments.append(
            Segment(
                line_id=r["line_id"],
                from_station_id=sa,
                to_station_id=sb,
                from_lat=la,
                from_lng=lga,
                to_lat=lb,
                to_lng=lgb,
            )
        )

    return NetworkResponse(stations=stations, segments=segments)
