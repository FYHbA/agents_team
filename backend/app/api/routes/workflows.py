from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app.config import Settings, get_settings
from app.models.dto import (
    DangerousCommandApprovalRequest,
    WorkflowAgentSessionRecord,
    WorkflowQueueDashboardResponse,
    WorkflowRunArtifactsResponse,
    WorkflowRunDeleteResponse,
    WorkflowPlanRequest,
    WorkflowPlanResponse,
    WorkflowRunCreateRequest,
    WorkflowRunLogResponse,
    WorkflowRunRecord,
)
from app.services.workflow_run_events import stream_workflow_run_events
from app.services.workflow_runs import (
    approve_workflow_run_dangerous_commands,
    cancel_workflow_run,
    create_workflow_run,
    delete_workflow_run,
    get_workflow_queue_dashboard,
    list_agent_sessions,
    get_workflow_run,
    list_workflow_runs,
    read_workflow_run_artifacts,
    read_workflow_run_log,
    resume_workflow_run,
    retry_workflow_run,
    start_workflow_run,
)
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


@router.delete("/runs/{run_id}", response_model=WorkflowRunDeleteResponse)
def remove_run(
    run_id: str,
    project_path: str | None = Query(default=None, description="Optional project path for a targeted lookup."),
    settings: Settings = Depends(get_settings),
) -> WorkflowRunDeleteResponse:
    return delete_workflow_run(run_id, project_path, settings)


@router.post("/runs/{run_id}/execute", response_model=WorkflowRunRecord)
def execute_run(
    run_id: str,
    project_path: str | None = Query(default=None, description="Optional project path for a targeted lookup."),
    settings: Settings = Depends(get_settings),
) -> WorkflowRunRecord:
    return start_workflow_run(run_id, project_path, settings)


@router.get("/runs/{run_id}/log", response_model=WorkflowRunLogResponse)
def read_run_log(
    run_id: str,
    project_path: str | None = Query(default=None, description="Optional project path for a targeted lookup."),
    tail: int = Query(default=200, ge=20, le=1000),
    settings: Settings = Depends(get_settings),
) -> WorkflowRunLogResponse:
    return read_workflow_run_log(run_id, project_path, settings, tail_lines=tail)


@router.get("/runs/{run_id}/artifacts", response_model=WorkflowRunArtifactsResponse)
def read_run_artifacts(
    run_id: str,
    project_path: str | None = Query(default=None, description="Optional project path for a targeted lookup."),
    settings: Settings = Depends(get_settings),
) -> WorkflowRunArtifactsResponse:
    return read_workflow_run_artifacts(run_id, project_path, settings)


@router.get("/runs/{run_id}/events")
async def stream_run_events(
    run_id: str,
    request: Request,
    project_path: str | None = Query(default=None, description="Optional project path for a targeted lookup."),
    tail: int = Query(default=200, ge=20, le=1000),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    return StreamingResponse(
        stream_workflow_run_events(run_id, project_path, settings, request, tail_lines=tail),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/runs/{run_id}/cancel", response_model=WorkflowRunRecord)
def cancel_run(
    run_id: str,
    project_path: str | None = Query(default=None, description="Optional project path for a targeted lookup."),
    settings: Settings = Depends(get_settings),
) -> WorkflowRunRecord:
    return cancel_workflow_run(run_id, project_path, settings)


@router.post("/runs/{run_id}/approve-dangerous", response_model=WorkflowRunRecord)
def approve_dangerous_commands(
    run_id: str,
    request: DangerousCommandApprovalRequest | None = None,
    project_path: str | None = Query(default=None, description="Optional project path for a targeted lookup."),
    settings: Settings = Depends(get_settings),
) -> WorkflowRunRecord:
    return approve_workflow_run_dangerous_commands(
        run_id,
        project_path,
        settings,
        command_ids=request.command_ids if request else None,
    )


@router.post("/runs/{run_id}/resume", response_model=WorkflowRunRecord)
def resume_run(
    run_id: str,
    project_path: str | None = Query(default=None, description="Optional project path for a targeted lookup."),
    settings: Settings = Depends(get_settings),
) -> WorkflowRunRecord:
    return resume_workflow_run(run_id, project_path, settings)


@router.post("/runs/{run_id}/retry", response_model=WorkflowRunRecord)
def retry_run(
    run_id: str,
    project_path: str | None = Query(default=None, description="Optional project path for a targeted lookup."),
    settings: Settings = Depends(get_settings),
) -> WorkflowRunRecord:
    return retry_workflow_run(run_id, project_path, settings)


@router.get("/queue", response_model=WorkflowQueueDashboardResponse)
def read_workflow_queue_dashboard(
    settings: Settings = Depends(get_settings),
) -> WorkflowQueueDashboardResponse:
    return get_workflow_queue_dashboard(settings)


@router.get("/runs/{run_id}/agent-sessions", response_model=list[WorkflowAgentSessionRecord])
def read_agent_sessions(
    run_id: str,
    settings: Settings = Depends(get_settings),
) -> list[WorkflowAgentSessionRecord]:
    return list_agent_sessions(run_id, settings)
