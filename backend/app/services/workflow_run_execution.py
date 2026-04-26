from __future__ import annotations

import os
import subprocess
import threading
import time
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException

from app.config import Settings
from app.models.dto import WorkflowRunRecord, WorkflowStepRun
from app.services.workflow_agent_sessions import (
    clear_agent_runtime_metadata,
    finish_agent_session,
    start_agent_session,
)
from app.services.workflow_contracts import build_local_research_result_contract, load_research_result_contract, write_research_result_contract
from app.services.workflow_backend_exceptions import WorkflowCancellationRequested, WorkflowExecutionError
from app.services.workflow_backend_reporter import execute_reporter_backend
from app.services.workflow_backend_registry import step_family
from app.services.workflow_memory import persist_run_memory, persist_step_finding
from app.services.workflow_reuse import infer_reuse_decision
from app.services.workflow_run_steps import execute_step
from app.services.workflow_run_queue import (
    DEFAULT_WORKER_LEASE_SECONDS,
    WorkflowQueueItem,
    cancel_active_workflow_queue_items,
    has_active_branch_group_items,
    has_active_run_queue_item,
    has_active_step_queue_item,
    claim_next_workflow_queue_item,
    complete_workflow_queue_item,
    enqueue_workflow_run,
    heartbeat_workflow_queue_item,
    has_active_workflow_queue_item,
    requeue_interrupted_workflow_queue_items,
)
from app.services.workflow_worker_state import upsert_workflow_worker
from app.services.workflow_run_store import (
    append_log,
    get_workflow_run,
    list_workflow_runs,
    now_iso,
    save_record,
    step_lookup,
)

RunMode = Literal["start", "resume", "retry"]
WORKER_POLL_INTERVAL_SECONDS = 0.25

_RUN_THREADS: dict[str, dict[int, threading.Thread]] = {}
_RUN_PROCESSES: dict[str, dict[int, subprocess.Popen[str]]] = {}
_RUN_CANCEL_EVENTS: dict[str, threading.Event] = {}
_RUN_REGISTRY_LOCK = threading.Lock()
_RUN_STATE_LOCKS: dict[str, threading.Lock] = {}
_QUEUE_WORKERS: dict[str, list[threading.Thread]] = {}
_QUEUE_WORKER_LOCK = threading.RLock()
_QUEUE_WORKER_IDS: dict[str, str] = {}
_EXECUTION_CONTEXT = threading.local()


def _has_live_thread(run_id: str) -> bool:
    with _RUN_REGISTRY_LOCK:
        threads = _RUN_THREADS.get(run_id, {})
        return any(thread.is_alive() for thread in threads.values())


def _worker_id_for_key(key: str) -> str:
    with _QUEUE_WORKER_LOCK:
        worker_id = _QUEUE_WORKER_IDS.get(key)
        if worker_id is None:
            worker_id = f"worker-{os.getpid()}-{uuid4().hex[:8]}"
            _QUEUE_WORKER_IDS[key] = worker_id
        return worker_id


def _set_execution_worker_id(worker_id: str | None) -> None:
    _EXECUTION_CONTEXT.worker_id = worker_id


def _current_execution_worker_id() -> str | None:
    return getattr(_EXECUTION_CONTEXT, "worker_id", None)


def _set_active_thread(run_id: str, thread: threading.Thread | None) -> None:
    thread_id = threading.get_ident()
    with _RUN_REGISTRY_LOCK:
        if thread is None:
            threads = _RUN_THREADS.get(run_id)
            if threads is not None:
                threads.pop(thread_id, None)
                if not threads:
                    _RUN_THREADS.pop(run_id, None)
            return
        threads = _RUN_THREADS.get(run_id)
        if threads is None:
            threads = {}
            _RUN_THREADS[run_id] = threads
        threads[thread_id] = thread


def _ensure_cancel_event(run_id: str) -> threading.Event:
    with _RUN_REGISTRY_LOCK:
        event = _RUN_CANCEL_EVENTS.get(run_id)
        if event is None:
            event = threading.Event()
            _RUN_CANCEL_EVENTS[run_id] = event
        return event


def _state_lock_for_run(run_id: str) -> threading.Lock:
    with _RUN_REGISTRY_LOCK:
        lock = _RUN_STATE_LOCKS.get(run_id)
        if lock is None:
            lock = threading.Lock()
            _RUN_STATE_LOCKS[run_id] = lock
        return lock


def _clear_runtime_handles(run_id: str) -> None:
    thread_id = threading.get_ident()
    with _RUN_REGISTRY_LOCK:
        threads = _RUN_THREADS.get(run_id)
        if threads is not None:
            threads.pop(thread_id, None)
            if not threads:
                _RUN_THREADS.pop(run_id, None)
        processes = _RUN_PROCESSES.get(run_id)
        if processes is not None:
            processes.pop(thread_id, None)
            if not processes:
                _RUN_PROCESSES.pop(run_id, None)
        if run_id not in _RUN_THREADS and run_id not in _RUN_PROCESSES:
            _RUN_CANCEL_EVENTS.pop(run_id, None)
            _RUN_STATE_LOCKS.pop(run_id, None)


def _set_active_process(run_id: str, process: subprocess.Popen[str] | None) -> None:
    thread_id = threading.get_ident()
    with _RUN_REGISTRY_LOCK:
        processes = _RUN_PROCESSES.get(run_id)
        if process is None:
            if processes is not None:
                processes.pop(thread_id, None)
                if not processes:
                    _RUN_PROCESSES.pop(run_id, None)
            return
        if processes is None:
            processes = {}
            _RUN_PROCESSES[run_id] = processes
        processes[thread_id] = process


def _is_cancel_requested(run_id: str) -> bool:
    with _RUN_REGISTRY_LOCK:
        event = _RUN_CANCEL_EVENTS.get(run_id)
        return bool(event and event.is_set())


