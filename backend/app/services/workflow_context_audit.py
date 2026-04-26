from __future__ import annotations

import json
import threading
from uuid import uuid4

from app.config import Settings
from app.models.dto import WorkflowRunRecord, WorkflowStepRun
from app.services.workflow_control_db import connect_control_db, initialize_control_db
from app.services.workflow_run_store import now_iso

_ACTIVE_CONTEXT_AUDIT = threading.local()


def set_active_context_audit(audit_id: str | None) -> None:
    _ACTIVE_CONTEXT_AUDIT.audit_id = audit_id


def _active_context_audit_id() -> str | None:
    return getattr(_ACTIVE_CONTEXT_AUDIT, "audit_id", None)


def create_context_audit(
    *,
    record: WorkflowRunRecord,
    step_run: WorkflowStepRun,
    settings: Settings,
    workspace_path: str,
    input_sources: list[dict[str, object]],
    input_bytes: int,
    memory_item_count: int,
    raw_log_bytes_included: int,
    markdown_artifact_bytes_included: int,
) -> str:
    initialize_control_db(settings)
    audit_id = f"context-{uuid4().hex[:12]}"
    created_at = now_iso()
    connection = connect_control_db(settings)
    try:
        connection.execute(
            """
            INSERT INTO workflow_context_audits (
                id,
                run_id,
                step_id,
                agent_role,
                backend,
                workspace_path,
                input_sources_json,
                input_bytes,
                memory_item_count,
                raw_log_bytes_included,
                markdown_artifact_bytes_included,
                forbidden_source_attempts,
                input_tokens,
                cached_tokens,
                output_tokens,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, NULL, NULL, ?, ?)
            """,
            (
                audit_id,
                record.id,
                step_run.step_id,
                step_run.agent_role,
                step_run.backend,
                workspace_path,
                json.dumps(input_sources, ensure_ascii=False),
                input_bytes,
                memory_item_count,
                raw_log_bytes_included,
                markdown_artifact_bytes_included,
                created_at,
                created_at,
            ),
        )
    finally:
        connection.close()
    return audit_id


def record_forbidden_source_attempt(settings: Settings, command: str) -> bool:
    audit_id = _active_context_audit_id()
    if not audit_id:
        return False
    initialize_control_db(settings)
    connection = connect_control_db(settings)
    try:
        updated = connection.execute(
            """
            UPDATE workflow_context_audits
            SET forbidden_source_attempts = forbidden_source_attempts + 1,
                updated_at = ?
            WHERE id = ?
            """,
            (now_iso(), audit_id),
        ).rowcount
    finally:
        connection.close()
    return bool(updated)


def update_context_audit_usage(
    *,
    settings: Settings,
    input_tokens: int | None = None,
    cached_tokens: int | None = None,
    output_tokens: int | None = None,
) -> None:
    audit_id = _active_context_audit_id()
    if not audit_id:
        return
    initialize_control_db(settings)
    connection = connect_control_db(settings)
    try:
        connection.execute(
            """
            UPDATE workflow_context_audits
            SET input_tokens = COALESCE(?, input_tokens),
                cached_tokens = COALESCE(?, cached_tokens),
                output_tokens = COALESCE(?, output_tokens),
                updated_at = ?
            WHERE id = ?
            """,
            (input_tokens, cached_tokens, output_tokens, now_iso(), audit_id),
        )
    finally:
        connection.close()
