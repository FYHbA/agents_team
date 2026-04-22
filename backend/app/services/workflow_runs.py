from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from app.config import Settings
from app.models.dto import (
    CodexCommandSpec,
    CodexSessionBridgeRequest,
    WorkflowPlanRequest,
    WorkflowRunCreateRequest,
    WorkflowRunRecord,
)
from app.services.codex import build_session_bridge
from app.services.runtime import init_project_runtime, project_runtime_path, resolve_project_path
from app.services.workflows import build_workflow_plan


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def _make_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"run-{stamp}-{uuid4().hex[:8]}"


def _run_index_path(settings: Settings) -> Path:
    return settings.agents_team_home / "run-index.json"


def _update_run_index(record: WorkflowRunRecord, settings: Settings) -> None:
    index_path = _run_index_path(settings)
    settings.agents_team_home.mkdir(parents=True, exist_ok=True)

    if index_path.exists():
        try:
            payload = _load_json(index_path)
        except json.JSONDecodeError:
            payload = []
    else:
        payload = []

    if not isinstance(payload, list):
        payload = []

    item = {
        "id": record.id,
        "project_path": record.project_path,
        "run_path": record.run_path,
        "updated_at": record.updated_at,
    }
    payload = [row for row in payload if row.get("id") != record.id]
    payload.append(item)
    payload.sort(key=lambda row: row.get("updated_at", ""), reverse=True)
    _write_json(index_path, payload)


def _report_template(record: WorkflowRunRecord) -> str:
    return "\n".join(
        [
            f"# Workflow Run {record.id}",
            "",
            f"Project: `{record.project_path}`",
            f"Status: `{record.status}`",
            f"Created at: `{record.created_at}`",
            "",
            "## Task",
            "",
            record.task,
            "",
            "## Expected Outputs",
            "",
            *[f"- {item}" for item in record.outputs],
            "",
            "## Warnings",
            "",
            *[f"- {warning}" for warning in record.warnings],
            "",
        ]
    )


def _changes_template(record: WorkflowRunRecord) -> str:
    return "\n".join(
        [
            f"# Planned Changes for {record.id}",
            "",
            "- Direct file edits will be recorded here as the workflow executes.",
            "- Git commit and push remain manual in V1.",
            "",
        ]
    )


def _load_record(path: Path) -> WorkflowRunRecord:
    payload = _load_json(path)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail=f"Run record is invalid: {path}")
    return WorkflowRunRecord.model_validate(payload)


def create_workflow_run(request: WorkflowRunCreateRequest, settings: Settings) -> WorkflowRunRecord:
    project_path = resolve_project_path(request.project_path)
    runtime = init_project_runtime(str(project_path), settings)
    plan = build_workflow_plan(
        WorkflowPlanRequest(
            task=request.task,
            project_path=str(project_path),
            allow_network=request.allow_network,
            allow_installs=request.allow_installs,
        ),
        settings,
    )

    codex_commands: list[CodexCommandSpec] = []
    warnings = list(plan.warnings)
    if request.codex_session_id:
        bridge = build_session_bridge(
            request.codex_session_id,
            CodexSessionBridgeRequest(
                project_path=str(project_path),
                prompt=request.resume_prompt,
                sandbox_mode="workspace-write",
                approval_policy="on-request",
            ),
            settings,
        )
        codex_commands = bridge.commands
        warnings.extend(bridge.warnings)

    run_id = _make_run_id()
    run_root = project_runtime_path(project_path) / "runs" / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    report_path = project_runtime_path(project_path) / "reports" / f"{run_id}.md"
    changes_path = run_root / "changes.md"
    created_at = _now_iso()

    record = WorkflowRunRecord(
        id=run_id,
        status="planned",
        created_at=created_at,
        updated_at=created_at,
        task=request.task,
        project_path=str(project_path),
        runtime_path=runtime.runtime_path,
        run_path=str(run_root),
        report_path=str(report_path),
        changes_path=str(changes_path),
        memory_scope="project+global",
        git_strategy="manual",
        direct_file_editing=True,
        team_name=plan.team_name,
        summary=plan.summary,
        allow_network=plan.allow_network,
        allow_installs=plan.allow_installs,
        command_policy=plan.command_policy,
        agents=plan.agents,
        steps=plan.steps,
        outputs=plan.outputs,
        warnings=warnings,
        codex_session_id=request.codex_session_id,
        codex_commands=codex_commands,
    )

    _write_json(run_root / "run.json", record.model_dump(mode="json"))
    report_path.write_text(_report_template(record), encoding="utf-8")
    changes_path.write_text(_changes_template(record), encoding="utf-8")
    _update_run_index(record, settings)
    return record


def list_workflow_runs(project_path_str: str | None, settings: Settings) -> list[WorkflowRunRecord]:
    records: list[WorkflowRunRecord] = []

    if project_path_str:
        project_path = resolve_project_path(project_path_str)
        runs_dir = project_runtime_path(project_path) / "runs"
        if not runs_dir.exists():
            return []
        for run_dir in sorted(runs_dir.iterdir(), reverse=True):
            record_path = run_dir / "run.json"
            if record_path.exists():
                records.append(_load_record(record_path))
        records.sort(key=lambda item: item.created_at, reverse=True)
        return records

    index_path = _run_index_path(settings)
    if not index_path.exists():
        return []

    payload = _load_json(index_path)
    if not isinstance(payload, list):
        return []

    for row in payload:
        run_path = Path(row.get("run_path", ""))
        record_path = run_path / "run.json"
        if record_path.exists():
            records.append(_load_record(record_path))

    records.sort(key=lambda item: item.created_at, reverse=True)
    return records


def get_workflow_run(run_id: str, project_path_str: str | None, settings: Settings) -> WorkflowRunRecord:
    if project_path_str:
        project_path = resolve_project_path(project_path_str)
        record_path = project_runtime_path(project_path) / "runs" / run_id / "run.json"
        if not record_path.exists():
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        return _load_record(record_path)

    index_path = _run_index_path(settings)
    if not index_path.exists():
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    payload = _load_json(index_path)
    if not isinstance(payload, list):
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    for row in payload:
        if row.get("id") == run_id:
            record_path = Path(row.get("run_path", "")) / "run.json"
            if record_path.exists():
                return _load_record(record_path)

    raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
