from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.config import Settings, get_settings
from app.models.dto import WorkflowPlanRequest, WorkflowPlanResponse, WorkflowRunCreateRequest, WorkflowRunRecord
from app.services.workflow_runs import create_workflow_run, get_workflow_run, list_workflow_runs
from app.services.workflows import build_workflow_plan

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.post("/plan", response_model=WorkflowPlanResponse)
def create_workflow_plan(
    request: WorkflowPlanRequest,
    settings: Settings = Depends(get_settings),
) -> WorkflowPlanResponse:
    return build_workflow_plan(request, settings)


@router.post("/runs", response_model=WorkflowRunRecord)
def create_run(
    request: WorkflowRunCreateRequest,
    settings: Settings = Depends(get_settings),
) -> WorkflowRunRecord:
    return create_workflow_run(request, settings)


@router.get("/runs", response_model=list[WorkflowRunRecord])
def read_runs(
    project_path: str | None = Query(default=None, description="Optional project path to filter runs."),
    settings: Settings = Depends(get_settings),
) -> list[WorkflowRunRecord]:
    return list_workflow_runs(project_path, settings)


@router.get("/runs/{run_id}", response_model=WorkflowRunRecord)
def read_run(
    run_id: str,
    project_path: str | None = Query(default=None, description="Optional project path for a targeted lookup."),
    settings: Settings = Depends(get_settings),
) -> WorkflowRunRecord:
    return get_workflow_run(run_id, project_path, settings)
