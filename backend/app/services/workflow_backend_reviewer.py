from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from app.config import Settings
from app.models.dto import WorkflowRunRecord
from app.services.workflow_artifact_paths import review_result_path
from app.services.workflow_backend_codex_delegate import execute_delegated_codex_backend
from app.services.workflow_contracts import (
    build_local_review_result_contract,
    load_review_result_contract,
    write_review_result_contract,
)
from app.services.workflow_run_store import append_log
from app.services.workflow_run_store import step_lookup


def _reviewer_prompt(record: WorkflowRunRecord) -> str:
    return "\n".join(
        [
            "You are the reviewer backend for an Agents Team workflow.",
            "Produce a single JSON object and nothing else.",
            "Focus on regressions, changed files, risks, and reviewer memory cross-checks without reading historical workflow artifacts.",
            "",
            f"Run id: {record.id}",
            f"Task: {record.task}",
            "",
            "Read `.agents-context/run-state.json`, `.agents-context/step-context.json`, `.agents-context/changed.diff`, and `.agents-context/verify-summary.json` first.",
            "",
            "Output schema:",
            "{",
            '  "run_id": string,',
            '  "task": string,',
            '  "reviewer_memory_cross_checks": string[],',
            '  "changed_files": string[],',
            '  "risk_assessment": string[],',
            '  "open_questions": string[],',
            '  "git_status_excerpt": string|null,',
            '  "diff_stat_excerpt": string|null,',
            '  "summary": string',
            "}",
        ]
    )


def execute_reviewer_backend(
    record: WorkflowRunRecord,
    settings: Settings,
    should_cancel: Callable[[], bool],
    set_active_process: Callable[[subprocess.Popen[str] | None], None],
) -> str:
    step_run = step_lookup(record, "review")
    summary = execute_delegated_codex_backend(
        record=record,
        step_run=step_run,
        settings=settings,
        backend_label="Reviewer backend",
        artifact_path=review_result_path(record),
        prompt=_reviewer_prompt(record),
        should_cancel=should_cancel,
        set_active_process=set_active_process,
        fallback=lambda: _local_review(record),
    )
    try:
        contract = load_review_result_contract(record)
    except Exception as exc:  # noqa: BLE001
        append_log(record, f"Reviewer backend produced an invalid JSON contract; falling back to local contract generation: {exc}")
        return _local_review(record)
    if contract is None:
        return _local_review(record)
    write_review_result_contract(record, contract)
    return summary


def _local_review(record: WorkflowRunRecord) -> str:
    contract = build_local_review_result_contract(record)
    write_review_result_contract(record, contract)
    return contract.summary
