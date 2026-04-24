from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.dependencies.access_control import get_current_admin
from backend.app.dependencies.services import get_scenario_service
from backend.app.schemas.scenario import ScenarioCreate, ScenarioResponse
from backend.app.services.scenario import ScenarioError, ScenarioService

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])


def _to_response(s: object) -> ScenarioResponse:
    return ScenarioResponse(id=s.id, type=s.type, payload=s.payload, created_at=s.created_at)  # type: ignore[attr-defined]


@router.get("", response_model=list[ScenarioResponse])
def list_scenarios(
    service: ScenarioService = Depends(get_scenario_service),
) -> list[ScenarioResponse]:
    return [_to_response(s) for s in service.list_scenarios()]


@router.post("", response_model=ScenarioResponse, status_code=status.HTTP_201_CREATED)
def create_scenario(
    body: ScenarioCreate,
    service: ScenarioService = Depends(get_scenario_service),
    _admin: str = Depends(get_current_admin),
) -> ScenarioResponse:
    try:
        created = service.create_scenario(body.type, body.payload)
    except ScenarioError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _to_response(created)


@router.delete("/{scenario_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scenario(
    scenario_id: int,
    service: ScenarioService = Depends(get_scenario_service),
    _admin: str = Depends(get_current_admin),
) -> None:
    if not service.delete_scenario(scenario_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scenario not found")


@router.delete("", status_code=status.HTTP_200_OK)
def clear_scenarios(
    service: ScenarioService = Depends(get_scenario_service),
    _admin: str = Depends(get_current_admin),
) -> dict[str, int]:
    count = service.clear_all()
    return {"deleted": count}
