from __future__ import annotations

import json

from app.config import Settings
from app.models.dto import (
    WorkflowContextAuditRecord,
    WorkflowContextAuditSourceRecord,
    WorkflowRunContextAuditsResponse,
)
from app.services.workflow_control_db import connect_control_db, initialize_control_db


def read_workflow_context_audits(run_id: str, settings: Settings) -> WorkflowRunContextAuditsResponse:
    initialize_control_db(settings)
    connection = connect_control_db(settings)
    try:
        rows = connection.execute(
            """
            SELECT
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
            FROM workflow_context_audits
            WHERE run_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (run_id,),
        ).fetchall()
    finally:
        connection.close()

    audits: list[WorkflowContextAuditRecord] = []
    for row in rows:
        raw_sources = []
        if row["input_sources_json"]:
            try:
                parsed = json.loads(str(row["input_sources_json"]))
                if isinstance(parsed, list):
                    raw_sources = parsed
            except json.JSONDecodeError:
                raw_sources = []
        input_sources = [
            WorkflowContextAuditSourceRecord.model_validate(item)
            for item in raw_sources
            if isinstance(item, dict)
        ]
        audits.append(
            WorkflowContextAuditRecord(
                id=str(row["id"]),
                run_id=str(row["run_id"]),
                step_id=str(row["step_id"]),
                agent_role=str(row["agent_role"]),
                backend=str(row["backend"]),
                workspace_path=str(row["workspace_path"]),
                input_sources=input_sources,
                input_bytes=int(row["input_bytes"]),
                memory_item_count=int(row["memory_item_count"]),
                raw_log_bytes_included=int(row["raw_log_bytes_included"]),
                markdown_artifact_bytes_included=int(row["markdown_artifact_bytes_included"]),
                forbidden_source_attempts=int(row["forbidden_source_attempts"]),
                input_tokens=int(row["input_tokens"]) if row["input_tokens"] is not None else None,
                cached_tokens=int(row["cached_tokens"]) if row["cached_tokens"] is not None else None,
                output_tokens=int(row["output_tokens"]) if row["output_tokens"] is not None else None,
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )
        )

    return WorkflowRunContextAuditsResponse(
        run_id=run_id,
        audits=audits,
        total_input_bytes=sum(item.input_bytes for item in audits),
        total_forbidden_source_attempts=sum(item.forbidden_source_attempts for item in audits),
        total_memory_items=sum(item.memory_item_count for item in audits),
        total_input_tokens=(sum(item.input_tokens for item in audits if item.input_tokens is not None) if any(item.input_tokens is not None for item in audits) else None),
        total_cached_tokens=(sum(item.cached_tokens for item in audits if item.cached_tokens is not None) if any(item.cached_tokens is not None for item in audits) else None),
        total_output_tokens=(sum(item.output_tokens for item in audits if item.output_tokens is not None) if any(item.output_tokens is not None for item in audits) else None),
    )