def _request_cancel_signal(run_id: str) -> None:
    processes: list[subprocess.Popen[str]]
    event = _ensure_cancel_event(run_id)
    event.set()
    with _RUN_REGISTRY_LOCK:
        processes = list((_RUN_PROCESSES.get(run_id) or {}).values())
    for process in processes:
        if process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass


def _reset_step(step_run: WorkflowStepRun) -> None:
    step_run.status = "pending"
    step_run.started_at = None
    step_run.completed_at = None
    step_run.summary = None


def _mark_step_running(record: WorkflowRunRecord, step_run: WorkflowStepRun, settings: Settings) -> None:
    now = now_iso()
    step_run.status = "running"
    step_run.started_at = now
    step_run.completed_at = None
    step_run.summary = None
    record.updated_at = now
    append_log(record, f"Starting step `{step_run.step_id}`: {step_run.title}")
    save_record(record, settings)


def _mark_step_finished(
    record: WorkflowRunRecord,
    step_run: WorkflowStepRun,
    status: Literal["completed", "failed", "skipped"],
    settings: Settings,
    summary: str | None = None,
) -> None:
    now = now_iso()
    step_run.status = status
    step_run.completed_at = now
    step_run.summary = summary
    record.updated_at = now
    if status == "failed" and summary:
        record.error = summary
    append_log(record, f"Finished step `{step_run.step_id}` with status `{status}`.")
    if summary:
        append_log(record, summary)
    save_record(record, settings)
    if step_run.step_id in {"research", "verify"} and status in {"completed", "failed"}:
        record.memory_context = persist_step_finding(record, step_run, settings)
        save_record(record, settings)


def _mark_step_cancelled(record: WorkflowRunRecord, step_run: WorkflowStepRun, settings: Settings, reason: str) -> None:
    now = now_iso()
    step_run.status = "cancelled"
    step_run.completed_at = now
    step_run.summary = reason
    record.updated_at = now
    append_log(record, f"Cancelled step `{step_run.step_id}`: {reason}")
    save_record(record, settings)


def _mark_step_skipped(record: WorkflowRunRecord, step_run: WorkflowStepRun, settings: Settings, reason: str) -> None:
    now = now_iso()
    step_run.status = "skipped"
    step_run.started_at = step_run.started_at or now
    step_run.completed_at = now
    step_run.summary = reason
    record.updated_at = now
    append_log(record, f"Skipping step `{step_run.step_id}`: {reason}")
    save_record(record, settings)


def _execute_step_with_agent_session(
    record: WorkflowRunRecord,
    step_run: WorkflowStepRun,
    settings: Settings,
    *,
    should_cancel,
    set_active_process,
) -> str:
    clear_agent_runtime_metadata()
    session = start_agent_session(
        record=record,
        step_run=step_run,
        settings=settings,
        worker_id=_current_execution_worker_id(),
    )
    try:
        summary = execute_step(
            record,
            step_run,
            settings,
            should_cancel=should_cancel,
            set_active_process=set_active_process,
        )
    except WorkflowCancellationRequested as exc:
        finish_agent_session(
            session_id=session.id,
            settings=settings,
            status="cancelled",
            summary=str(exc),
            error=str(exc),
        )
        raise
    except Exception as exc:  # noqa: BLE001
        finish_agent_session(
            session_id=session.id,
            settings=settings,
            status="failed",
            summary=str(exc),
            error=str(exc),
        )
        raise
    else:
        finish_agent_session(
            session_id=session.id,
            settings=settings,
            status="completed",
            summary=summary,
        )
        return summary
    finally:
        clear_agent_runtime_metadata()


def _prepare_for_resume(record: WorkflowRunRecord) -> None:
    for step_run in record.step_runs:
        if step_run.step_id == "report":
            _reset_step(step_run)
            continue
        if step_run.status != "completed":
            _reset_step(step_run)


def _prepare_for_retry(record: WorkflowRunRecord) -> None:
    for step_run in record.step_runs:
        _reset_step(step_run)


def _dangerous_command_previews(record: WorkflowRunRecord):
    previews = []
    seen: set[str] = set()
    for step_run in record.step_runs:
        for preview in step_run.command_previews:
            if not preview.requires_confirmation or preview.command_id in seen:
                continue
            previews.append(preview)
            seen.add(preview.command_id)
    if previews:
        return previews

    for step in record.steps:
        for preview in step.command_previews:
            if not preview.requires_confirmation or preview.command_id in seen:
                continue
            previews.append(preview)
            seen.add(preview.command_id)
    return previews


def _pending_dangerous_command_previews(record: WorkflowRunRecord):
    return [preview for preview in _dangerous_command_previews(record) if preview.confirmed_at is None]


def _sync_dangerous_confirmation_state(record: WorkflowRunRecord) -> None:
    previews = _dangerous_command_previews(record)
    if not previews:
        return
    if all(preview.confirmed_at for preview in previews):
        latest = max(preview.confirmed_at or "" for preview in previews)
        record.dangerous_commands_confirmed_at = latest or now_iso()
        return
    record.dangerous_commands_confirmed_at = None


def _delta_preview_scope_note(record: WorkflowRunRecord) -> str | None:
    if record.delta_scope is None:
        return None
    parts: list[str] = []
    if record.delta_scope.focus_paths:
        parts.append("Focus paths: " + ", ".join(record.delta_scope.focus_paths[:4]))
    if record.delta_scope.scope_summary:
        parts.append(record.delta_scope.scope_summary)
    return " ".join(parts).strip() or None


def _preview_allowed_for_delta(step_id: str, verification_focus: str) -> bool:
    family = step_family(step_id)
    if family != "verify":
        return True
    if step_id == "verify_tests":
        return verification_focus in {"all", "tests"}
    if step_id == "verify_build":
        return verification_focus in {"all", "build"}
    return verification_focus != "docs"


