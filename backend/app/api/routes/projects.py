from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.config import Settings, get_settings
from app.models.dto import DiscoveredProject, ProjectRuntimeRequest, ProjectRuntimeResponse, ProjectTreeResponse
from app.services.projects import discover_projects, list_directory
from app.services.runtime import get_project_runtime, init_project_runtime

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("/discovered", response_model=list[DiscoveredProject])
def read_discovered_projects(settings: Settings = Depends(get_settings)) -> list[DiscoveredProject]:
    return discover_projects(settings)


@router.get("/tree", response_model=ProjectTreeResponse)
def read_project_tree(
    path: str = Query(..., description="Absolute path to inspect."),
    depth: int = Query(default=1, ge=1, le=3),
) -> ProjectTreeResponse:
    return list_directory(path, depth=depth)


@router.get("/runtime", response_model=ProjectRuntimeResponse)
def read_project_runtime(
    path: str = Query(..., description="Absolute path to the managed project."),
    settings: Settings = Depends(get_settings),
) -> ProjectRuntimeResponse:
    return get_project_runtime(path, settings)


@router.post("/runtime/init", response_model=ProjectRuntimeResponse)
def create_project_runtime(
    request: ProjectRuntimeRequest,
    settings: Settings = Depends(get_settings),
) -> ProjectRuntimeResponse:
    return init_project_runtime(request.project_path, settings)
