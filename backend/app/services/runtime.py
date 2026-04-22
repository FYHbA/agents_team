from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from app.config import Settings
from app.models.dto import ProjectRuntimePolicy, ProjectRuntimeResponse

RUNTIME_DIRNAME = ".agents-team"
RUNTIME_SUBDIRECTORIES = ("runs", "reports", "artifacts", "memory", "logs")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def resolve_project_path(path_str: str) -> Path:
    path = Path(path_str).expanduser()
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Project path does not exist: {path}")
    if not path.is_dir():
        raise HTTPException(status_code=400, detail=f"Project path is not a directory: {path}")
    return path.resolve()


def project_runtime_path(project_path: Path) -> Path:
    return project_path / RUNTIME_DIRNAME


def runtime_settings_path(project_path: Path) -> Path:
    return project_runtime_path(project_path) / "project.json"


def default_runtime_policy(settings: Settings) -> ProjectRuntimePolicy:
    return ProjectRuntimePolicy(
        allow_network=settings.default_allow_network,
        allow_installs=settings.default_allow_installs,
        dangerous_commands_require_confirmation=settings.default_confirm_dangerous_commands,
        git_strategy="manual",
        global_memory_enabled=True,
        direct_file_editing=True,
    )


def _load_runtime_policy(settings_path: Path, settings: Settings) -> ProjectRuntimePolicy:
    if not settings_path.exists():
        return default_runtime_policy(settings)

    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default_runtime_policy(settings)

    raw_policy = payload.get("policy", {})
    return ProjectRuntimePolicy(
        allow_network=bool(raw_policy.get("allow_network", settings.default_allow_network)),
        allow_installs=bool(raw_policy.get("allow_installs", settings.default_allow_installs)),
        dangerous_commands_require_confirmation=bool(
            raw_policy.get(
                "dangerous_commands_require_confirmation",
                settings.default_confirm_dangerous_commands,
            )
        ),
        git_strategy="manual",
        global_memory_enabled=bool(raw_policy.get("global_memory_enabled", True)),
        direct_file_editing=bool(raw_policy.get("direct_file_editing", True)),
    )


def _runtime_response(
    project_path: Path,
    settings: Settings,
    state: str,
) -> ProjectRuntimeResponse:
    runtime_path = project_runtime_path(project_path)
    settings_file = runtime_settings_path(project_path)
    policy = _load_runtime_policy(settings_file, settings)

    return ProjectRuntimeResponse(
        project_path=str(project_path),
        runtime_path=str(runtime_path),
        state=state,  # type: ignore[arg-type]
        settings_path=str(settings_file),
        directories=[str(runtime_path / name) for name in RUNTIME_SUBDIRECTORIES],
        policy=policy,
        global_home=str(settings.agents_team_home),
    )


def _update_project_registry(project_path: Path, runtime_path: Path, settings: Settings) -> None:
    registry_path = settings.agents_team_home / "projects.json"
    settings.agents_team_home.mkdir(parents=True, exist_ok=True)

    if registry_path.exists():
        try:
            payload = json.loads(registry_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = []
    else:
        payload = []

    if not isinstance(payload, list):
        payload = []

    item = {
        "project_path": str(project_path),
        "runtime_path": str(runtime_path),
        "updated_at": _now_iso(),
    }
    payload = [row for row in payload if row.get("project_path") != str(project_path)]
    payload.append(item)
    payload.sort(key=lambda row: row.get("project_path", "").lower())
    _write_json(registry_path, payload)


def get_project_runtime(project_path_str: str, settings: Settings) -> ProjectRuntimeResponse:
    project_path = resolve_project_path(project_path_str)
    runtime_path = project_runtime_path(project_path)
    state = "existing" if runtime_path.exists() else "missing"
    return _runtime_response(project_path, settings, state)


def init_project_runtime(project_path_str: str, settings: Settings) -> ProjectRuntimeResponse:
    project_path = resolve_project_path(project_path_str)
    runtime_path = project_runtime_path(project_path)
    already_exists = runtime_path.exists()

    runtime_path.mkdir(parents=True, exist_ok=True)
    for directory_name in RUNTIME_SUBDIRECTORIES:
        (runtime_path / directory_name).mkdir(parents=True, exist_ok=True)

    policy = _load_runtime_policy(runtime_settings_path(project_path), settings)
    payload = {
        "version": 1,
        "project_path": str(project_path),
        "runtime_path": str(runtime_path),
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "policy": policy.model_dump(),
    }
    _write_json(runtime_settings_path(project_path), payload)
    _update_project_registry(project_path, runtime_path, settings)

    state = "existing" if already_exists else "initialized"
    return _runtime_response(project_path, settings, state)