def _apply_delta_scope_to_previews(record: WorkflowRunRecord) -> None:
    if record.delta_scope is None:
        return
    verification_focus = record.delta_scope.verification_focus
    scope_note = _delta_preview_scope_note(record)

    def mutate(step_like) -> None:
        filtered_previews = [
            preview
            for preview in step_like.command_previews
            if _preview_allowed_for_delta(step_like.id if hasattr(step_like, "id") else step_like.step_id, verification_focus)
        ]
        for preview in filtered_previews:
            preview.delta_scoped = True
            preview.scope_note = scope_note
        step_like.command_previews = filtered_previews

    for step in record.steps:
        mutate(step)
    for step_run in record.step_runs:
        mutate(step_run)


def _ensure_dangerous_commands_are_confirmed(record: WorkflowRunRecord, mode: RunMode) -> None:
    if not record.requires_dangerous_command_confirmation:
        return
    pending = _pending_dangerous_command_previews(record)
    if not pending and record.dangerous_commands_confirmed_at:
        return
    if not pending and not _dangerous_command_previews(record) and record.dangerous_commands_confirmed_at:
        return
    raise HTTPException(
        status_code=409,
        detail=(
            f"Run requires dangerous command confirmation before it can {mode}: {record.id}. "
            + (
                f"Approve the remaining {len(pending)} command(s) first."
                if pending
                else "Approve the run first."
            )
        ),
    )


def _prepare_run_attempt(
    record: WorkflowRunRecord,
    settings: Settings,
    mode: RunMode,
    *,
    ignore_active_queue: bool = False,
) -> WorkflowRunRecord:
    live_thread = _has_live_thread(record.id)
    active_queue_item = False if ignore_active_queue else has_active_workflow_queue_item(record.id, settings)

    if mode == "start":
        if record.status == "running" and (live_thread or active_queue_item):
            return record
        if record.status == "running" and not live_thread:
            raise HTTPException(status_code=409, detail=f"Run is stuck in `running`; use resume: {record.id}")
        if record.status != "planned":
            raise HTTPException(status_code=409, detail=f"Run cannot be started from status `{record.status}`.")
        _ensure_dangerous_commands_are_confirmed(record, mode)
    elif mode == "resume":
        if record.status == "running" and (live_thread or active_queue_item):
            return record
        if record.status not in {"planned", "failed", "cancelled", "running"}:
            raise HTTPException(status_code=409, detail=f"Run cannot be resumed from status `{record.status}`.")
        _ensure_dangerous_commands_are_confirmed(record, mode)
        if record.status in {"failed", "cancelled"} or (record.status == "running" and not live_thread):
            _prepare_for_resume(record)
    else:
        if record.status == "running" and (live_thread or active_queue_item):
            raise HTTPException(status_code=409, detail=f"Run is still active and cannot be retried: {record.id}")
        if record.status not in {"failed", "cancelled", "short_circuited"}:
            raise HTTPException(status_code=409, detail=f"Run cannot be retried from status `{record.status}`.")
        _ensure_dangerous_commands_are_confirmed(record, mode)
        _prepare_for_retry(record)

    _ensure_cancel_event(record.id).clear()
    now = now_iso()
    record.attempt_count += 1
    record.status = "running"
    record.started_at = now
    record.completed_at = None
    record.cancel_requested_at = None
    record.cancelled_at = None
    record.error = None
    record.memory_context.written_project = []
    record.memory_context.written_global = []
    record.reuse_decision = None
    record.matched_run_id = None
    record.reuse_reason = None
    record.reuse_confidence = None
    record.delta_hint = None
    record.delta_scope = None
    record.updated_at = now
    save_record(record, settings)
    append_log(record, f"Workflow {mode} started for run `{record.id}` on attempt `{record.attempt_count}`.")
    return record


def _finalize_run(
    record: WorkflowRunRecord,
    settings: Settings,
    *,
    status: Literal["completed", "failed", "cancelled", "short_circuited"],
    message: str,
    error: str | None = None,
) -> WorkflowRunRecord:
    now = now_iso()
    record.status = status
    record.completed_at = now
    record.updated_at = now
    record.error = error
    if status == "cancelled":
        record.cancelled_at = now
        record.cancel_requested_at = record.cancel_requested_at or now
    record.memory_context = persist_run_memory(record, settings)
    try:
        execute_reporter_backend(
            record,
            settings,
            should_cancel=lambda: False,
            set_active_process=lambda process: _set_active_process(record.id, process),
        )
    except Exception:  # noqa: BLE001
        pass
    append_log(record, message)
    save_record(record, settings)
    return record


def _finalize_cancelled_run(
    record: WorkflowRunRecord,
    settings: Settings,
    *,
    reason: str,
) -> WorkflowRunRecord:
    report_step = step_lookup(record, "report")
    for step_run in record.step_runs:
        if step_run.step_id == "report" or step_run.status == "completed":
            continue
        if step_run.status == "running":
            _mark_step_cancelled(record, step_run, settings, reason)
        else:
            _mark_step_skipped(record, step_run, settings, "Skipped because the workflow was cancelled.")

    if report_step.status != "completed":
        _reset_step(report_step)
        _mark_step_running(record, report_step, settings)
        try:
            summary = _execute_step_with_agent_session(
                record,
                report_step,
                settings,
                should_cancel=lambda: False,
                set_active_process=lambda process: _set_active_process(record.id, process),
            )
        except Exception as exc:  # noqa: BLE001
            _mark_step_finished(record, report_step, "failed", settings, summary=str(exc))
            return _finalize_run(
                get_workflow_run(record.id, record.project_path, settings),
                settings,
                status="failed",
                message=f"Workflow cancellation report failed: {exc}",
                error=str(exc),
            )
        _mark_step_finished(record, report_step, "completed", settings, summary=summary)

    return _finalize_run(record, settings, status="cancelled", message=f"Workflow execution cancelled: {reason}")


def _research_short_circuit_contract(record: WorkflowRunRecord):
    research_step = next((step_run for step_run in record.step_runs if step_run.step_id == "research"), None)
    if research_step is None or research_step.status != "completed":
        return None
    contract = load_research_result_contract(record)
    if contract is None:
        return None
    if contract.decision not in {"stop_as_duplicate", "stop_as_already_satisfied"}:
        return None
    return contract


