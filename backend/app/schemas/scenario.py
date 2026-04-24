from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ScenarioType = Literal["station", "segment", "line"]


class ScenarioCreate(BaseModel):
    type: ScenarioType
    payload: dict[str, Any] = Field(default_factory=dict)


class ScenarioResponse(BaseModel):
    id: int
    type: ScenarioType
    payload: dict[str, Any]
    created_at: str
