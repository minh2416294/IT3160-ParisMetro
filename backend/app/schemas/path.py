from __future__ import annotations

from pydantic import BaseModel, Field


class PathRequest(BaseModel):
    lat_start: float = Field(..., ge=-90, le=90)
    lng_start: float = Field(..., ge=-180, le=180)
    lat_end: float = Field(..., ge=-90, le=90)
    lng_end: float = Field(..., ge=-180, le=180)


class PathStepOut(BaseModel):
    kind: str  # "walk" | "ride" | "transfer" | "enter" | "exit"
    description: str
    duration_s: float
    distance_m: float = 0.0
    line_id: str | None = None


class PathResponse(BaseModel):
    total_time_s: float
    steps: list[PathStepOut]
    coords: list[tuple[float, float]]  # [(lat, lng), ...]