def _apply_research_short_circuit(record: WorkflowRunRecord, settings: Settings) -> None:
    contract = _research_short_circuit_contract(record)
    if contract is None:
        return
    if record.reuse_decision == contract.decision and record.matched_run_id == contract.matched_run_id:
        return
    record.reuse_decision = contract.decision
    record.matched_run_id = contract.matched_run_id
    record.reuse_reason = contract.reason or None
    record.reuse_confidence = contract.confidence
    record.delta_hint = contract.delta_hint or None
    record.delta_scope = None
    summary = contract.reason or (
        "Research concluded that this task is already covered by a prior successful run and later workflow steps are being skipped."
    )
    for step_run in record.step_runs:
        if step_family(step_run.step_id) in {"plan", "research", "report"}:
            continue
        if step_run.status == "pending":
            _mark_step_skipped(record, step_run, settings, f"Skipped because research returned `{contract.decision}`. {summary}")
    record.updated_at = now_iso()
    append_log(
        record,
        "Workflow short-circuit triggered by research decision "
        f"`{contract.decision}`"
        + (f" matched to `{contract.matched_run_id}`." if contract.matched_run_id else "."),
    )
    if summary:
        append_log(record, summary)
    save_record(record, settings)


def _apply_research_delta_narrowing(record: WorkflowRunRecord, settings: Settings) -> None:
    research_step = next((step_run for step_run in record.step_runs if step_run.step_id == "research"), None)
    if research_step is None or research_step.status != "completed":
        return
    contract = load_research_result_contract(record)
    if contract is None or contract.decision != "continue_with_delta":
        return
    if record.reuse_decision == contract.decision and record.matched_run_id == contract.matched_run_id:
        return
    record.reuse_decision = contract.decision
    record.matched_run_id = contract.matched_run_id
    record.reuse_reason = contract.reason or None
    record.reuse_confidence = contract.confidence
    record.delta_hint = contract.delta_hint or None
    record.delta_scope = contract.delta_scope

    goal_suffix = (
        contract.delta_scope.scope_summary
        if contract.delta_scope is not None and contract.delta_scope.scope_summary
        else contract.delta_hint
        or contract.reason
        or "Continue only on the remaining delta from the matched prior run."
    )

    def rewrite_goal(step_id: str, prefix: str) -> None:
        for step in record.steps:
            if step.id == step_id:
                step.goal = f"{prefix} {goal_suffix}".strip()
        for step_run in record.step_runs:
            if step_run.step_id == step_id and step_run.status == "pending":
                step_run.goal = f"{prefix} {goal_suffix}".strip()

    rewrite_goal("implement", "Apply only the remaining delta that still separates the current project from the matched prior run.")
    for step_id in ("verify", "verify_tests", "verify_build"):
        rewrite_goal(step_id, "Verify only the narrowed delta path and confirm the matched prior result still holds where unchanged.")
    rewrite_goal("review", "Review only the narrowed delta path, with explicit cross-checks against the matched prior run.")
    rewrite_goal("report", "Explain which prior run was reused, what remaining delta was processed, and why the workflow was narrowed.")
    _apply_delta_scope_to_previews(record)

    append_log(
        record,
        "Workflow delta narrowing triggered by research decision "
        f"`{contract.decision}`"
        + (f" matched to `{contract.matched_run_id}`." if contract.matched_run_id else "."),
    )
    if contract.reason:
        append_log(record, contract.reason)
    if contract.delta_hint:
        append_log(record, f"Delta hint: {contract.delta_hint}")
    if contract.delta_scope is not None and contract.delta_scope.scope_summary:
        append_log(record, f"Delta scope: {contract.delta_scope.scope_summary}")
    record.updated_at = now_iso()
    save_record(record, settings)


def _completed_step_ids(record: WorkflowRunRecord) -> set[str]:
    return {step.step_id for step in record.step_runs if step.status == "completed"}


def _dependency_satisfied(record: WorkflowRunRecord, step_run: WorkflowStepRun, dependency_id: str) -> bool:
    dependency = step_lookup(record, dependency_id)
    if dependency.status == "completed":
        return True
    if step_run.allow_failed_dependencies and dependency.status == "failed":
        return True
    return False


def _dependency_blocked(record: WorkflowRunRecord, step_run: WorkflowStepRun, dependency_id: str) -> bool:
    dependency = step_lookup(record, dependency_id)
    if dependency.status in {"pending", "running"}:
        return False
    return not _dependency_satisfied(record, step_run, dependency_id)


def _ready_step_runs(record: WorkflowRunRecord) -> list[WorkflowStepRun]:
    return [
        step_run
        for step_run in record.step_runs
        if step_family(step_run.step_id) != "report"
        and step_run.status == "pending"
        and all(_dependency_satisfied(record, step_run, dependency) for dependency in step_run.depends_on)
    ]


def _select_step_wave(ready_steps: list[WorkflowStepRun]) -> list[WorkflowStepRun]:
    serial_steps = [step for step in ready_steps if step.execution == "serial"]
    if serial_steps:
        return [serial_steps[0]]
    return ready_steps


def _blocked_step_runs(record: WorkflowRunRecord) -> list[WorkflowStepRun]:
    blocked: list[WorkflowStepRun] = []
    for step_run in record.step_runs:
        if step_family(step_run.step_id) == "report" or step_run.status != "pending":
            continue
        if any(_dependency_blocked(record, step_run, dependency) for dependency in step_run.depends_on):
            blocked.append(step_run)
    return blocked


