from __future__ import annotations

import json
import threading
from collections import defaultdict
from uuid import uuid4

from app.config import Settings
from app.models.dto import (
    WorkflowAgentCommandRecord,
    WorkflowAgentSessionEventRecord,
    WorkflowAgentSessionRecord,
    WorkflowRunRecord,
    WorkflowStepRun,
)
from app.services.workflow_control_db import connect_control_db, initialize_control_db
from app.services.workflow_run_store import now_iso, trim_summary

_AGENT_RUNTIME = threading.local()


def clear_agent_runtime_metadata() -> None:
    _AGENT_RUNTIME.provider = None
    _AGENT_RUNTIME.session_ref = None
    _AGENT_RUNTIME.session_id = None
    _AGENT_RUNTIME.run_id = None
    _AGENT_RUNTIME.step_id = None
    _AGENT_RUNTIME.event_sequence = 0


def set_agent_runtime_metadata(*, provider: str, session_ref: str | None = None) -> None:
    _AGENT_RUNTIME.provider = provider
    _AGENT_RUNTIME.session_ref = session_ref


def get_agent_runtime_metadata() -> tuple[str | None, str | None]:
    return (
        getattr(_AGENT_RUNTIME, "provider", None),
        getattr(_AGENT_RUNTIME, "session_ref", None),
    )


def _set_active_agent_session(*, session_id: str, run_id: str, step_id: str) -> None:
    _AGENT_RUNTIME.session_id = session_id
    _AGENT_RUNTIME.run_id = run_id
    _AGENT_RUNTIME.step_id = step_id
    _AGENT_RUNTIME.event_sequence = 0


def _get_active_agent_session() -> tuple[str | None, str | None, str | None]:
    return (
        getattr(_AGENT_RUNTIME, "session_id", None),
        getattr(_AGENT_RUNTIME, "run_id", None),
        getattr(_AGENT_RUNTIME, "step_id", None),
    )


def _next_event_sequence() -> int:
    sequence = int(getattr(_AGENT_RUNTIME, "event_sequence", 0)) + 1
    _AGENT_RUNTIME.event_sequence = sequence
    return sequence


def start_agent_session(
    *,
    record: WorkflowRunRecord,
    step_run: WorkflowStepRun,
    settings: Settings,
    worker_id: str | None,
) -> WorkflowAgentSessionRecord:
    initialize_control_db(settings)
    session = WorkflowAgentSessionRecord(
        id=f"agent-{uuid4().hex[:12]}",
        run_id=record.id,
        step_id=step_run.step_id,
        title=step_run.title,
        agent_role=step_run.agent_role,
        backend=step_run.backend,
        execution=step_run.execution,
        status="running",
        owner_worker_id=worker_id,
        provider=None,
        session_ref=None,
        started_at=now_iso(),
        completed_at=None,
        summary=None,
        error=None,
        events=[],
    )
    connection = connect_control_db(settings)
    try:
        connection.execute(
            """
            INSERT INTO workflow_agent_sessions (
                id,
                run_id,
                step_id,
                title,
                agent_role,
                backend,
                execution,
                status,
                owner_worker_id,
                provider,
                session_ref,
                started_at,
                completed_at,
                summary,
                error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.id,
                session.run_id,
                session.step_id,
                session.title,
                session.agent_role,
                session.backend,
                session.execution,
                session.status,
                session.owner_worker_id,
                session.provider,
                session.session_ref,
                session.started_at,
                session.completed_at,
                session.summary,
                session.error,
            ),
        )
    finally:
        connection.close()

    _set_active_agent_session(session_id=session.id, run_id=session.run_id, step_id=session.step_id)
    return session


def append_agent_session_event(
    *,
    settings: Settings,
    event_type: str,
    payload: dict,
    session_id: str | None = None,
    run_id: str | None = None,
    step_id: str | None = None,
) -> None:
    active_session_id, active_run_id, active_step_id = _get_active_agent_session()
    resolved_session_id = session_id or active_session_id
    resolved_run_id = run_id or active_run_id
    resolved_step_id = step_id or active_step_id
    if not resolved_session_id or not resolved_run_id or not resolved_step_id:
        return

    initialize_control_db(settings)
    event = WorkflowAgentSessionEventRecord(
        id=f"event-{uuid4().hex[:14]}",
        session_id=resolved_session_id,
        run_id=resolved_run_id,
        step_id=resolved_step_id,
        sequence=_next_event_sequence(),
        created_at=now_iso(),
        event_type=event_type,
        payload=payload,
    )
    connection = connect_control_db(settings)
    try:
        connection.execute(
            """
            INSERT INTO workflow_agent_session_events (
                id,
                session_id,
                run_id,
                step_id,
                sequence,
                created_at,
                event_type,
                payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.id,
                event.session_id,
                event.run_id,
                event.step_id,
                event.sequence,
                event.created_at,
                event.event_type,
                json.dumps(event.payload, ensure_ascii=False),
            ),
        )
    finally:
        connection.close()


