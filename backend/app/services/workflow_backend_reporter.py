from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from app.config import Settings
from app.models.dto import WorkflowRunRecord
from app.services.workflow_contracts import build_final_state_contract, write_final_state_contract
from app.services.workflow_backend_codex_delegate import execute_delegated_codex_backend
from app.services.workflow_run_store import step_lookup


def _step_summary_lines(record: WorkflowRunRecord) -> list[str]:
    lines: list[str] = []
    for step_run in record.step_runs:
        line = f"- `{step_run.step_id}` `{step_run.status}` via `{step_run.backend}`"
        if step_run.summary:
            line = f"{line}: {step_run.summary}"
        lines.append(line)
    return lines


def _local_report(record: WorkflowRunRecord) -> str:
    contract = build_final_state_contract(record)
    write_final_state_contract(record, contract)
    return "Reporter backend updated the final handoff report with role-specific guidance, changes, and memory outcomes using the local fallback."


def _reporter_prompt(record: WorkflowRunRecord) -> str:
    return "\n".join(
        [
            "You are the reporter backend for an Agents Team workflow.",
            "Produce the final markdown handoff report for the run.",
            "Use the structured files in `.agents-context/` instead of reading historical workflow artifacts directly.",
            "",
            f"Run id: {record.id}",
            f"Task: {record.task}",
            "",
            "Read `.agents-context/run-state.json`, `.agents-context/step-context.json`, and `.agents-context/final-state.json` first.",
            "",
            "Output sections:",
            "- Task",
            "- Step Outcomes",
            "- Memory Recall",
            "- Codex Final Message",
            "- Change Summary",
            "- Memory Writes",
            "- Promoted Global Rules",
            "- Warnings",
        ]
    )


def execute_reporter_backend(
    record: WorkflowRunRecord,
    settings: Settings,
    should_cancel: Callable[[], bool],
    set_active_process: Callable[[subprocess.Popen[str] | None], None],
) -> str:
    contract = build_final_state_contract(record)
    write_final_state_contract(record, contract)
    step_run = step_lookup(record, "report")
    return execute_delegated_codex_backend(
        record=record,
        step_run=step_run,
        settings=settings,
        backend_label="Reporter backend",
        artifact_path=Path(record.report_path),
        prompt=_reporter_prompt(record),
        should_cancel=should_cancel,
        set_active_process=set_active_process,
        fallback=lambda: _local_report(record),
    )