def _execute_single_step_run(
    record: WorkflowRunRecord,
    step_run: WorkflowStepRun,
    settings: Settings,
    run_id: str,
    state_lock: threading.Lock,
    *,
    wave_cancel_event: threading.Event | None = None,
) -> tuple[str, str]:
    run_state_lock = _state_lock_for_run(run_id)
    with run_state_lock:
        latest_record = get_workflow_run(record.id, record.project_path, settings)
        latest_step_run = step_lookup(latest_record, step_run.step_id)
        _mark_step_running(latest_record, latest_step_run, settings)
    try:
        summary = _execute_step_with_agent_session(
            record,
            step_run,
            settings,
            should_cancel=lambda: _is_cancel_requested(run_id) or bool(wave_cancel_event and wave_cancel_event.is_set()),
            set_active_process=lambda process: _set_active_process(run_id, process),
        )
    except WorkflowCancellationRequested as exc:
        if wave_cancel_event is not None:
            wave_cancel_event.set()
        with run_state_lock:
            latest_record = get_workflow_run(record.id, record.project_path, settings)
            latest_step_run = step_lookup(latest_record, step_run.step_id)
            _mark_step_cancelled(latest_record, latest_step_run, settings, str(exc))
        return "cancelled", str(exc)
    except Exception as exc:  # noqa: BLE001
        if wave_cancel_event is not None:
            wave_cancel_event.set()
        with run_state_lock:
            latest_record = get_workflow_run(record.id, record.project_path, settings)
            latest_step_run = step_lookup(latest_record, step_run.step_id)
            _mark_step_finished(latest_record, latest_step_run, "failed", settings, summary=str(exc))
        return "failed", str(exc)

    with run_state_lock:
        latest_record = get_workflow_run(record.id, record.project_path, settings)
        latest_step_run = step_lookup(latest_record, step_run.step_id)
        _mark_step_finished(latest_record, latest_step_run, "completed", settings, summary=summary)
    return "completed", summary


