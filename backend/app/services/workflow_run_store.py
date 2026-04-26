from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from app.config import Settings
from app.models.dto import WorkflowRunLogResponse, WorkflowRunRecord, WorkflowStepRun
from app.services.runtime import resolve_project_path
from app.services.workflow_control_db import connect_control_db, control_plane_db_path, initialize_control_db

LOG_TAIL_LINES = 200


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(path)


def load_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def make_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"run-{stamp}-{uuid4().hex[:8]}"


def run_store_path(settings: Settings) -> Path:
    return control_plane_db_path(settings)


def _serialize_record(record: WorkflowRunRecord) -> tuple[str, str, str, str, str, str, str, str, str, str, str]:
    payload = json.dumps(record.model_dump(mode="json"), ensure_ascii=False)
    return (
        record.id,
        record.project_path,
        record.runtime_path,
        record.run_path,
        record.report_path,
        record.changes_path,
        record.log_path,
        record.created_at,
        record.updated_at,
        record.status,
        payload,
    )


def _deserialize_record(payload: str) -> WorkflowRunRecord:
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as exc:  # noqa: PERF203
        raise HTTPException(status_code=500, detail="Stored workflow run payload is invalid JSON.") from exc
    if not isinstance(raw, dict):
        raise HTTPException(status_code=500, detail="Stored workflow run payload is invalid.")
    return WorkflowRunRecord.model_validate(raw)


def save_record(record: WorkflowRunRecord, settings: Settings) -> None:
    initialize_control_db(settings)
    connection = connect_control_db(settings)
    try:
        connection.execute(
            """
            INSERT INTO workflow_runs (
                id,
                project_path,
                runtime_path,
                run_path,
                report_path,
                changes_path,
                log_path,
                created_at,
                updated_at,
                status,
                payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                project_path = excluded.project_path,
                runtime_path = excluded.runtime_path,
                run_path = excluded.run_path,
                report_path = excluded.report_path,
                changes_path = excluded.changes_path,
                log_path = excluded.log_path,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at,
                status = excluded.status,
                payload = excluded.payload
            """,
            _serialize_record(record),
        )
    finally:
        connection.close()


def list_workflow_runs(project_path_str: str | None, settings: Settings) -> list[WorkflowRunRecord]:
    initialize_control_db(settings)
    connection = connect_control_db(settings)
    try:
        if project_path_str:
            project_path = str(resolve_project_path(project_path_str))
            rows = connection.execute(
                """
                SELECT payload
                FROM workflow_runs
                WHERE project_path = ?
                ORDER BY created_at DESC, id DESC
                """,
                (project_path,),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT payload
                FROM workflow_runs
                ORDER BY created_at DESC, id DESC
                """
            ).fetchall()
        return [_deserialize_record(str(row["payload"])) for row in rows]
    finally:
        connection.close()


def get_workflow_run(run_id: str, project_path_str: str | None, settings: Settings) -> WorkflowRunRecord:
    initialize_control_db(settings)
    connection = connect_control_db(settings)
    try:
        if project_path_str:
            project_path = str(resolve_project_path(project_path_str))
            row = connection.execute(
                """
                SELECT payload
                FROM workflow_runs
                WHERE id = ?
                  AND project_path = ?
                LIMIT 1
                """,
                (run_id, project_path),
            ).fetchone()
        else:
            row = connection.execute(
                """
                SELECT payload
                FROM workflow_runs
                WHERE id = ?
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        return _deserialize_record(str(row["payload"]))
    finally:
        connection.close()


def delete_workflow_run_record(run_id: str, settings: Settings) -> None:
    initialize_control_db(settings)
    connection = connect_control_db(settings)
    try:
        connection.execute(
            """
            DELETE FROM workflow_runs
            WHERE id = ?
            """,
            (run_id,),
        )
    finally:
        connection.close()


def append_log(record: WorkflowRunRecord, message: str) -> None:
    log_path = Path(record.log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"[{timestamp}] {message}\n")


def trim_summary(text: str | None, limit: int = 240) -> str | None:
    if text is None:
        return None
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 3].rstrip()}..."


def initialize_step_runs(record: WorkflowRunRecord) -> list[WorkflowStepRun]:
    return [
        WorkflowStepRun(
            step_id=step.id,
            title=step.title,
            agent_role=step.agent_role,
            backend=step.backend,
            execution=step.execution,
            goal=step.goal,
            depends_on=list(step.depends_on),
            allow_failed_dependencies=step.allow_failed_dependencies,
            status="pending",
            command_previews=[preview.model_copy(deep=True) for preview in step.command_previews],
        )
        for step in record.steps
    ]


def step_lookup(record: WorkflowRunRecord, step_id: str) -> WorkflowStepRun:
    for step_run in record.step_runs:
        if step_run.step_id == step_id:
            return step_run
    raise RuntimeError(f"Step not found on run record: {step_id}")


def read_workflow_run_log(
    run_id: str,
    project_path_str: str | None,
    settings: Settings,
    tail_lines: int = LOG_TAIL_LINES,
) -> WorkflowRunLogResponse:
    record = get_workflow_run(run_id, project_path_str, settings)
    log_path = Path(record.log_path)
    if not log_path.exists():
        return WorkflowRunLogResponse(run_id=record.id, log_path=str(log_path), content="")

    content_lines = log_path.read_text(encoding="utf-8").splitlines()
    if tail_lines > 0:
        content_lines = content_lines[-tail_lines:]
    return WorkflowRunLogResponse(
        run_id=record.id,
        log_path=str(log_path),
        content="\n".join(content_lines),
    )
