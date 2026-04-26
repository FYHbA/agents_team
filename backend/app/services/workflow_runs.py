from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import HTTPException

from app.config import Settings
from app.models.dto import (
    CodexCommandSpec,
    CodexSessionBridgeRequest,
    WorkflowCommandPreview,
    WorkflowPlanRequest,
    WorkflowStep,
    WorkflowRunArtifactsResponse,
    WorkflowRunContextAuditsResponse,
    WorkflowRunCreateRequest,
    WorkflowRunDeleteResponse,
    WorkflowRunLogResponse,
    WorkflowRunRecord,
)
from app.services.codex import build_session_bridge
from app.services.runtime import init_project_runtime, project_runtime_path, resolve_project_path
from app.services.workflow_agent_sessions import delete_agent_sessions, list_agent_sessions
from app.services.workflow_context_audits import read_workflow_context_audits
from app.services.workflow_memory import build_memory_context
from app.services.workflow_run_queue import delete_workflow_queue_items, get_workflow_queue_dashboard, has_active_workflow_queue_item
from app.services.workflow_run_artifacts import changes_template, read_run_artifacts, report_template
from app.services.workflow_run_execution import (
    approve_workflow_run_dangerous_commands,
    cancel_workflow_run,
    execute_workflow_run_now,
    resume_workflow_run,
    resume_workflow_run_now,
    retry_workflow_run,
    retry_workflow_run_now,
    start_workflow_run,
)
from app.services.workflow_run_store import (
    delete_workflow_run_record,
    get_workflow_run,
    initialize_step_runs,
    list_workflow_runs,
    make_run_id,
    now_iso,
    read_workflow_run_log,
    save_record,
)
from app.services.workflows import build_workflow_plan


def _resolved_path(value: str | None) -> Path | None:
    if not value:
        return None
    try:
        return Path(value).expanduser().resolve()
    except OSError:
        return None