def _execute_step_wave(
    record: WorkflowRunRecord,
    step_runs: list[WorkflowStepRun],
    settings: Settings,
    run_id: str,
    state_lock: threading.Lock,
) -> tuple[str | None, str | None]:
    if len(step_runs) == 1:
        status, message = _execute_single_step_run(record, step_runs[0], settings, run_id, state_lock)
        if status == "failed":
            return message, None
        if status == "cancelled":
            return None, message
        return None, None

    wave_cancel_event = threading.Event()
    results: dict[str, tuple[str, str]] = {}
    result_lock = threading.Lock()

    def worker(step_run: WorkflowStepRun) -> None:
        status, message = _execute_single_step_run(
            record,
            step_run,
            settings,
            run_id,
            state_lock,
            wave_cancel_event=wave_cancel_event,
        )
        with result_lock:
            results[step_run.step_id] = (status, message)

    threads = [
        threading.Thread(
            target=worker,
            args=(step_run,),
            daemon=True,
            name=f"workflow-step-{run_id}-{step_run.step_id}",
        )
        for step_run in step_runs
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    for step_run in step_runs:
        status, message = results.get(step_run.step_id, ("failed", "Parallel step did not report a result."))
        if status == "failed":
            return message, None
    for step_run in step_runs:
        status, message = results.get(step_run.step_id, ("cancelled", "Parallel step was cancelled."))
        if status == "cancelled":
            return None, message
    return None, None


def _enqueue_parallel_step_wave(record: WorkflowRunRecord, step_runs: list[WorkflowStepRun], settings: Settings) -> None:
    branch_group_id = f"branch-{record.id}-{uuid4().hex[:8]}"
    for step_run in step_runs:
        _mark_step_running(record, step_run, settings)
        enqueue_workflow_run(
            run_id=record.id,
            project_path=record.project_path,
            mode="resume",
            prepared=True,
            item_kind="step",
            target_step_id=step_run.step_id,
            branch_group_id=branch_group_id,
            settings=settings,
        )
    append_log(
        record,
        "Queued parallel workflow branch wave: " + ", ".join(step_run.step_id for step_run in step_runs),
    )


def _final_run_status(record: WorkflowRunRecord) -> Literal["completed", "failed", "short_circuited"]:
    if record.reuse_decision in {"stop_as_duplicate", "stop_as_already_satisfied"}:
        return "short_circuited"
    non_report_steps = [step_run for step_run in record.step_runs if step_family(step_run.step_id) != "report"]
    if any(step_run.status in {"failed", "skipped", "cancelled"} for step_run in non_report_steps):
        return "failed"
    return "completed"


def _maybe_preflight_reuse_research_completion(
    record: WorkflowRunRecord,
    settings: Settings,
) -> bool:
    research_step = next((step_run for step_run in record.step_runs if step_run.step_id == "research"), None)
    if research_step is None or research_step.status != "pending":
        return False
    if any(step_lookup(record, dependency_id).status != "completed" for dependency_id in research_step.depends_on):
        return False
    decision, matched_run_id, confidence, reason, delta_hint, delta_scope = infer_reuse_decision(record, settings)
    if decision not in {"stop_as_duplicate", "stop_as_already_satisfied"}:
        return False
    contract = build_local_research_result_contract(
        record,
        top_level_entries=[],
        decision=decision,
        matched_run_id=matched_run_id,
        confidence=confidence,
        reason=reason,
        delta_hint=delta_hint,
        delta_scope=delta_scope,
    )
    _mark_step_running(record, research_step, settings)
    write_research_result_contract(record, contract)
    _mark_step_finished(record, research_step, "completed", settings, summary=contract.summary)
    latest_record = get_workflow_run(record.id, record.project_path, settings)
    _apply_research_short_circuit(latest_record, settings)
    return True


def _execute_workflow_run(
    run_id: str,
    project_path_str: str | None,
    settings: Settings,
    *,
    queue_parallel_branches: bool = False,
) -> None:
    record = get_workflow_run(run_id, project_path_str, settings)
    if record.status != "running":
        raise WorkflowExecutionError(f"Run {run_id} cannot be executed from status `{record.status}`.")

    cancel_message: str | None = None
    state_lock = threading.Lock()

    while True:
        record = get_workflow_run(run_id, project_path_str, settings)
        remaining = [
            step_run
            for step_run in record.step_runs
            if step_family(step_run.step_id) != "report" and step_run.status == "pending"
        ]
        if not remaining:
            break

        if cancel_message:
            for step_run in remaining:
                _mark_step_skipped(record, step_run, settings, "Skipped because the workflow was cancelled.")
            break
        if _is_cancel_requested(run_id):
            cancel_message = "Workflow execution was cancelled before the next step started."
            for step_run in remaining:
                _mark_step_skipped(record, step_run, settings, "Skipped because the workflow was cancelled.")
            break

        ready_steps = _ready_step_runs(record)
        if not ready_steps:
            blocked_steps = _blocked_step_runs(record)
            if blocked_steps:
                for step_run in blocked_steps:
                    _mark_step_skipped(
                        record,
                        step_run,
                        settings,
                        "Skipped because a dependency failed before this step could run.",
                    )
                continue
            if queue_parallel_branches and has_active_step_queue_item(record.id, settings):
                return
            for step_run in remaining:
                _mark_step_skipped(record, step_run, settings, "Skipped because the workflow graph stalled.")
            break

        if _maybe_preflight_reuse_research_completion(record, settings):
            continue

        wave = _select_step_wave(ready_steps)
        if queue_parallel_branches and len(wave) > 1 and all(step.execution == "parallel" for step in wave):
            _enqueue_parallel_step_wave(record, wave, settings)
            return
        wave_error, wave_cancel = _execute_step_wave(record, wave, settings, run_id, state_lock)
        if wave_cancel and _is_cancel_requested(run_id):
            cancel_message = wave_cancel
        record = get_workflow_run(run_id, project_path_str, settings)
        _apply_research_short_circuit(record, settings)
        _apply_research_delta_narrowing(record, settings)

    record = get_workflow_run(run_id, project_path_str, settings)
    report_step = step_lookup(record, "report")
    if report_step.status != "completed":
        _reset_step(report_step)
        _mark_step_running(record, report_step, settings)
        try:
            summary = _execute_step_with_agent_session(
                record,
                report_step,
                settings,
                should_cancel=lambda: False,
                set_active_process=lambda process: _set_active_process(run_id, process),
            )
        except Exception as exc:  # noqa: BLE001
            _mark_step_finished(record, report_step, "failed", settings, summary=str(exc))
        else:
            _mark_step_finished(record, report_step, "completed", settings, summary=summary)

    record = get_workflow_run(run_id, project_path_str, settings)
    if cancel_message:
        _finalize_run(record, settings, status="cancelled", message=f"Workflow execution cancelled: {cancel_message}")
        return
    final_status = _final_run_status(record)
    if final_status == "short_circuited":
        _finalize_run(
            record,
            settings,
            status="short_circuited",
            message=record.reuse_reason
            or "Workflow ended early because research determined the task was already satisfied or duplicated.",
        )
        return
    if final_status == "failed":
        _finalize_run(
            record,
            settings,
            status="failed",
            message="Workflow execution completed with partial failures that were carried into review/report.",
            error=record.error or "One or more workflow branches failed or were blocked before completion.",
        )
        return
    _finalize_run(record, settings, status="completed", message="Workflow execution completed successfully.")


def _queue_status_for_record(record: WorkflowRunRecord) -> Literal["completed", "failed", "cancelled"]:
    if record.status == "cancelled":
        return "cancelled"
    if record.status == "failed":
        return "failed"
    return "completed"


def _heartbeat_current_queue_item(
    *,
    stop_event: threading.Event,
    settings: Settings,
    worker_id: str,
    item_id: str,
    run_id: str,
    worker_thread_name: str,
) -> None:
    while not stop_event.wait(max(DEFAULT_WORKER_LEASE_SECONDS / 3, 1)):
        heartbeat_workflow_queue_item(
            item_id=item_id,
            worker_id=worker_id,
            settings=settings,
            lease_seconds=DEFAULT_WORKER_LEASE_SECONDS,
        )
        upsert_workflow_worker(
            settings=settings,
            worker_id=worker_id,
            thread_name=worker_thread_name,
            status="running",
            current_item_id=item_id,
            current_run_id=run_id,
        )


def _enqueue_run_continuation_if_ready(
    *,
    item: WorkflowQueueItem,
    settings: Settings,
) -> None:
    branch_group_id = item["branch_group_id"]
    if not branch_group_id:
        return
    if has_active_branch_group_items(branch_group_id, settings):
        return
    if has_active_run_queue_item(item["run_id"], settings):
        return
    record = get_workflow_run(item["run_id"], item["project_path"], settings)
    enqueue_workflow_run(
        run_id=record.id,
        project_path=record.project_path,
        mode="resume",
        prepared=True,
        item_kind="run",
        settings=settings,
    )
    append_log(record, f"All branch jobs in `{branch_group_id}` are terminal; queued run continuation.")


def _execute_run_queue_item(item: WorkflowQueueItem, settings: Settings) -> None:
    run_id = item["run_id"]
    project_path_str = item["project_path"]
    worker_id = item["worker_id"] or _current_execution_worker_id() or "sync-worker"
    heartbeat_stop = threading.Event()
    heartbeat_thread = threading.Thread(
        target=_heartbeat_current_queue_item,
        kwargs={
            "stop_event": heartbeat_stop,
            "settings": settings,
            "worker_id": worker_id,
            "item_id": item["id"],
            "run_id": run_id,
            "worker_thread_name": threading.current_thread().name,
        },
        daemon=True,
        name=f"workflow-lease-heartbeat-{run_id}",
    )
    try:
        _set_execution_worker_id(worker_id)
        record = get_workflow_run(run_id, project_path_str, settings)
        if not item["prepared"]:
            record = _prepare_run_attempt(record, settings, item["mode"], ignore_active_queue=True)
        _set_active_thread(run_id, threading.current_thread())
        upsert_workflow_worker(
            settings=settings,
            worker_id=worker_id,
            thread_name=threading.current_thread().name,
            status="running",
            current_item_id=item["id"],
            current_run_id=run_id,
        )
        heartbeat_thread.start()
        _execute_workflow_run(record.id, record.project_path, settings, queue_parallel_branches=True)
        final_record = get_workflow_run(run_id, project_path_str, settings)
        complete_workflow_queue_item(
            item_id=item["id"],
            status="completed" if final_record.status == "running" else _queue_status_for_record(final_record),
            settings=settings,
            error=final_record.error,
        )
    except Exception as exc:  # noqa: BLE001
        try:
            record = get_workflow_run(run_id, project_path_str, settings)
            if record.status == "running":
                _finalize_run(
                    record,
                    settings,
                    status="failed",
                    message=f"Workflow execution failed with an unexpected queue worker error: {exc}",
                    error=str(exc),
                )
        finally:
            complete_workflow_queue_item(
                item_id=item["id"],
                status="failed",
                settings=settings,
                error=str(exc),
            )
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=1)
        upsert_workflow_worker(
            settings=settings,
            worker_id=worker_id,
            thread_name=threading.current_thread().name,
            status="idle",
            current_item_id=None,
            current_run_id=None,
        )
        _set_execution_worker_id(None)
        _clear_runtime_handles(run_id)