def finish_agent_session(
    *,
    session_id: str,
    settings: Settings,
    status: str,
    summary: str | None,
    error: str | None = None,
) -> None:
    initialize_control_db(settings)
    provider, session_ref = get_agent_runtime_metadata()
    completed_at = now_iso()
    connection = connect_control_db(settings)
    try:
        connection.execute(
            """
            UPDATE workflow_agent_sessions
            SET status = ?,
                provider = COALESCE(?, provider),
                session_ref = COALESCE(?, session_ref),
                completed_at = ?,
                summary = ?,
                error = ?
            WHERE id = ?
            """,
            (status, provider, session_ref, completed_at, summary, error, session_id),
        )
    finally:
        connection.close()

    append_agent_session_event(
        settings=settings,
        event_type="session_summary",
        payload={
            "status": status,
            "summary": summary or "",
            "error": error or "",
            "provider": provider,
            "session_ref": session_ref,
        },
        session_id=session_id,
    )


def _normalize_command_status(value: str | None) -> str:
    if not value:
        return "completed"
    if value == "in_progress":
        return "running"
    return value


def _populate_session_presentation(session: WorkflowAgentSessionRecord) -> None:
    if not session.events:
        session.has_structured_timeline = False
        session.thinking_messages = []
        session.final_message = session.summary or session.error
        session.collapsed_preview = trim_summary(session.final_message, limit=180)
        session.commands = []
        return

    agent_messages: list[str] = []
    command_map: dict[str, WorkflowAgentCommandRecord] = {}

    for event in session.events:
        if event.event_type == "agent_message":
            text = event.payload.get("text")
            if isinstance(text, str):
                cleaned = text.strip()
                if cleaned:
                    agent_messages.append(cleaned)
            continue

        if event.event_type == "command_execution":
            command_id = event.payload.get("command_id")
            resolved_command_id = str(command_id) if isinstance(command_id, str) and command_id else event.id
            existing = command_map.get(resolved_command_id)
            label = event.payload.get("label")
            command = event.payload.get("command")
            output = event.payload.get("output")
            command_map[resolved_command_id] = WorkflowAgentCommandRecord(
                id=resolved_command_id,
                label=str(label) if isinstance(label, str) and label else (str(command) if isinstance(command, str) and command else "Shell command"),
                command=str(command) if isinstance(command, str) else (existing.command if existing else ""),
                status=_normalize_command_status(str(event.payload.get("status") or "")),
                output=str(output) if isinstance(output, str) else (existing.output if existing else ""),
                exit_code=int(event.payload["exit_code"]) if isinstance(event.payload.get("exit_code"), int) else (existing.exit_code if existing else None),
                sequence=event.sequence,
            )

    if agent_messages:
        if session.status == "running":
            thinking_messages = agent_messages
            final_message = None
        else:
            thinking_messages = agent_messages[:-1]
            final_message = agent_messages[-1]
    else:
        thinking_messages = []
        final_message = session.summary or session.error

    session.has_structured_timeline = True
    session.thinking_messages = thinking_messages
    session.final_message = final_message
    session.collapsed_preview = trim_summary(final_message or session.summary or session.error, limit=180)
    session.commands = sorted(command_map.values(), key=lambda item: item.sequence)


def delete_agent_sessions(run_id: str, settings: Settings) -> None:
    initialize_control_db(settings)
    connection = connect_control_db(settings)
    try:
        connection.execute(
            """
            DELETE FROM workflow_agent_session_events
            WHERE run_id = ?
            """,
            (run_id,),
        )
        connection.execute(
            """
            DELETE FROM workflow_agent_sessions
            WHERE run_id = ?
            """,
            (run_id,),
        )
    finally:
        connection.close()


def list_agent_sessions(run_id: str, settings: Settings) -> list[WorkflowAgentSessionRecord]:
    initialize_control_db(settings)
    connection = connect_control_db(settings)
    try:
        session_rows = connection.execute(
            """
            SELECT
                id,
                run_id,
                step_id,
                title,
                agent_role,
                backend,
                execution,
                status,
                owner_worker_id,
                provider,
                session_ref,
                started_at,
                completed_at,
                summary,
                error
            FROM workflow_agent_sessions
            WHERE run_id = ?
            ORDER BY started_at ASC, id ASC
            """,
            (run_id,),
        ).fetchall()
        event_rows = connection.execute(
            """
            SELECT
                id,
                session_id,
                run_id,
                step_id,
                sequence,
                created_at,
                event_type,
                payload
            FROM workflow_agent_session_events
            WHERE run_id = ?
            ORDER BY session_id ASC, sequence ASC, created_at ASC
            """,
            (run_id,),
        ).fetchall()
    finally:
        connection.close()

    events_by_session: dict[str, list[WorkflowAgentSessionEventRecord]] = defaultdict(list)
    for row in event_rows:
        payload: dict = {}
        if row["payload"]:
            try:
                parsed = json.loads(str(row["payload"]))
                if isinstance(parsed, dict):
                    payload = parsed
            except json.JSONDecodeError:
                payload = {"raw": str(row["payload"])}
        events_by_session[str(row["session_id"])].append(
            WorkflowAgentSessionEventRecord(
                id=str(row["id"]),
                session_id=str(row["session_id"]),
                run_id=str(row["run_id"]),
                step_id=str(row["step_id"]),
                sequence=int(row["sequence"]),
                created_at=str(row["created_at"]),
                event_type=str(row["event_type"]),
                payload=payload,
            )
        )

    sessions: list[WorkflowAgentSessionRecord] = []
    for row in session_rows:
        session = WorkflowAgentSessionRecord.model_validate(dict(row))
        session.events = events_by_session.get(session.id, [])
        _populate_session_presentation(session)
        sessions.append(session)
    return sessions