def _path_within_root(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _cleanup_deleted_run_files(record: WorkflowRunRecord) -> None:
    runtime_root = _resolved_path(record.runtime_path)
    if runtime_root is None:
        return

    runs_root = runtime_root / "runs"
    run_root = _resolved_path(record.run_path)
    if run_root and run_root.exists() and run_root != runs_root and _path_within_root(run_root, runs_root):
        shutil.rmtree(run_root)

    for file_path in {record.report_path, record.changes_path, record.log_path, record.last_message_path}:
        candidate = _resolved_path(file_path)
        if candidate is None or candidate.is_dir() or not _path_within_root(candidate, runtime_root):
            continue
        candidate.unlink(missing_ok=True)


def _bridge_command_previews(
    commands: list[CodexCommandSpec],
    *,
    step_id: str,
    requires_confirmation: bool,
) -> list[WorkflowCommandPreview]:
    return [
        WorkflowCommandPreview(
            command_id=f"{step_id}:{index}",
            label=command.purpose,
            argv=list(command.argv),
            cwd=command.cwd,
            source="codex_bridge",
            requires_confirmation=requires_confirmation,
        )
        for index, command in enumerate(commands, start=1)
    ]


def _attach_implement_previews(record_steps: list[WorkflowStep], commands: list[CodexCommandSpec]) -> None:
    if not commands:
        return
    for step in record_steps:
        if step.id == "implement":
            previews = _bridge_command_previews(
                commands,
                step_id=step.id,
                requires_confirmation=step.requires_confirmation,
            )
            step.command_previews = previews
            return


def create_workflow_run(request: WorkflowRunCreateRequest, settings: Settings) -> WorkflowRunRecord:
    project_path = resolve_project_path(request.project_path)
    runtime = init_project_runtime(str(project_path), settings)
    memory_context = build_memory_context(
        str(project_path),
        request.task,
        settings,
        global_enabled=runtime.policy.global_memory_enabled,
    )
    plan = build_workflow_plan(
        WorkflowPlanRequest(
            task=request.task,
            project_path=str(project_path),
            allow_network=request.allow_network,
            allow_installs=request.allow_installs,
            locale=request.locale,
        ),
        settings,
        memory_context=memory_context,
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

    _attach_implement_previews(plan.steps, codex_commands)

    requires_dangerous_command_confirmation = any(step.requires_confirmation for step in plan.steps)
    if requires_dangerous_command_confirmation:
        warnings.append(
            "这个运行在真正执行危险命令前必须先得到明确批准。"
            if request.locale == "zh-CN"
            else "This run must be explicitly approved before it can execute dangerous command-backed steps."
        )

    run_id = make_run_id()
    run_root = project_runtime_path(project_path) / "runs" / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    report_path = project_runtime_path(project_path) / "reports" / f"{run_id}.md"
    changes_path = run_root / "changes.md"
    log_path = run_root / "execution.log"
    last_message_path = run_root / "last-message.md"
    created_at = now_iso()

    record = WorkflowRunRecord(
        id=run_id,
        status="planned",
        attempt_count=0,
        created_at=created_at,
        updated_at=created_at,
        started_at=None,
        completed_at=None,
        cancel_requested_at=None,
        cancelled_at=None,
        task=request.task,
        project_path=str(project_path),
        runtime_path=runtime.runtime_path,
        run_path=str(run_root),
        report_path=str(report_path),
        changes_path=str(changes_path),
        log_path=str(log_path),
        last_message_path=str(last_message_path),
        memory_scope="project+global" if runtime.policy.global_memory_enabled else "project",
        git_strategy="manual",
        direct_file_editing=True,
        requires_dangerous_command_confirmation=requires_dangerous_command_confirmation,
        dangerous_commands_confirmed_at=None,
        team_name=plan.team_name,
        summary=plan.summary,
        allow_network=plan.allow_network,
        allow_installs=plan.allow_installs,
        command_policy=plan.command_policy,
        agents=plan.agents,
        steps=plan.steps,
        outputs=plan.outputs,
        warnings=warnings,
        error=None,
        reuse_decision=None,
        matched_run_id=None,
        reuse_reason=None,
        reuse_confidence=None,
        delta_hint=None,
        delta_scope=None,
        step_runs=[],
        memory_context=memory_context,
        memory_guidance=plan.memory_guidance,
        codex_session_id=request.codex_session_id,
        codex_commands=codex_commands,
    )
    record.step_runs = initialize_step_runs(record)

    save_record(record, settings)
    Path(record.report_path).write_text(report_template(record), encoding="utf-8")
    Path(record.changes_path).write_text(changes_template(record), encoding="utf-8")
    Path(record.log_path).write_text("", encoding="utf-8")

    if request.start_immediately:
        if record.requires_dangerous_command_confirmation:
            record.warnings = [
                *record.warnings,
                (
                    "这个运行先停留在“已计划”状态，因为危险命令执行仍然需要明确批准。"
                    if request.locale == "zh-CN"
                    else "Run created in planned mode because dangerous command execution still needs explicit approval."
                ),
            ]
            record.updated_at = now_iso()
            save_record(record, settings)
            return record
        return start_workflow_run(record.id, str(project_path), settings)
    return record


def read_workflow_run_artifacts(run_id: str, project_path_str: str | None, settings: Settings) -> WorkflowRunArtifactsResponse:
    record = get_workflow_run(run_id, project_path_str, settings)
    return read_run_artifacts(record)


def read_workflow_run_context_audits(run_id: str, settings: Settings) -> WorkflowRunContextAuditsResponse:
    return read_workflow_context_audits(run_id, settings)


def delete_workflow_run(run_id: str, project_path_str: str | None, settings: Settings) -> WorkflowRunDeleteResponse:
    record = get_workflow_run(run_id, project_path_str, settings)
    if record.status == "running":
        raise HTTPException(status_code=409, detail="Cannot delete a running run. Cancel it first and wait for it to stop.")
    if has_active_workflow_queue_item(record.id, settings):
        raise HTTPException(
            status_code=409,
            detail="Cannot delete a queued or running run. Cancel it first and wait for queue activity to finish.",
        )

    _cleanup_deleted_run_files(record)
    delete_agent_sessions(record.id, settings)
    delete_workflow_queue_items(record.id, settings)
    delete_workflow_run_record(record.id, settings)
    return WorkflowRunDeleteResponse(
        run_id=record.id,
        project_path=record.project_path,
        deleted_at=now_iso(),
    )


__all__ = [
    "approve_workflow_run_dangerous_commands",
    "cancel_workflow_run",
    "create_workflow_run",
    "delete_workflow_run",
    "execute_workflow_run_now",
    "get_workflow_run",
    "get_workflow_queue_dashboard",
    "list_agent_sessions",
    "list_workflow_runs",
    "read_workflow_run_log",
    "read_workflow_run_artifacts",
    "read_workflow_run_context_audits",
    "resume_workflow_run",
    "resume_workflow_run_now",
    "retry_workflow_run",
    "retry_workflow_run_now",
    "start_workflow_run",
    "WorkflowRunLogResponse",
]