def _execute_branch_queue_item(item: WorkflowQueueItem, settings: Settings) -> None:
    run_id = item["run_id"]
    project_path_str = item["project_path"]
    target_step_id = item["target_step_id"]
    if not target_step_id:
        complete_workflow_queue_item(
            item_id=item["id"],
            status="failed",
            settings=settings,
            error="Branch queue item had no target step id.",
        )
        return

    worker_id = item["worker_id"] or _current_execution_worker_id() or "sync-worker"
    heartbeat_stop = threading.Event()
    heartbeat_thread = threading.Thread(
        target=_heartbeat_current_queue_item,
        kwargs={
            "stop_event": heartbeat_stop,
            "settings": settings,
            "worker_id": worker_id,
            "item_id": item["id"],
            "run_id": run_id,
            "worker_thread_name": threading.current_thread().name,
        },
        daemon=True,
        name=f"workflow-branch-heartbeat-{run_id}-{target_step_id}",
    )
    try:
        _set_execution_worker_id(worker_id)
        record = get_workflow_run(run_id, project_path_str, settings)
        step_run = step_lookup(record, target_step_id)
        if step_run.status in {"completed", "failed", "skipped", "cancelled"}:
            complete_workflow_queue_item(
                item_id=item["id"],
                status="completed",
                settings=settings,
                error=None,
            )
            _enqueue_run_continuation_if_ready(item=item, settings=settings)
            return

        _set_active_thread(run_id, threading.current_thread())
        upsert_workflow_worker(
            settings=settings,
            worker_id=worker_id,
            thread_name=threading.current_thread().name,
            status="running",
            current_item_id=item["id"],
            current_run_id=run_id,
        )
        heartbeat_thread.start()
        status, message = _execute_single_step_run(
            record,
            step_run,
            settings,
            run_id,
            threading.Lock(),
        )
        complete_workflow_queue_item(
            item_id=item["id"],
            status="failed" if status == "failed" else ("cancelled" if status == "cancelled" else "completed"),
            settings=settings,
            error=message if status in {"failed", "cancelled"} else None,
        )
        _enqueue_run_continuation_if_ready(item=item, settings=settings)
    except Exception as exc:  # noqa: BLE001
        complete_workflow_queue_item(
            item_id=item["id"],
            status="failed",
            settings=settings,
            error=str(exc),
        )
        _enqueue_run_continuation_if_ready(item=item, settings=settings)
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=1)
        upsert_workflow_worker(
            settings=settings,
            worker_id=worker_id,
            thread_name=threading.current_thread().name,
            status="idle",
            current_item_id=None,
            current_run_id=None,
        )
        _set_execution_worker_id(None)
        _clear_runtime_handles(run_id)


def _execute_workflow_queue_item(item: WorkflowQueueItem, settings: Settings) -> None:
    if item["item_kind"] == "step":
        _execute_branch_queue_item(item, settings)
        return
    _execute_run_queue_item(item, settings)


def process_workflow_queue_once(settings: Settings, worker_id: str | None = None) -> bool:
    resolved_worker_id = worker_id or "sync-worker"
    item = claim_next_workflow_queue_item(settings, worker_id=resolved_worker_id)
    if item is None:
        return False
    _execute_workflow_queue_item(item, settings)
    return True


def recover_workflow_queue(settings: Settings) -> int:
    recovered = requeue_interrupted_workflow_queue_items(settings)
    for record in list_workflow_runs(None, settings):
        if record.status != "running":
            continue
        if has_active_workflow_queue_item(record.id, settings):
            continue
        append_log(record, "Recovered orphaned running workflow after backend restart; queueing resume.")
        enqueue_workflow_run(
            run_id=record.id,
            project_path=record.project_path,
            mode="resume",
            prepared=False,
            settings=settings,
        )
        recovered += 1
    return recovered


def _workflow_queue_worker_loop(settings: Settings, worker_id: str) -> None:
    while True:
        upsert_workflow_worker(
            settings=settings,
            worker_id=worker_id,
            thread_name=threading.current_thread().name,
            status="idle",
            current_item_id=None,
            current_run_id=None,
        )
        if not process_workflow_queue_once(settings, worker_id):
            time.sleep(WORKER_POLL_INTERVAL_SECONDS)


def start_workflow_queue_worker(settings: Settings) -> None:
    worker_pool_key = str(settings.agents_team_home)
    with _QUEUE_WORKER_LOCK:
        existing_threads = _QUEUE_WORKERS.get(worker_pool_key, [])
        alive_threads = [thread for thread in existing_threads if thread.is_alive()]
        if len(alive_threads) >= settings.workflow_worker_count:
            _QUEUE_WORKERS[worker_pool_key] = alive_threads
            return
        recover_workflow_queue(settings)
        threads = list(alive_threads)
        for index in range(len(alive_threads), settings.workflow_worker_count):
            worker_key = f"{worker_pool_key}:{index}"
            worker_id = _worker_id_for_key(worker_key)
            thread_name = f"workflow-queue-worker-{index}"
            upsert_workflow_worker(
                settings=settings,
                worker_id=worker_id,
                thread_name=thread_name,
                status="idle",
                current_item_id=None,
                current_run_id=None,
            )
            thread = threading.Thread(
                target=_workflow_queue_worker_loop,
                args=(settings, worker_id),
                daemon=True,
                name=thread_name,
            )
            threads.append(thread)
            thread.start()
        _QUEUE_WORKERS[worker_pool_key] = threads


def _start_attempt(
    run_id: str,
    project_path_str: str | None,
    settings: Settings,
    *,
    mode: RunMode,
    background: bool,
) -> WorkflowRunRecord:
    record = get_workflow_run(run_id, project_path_str, settings)
    record = _prepare_run_attempt(record, settings, mode)
    if record.status == "running" and background and _has_live_thread(run_id):
        return record

    if background:
        enqueue_workflow_run(
            run_id=record.id,
            project_path=record.project_path,
            mode=mode,
            prepared=True,
            settings=settings,
        )
        start_workflow_queue_worker(settings)
        return record

    try:
        _execute_workflow_run(record.id, project_path_str, settings)
    finally:
        _clear_runtime_handles(record.id)
    return get_workflow_run(record.id, project_path_str, settings)


def start_workflow_run(run_id: str, project_path_str: str | None, settings: Settings) -> WorkflowRunRecord:
    return _start_attempt(run_id, project_path_str, settings, mode="start", background=True)


def resume_workflow_run(run_id: str, project_path_str: str | None, settings: Settings) -> WorkflowRunRecord:
    return _start_attempt(run_id, project_path_str, settings, mode="resume", background=True)


def retry_workflow_run(run_id: str, project_path_str: str | None, settings: Settings) -> WorkflowRunRecord:
    return _start_attempt(run_id, project_path_str, settings, mode="retry", background=True)


def cancel_workflow_run(run_id: str, project_path_str: str | None, settings: Settings) -> WorkflowRunRecord:
    record = get_workflow_run(run_id, project_path_str, settings)
    if record.status == "cancelled":
        return record
    if record.status == "completed":
        raise HTTPException(status_code=409, detail=f"Completed runs cannot be cancelled: {record.id}")
    if record.status == "short_circuited":
        raise HTTPException(status_code=409, detail=f"Short-circuited runs cannot be cancelled: {record.id}")
    if record.status == "failed":
        raise HTTPException(status_code=409, detail=f"Failed runs cannot be cancelled; retry or resume instead: {record.id}")

    now = now_iso()
    record.cancel_requested_at = record.cancel_requested_at or now
    record.updated_at = now
    save_record(record, settings)

    if record.status == "planned":
        cancel_active_workflow_queue_items(record.id, settings, reason="Cancelled before execution started.")
        append_log(record, f"Workflow cancellation requested before execution for run `{record.id}`.")
        return _finalize_cancelled_run(record, settings, reason="Cancelled before execution started.")

    append_log(record, f"Workflow cancellation requested for run `{record.id}`.")
    if _has_live_thread(record.id):
        _request_cancel_signal(record.id)
        return get_workflow_run(run_id, project_path_str, settings)

    cancel_active_workflow_queue_items(record.id, settings, reason="Cancelled after recovering an orphaned running state.")
    return _finalize_cancelled_run(record, settings, reason="Cancelled after recovering an orphaned running state.")


def approve_workflow_run_dangerous_commands(
    run_id: str,
    project_path_str: str | None,
    settings: Settings,
    *,
    command_ids: list[str] | None = None,
) -> WorkflowRunRecord:
    record = get_workflow_run(run_id, project_path_str, settings)
    if not record.requires_dangerous_command_confirmation:
        return record
    if record.status == "running":
        raise HTTPException(status_code=409, detail=f"Running runs cannot be re-approved: {record.id}")
    if record.dangerous_commands_confirmed_at and not _pending_dangerous_command_previews(record):
        return record

    previews = _dangerous_command_previews(record)
    if not previews:
        now = now_iso()
        record.dangerous_commands_confirmed_at = now
        record.updated_at = now
        append_log(record, f"Dangerous command execution approved for run `{record.id}`.")
        save_record(record, settings)
        return record

    target_ids = command_ids or [preview.command_id for preview in previews if preview.confirmed_at is None]
    preview_ids = {preview.command_id for preview in previews}
    unknown_ids = [command_id for command_id in target_ids if command_id not in preview_ids]
    if unknown_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown dangerous command preview id(s): {', '.join(unknown_ids)}",
        )

    now = now_iso()
    record.updated_at = now
    approved_labels: list[str] = []

    for step in record.steps:
        for preview in step.command_previews:
            if preview.command_id in target_ids and preview.confirmed_at is None:
                preview.confirmed_at = now
                approved_labels.append(preview.label)

    for step_run in record.step_runs:
        for preview in step_run.command_previews:
            if preview.command_id in target_ids and preview.confirmed_at is None:
                preview.confirmed_at = now

    _sync_dangerous_confirmation_state(record)
    if approved_labels:
        append_log(
            record,
            "Approved dangerous command preview(s) for run "
            f"`{record.id}`: {', '.join(approved_labels)}.",
        )
    if record.dangerous_commands_confirmed_at:
        append_log(record, f"All dangerous command previews are approved for run `{record.id}`.")
    save_record(record, settings)
    return record


def execute_workflow_run_now(run_id: str, project_path_str: str | None, settings: Settings) -> WorkflowRunRecord:
    return _start_attempt(run_id, project_path_str, settings, mode="start", background=False)


def resume_workflow_run_now(run_id: str, project_path_str: str | None, settings: Settings) -> WorkflowRunRecord:
    return _start_attempt(run_id, project_path_str, settings, mode="resume", background=False)


def retry_workflow_run_now(run_id: str, project_path_str: str | None, settings: Settings) -> WorkflowRunRecord:
    return _start_attempt(run_id, project_path_str, settings, mode="retry", background=False)
