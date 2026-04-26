from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from app.config import Settings
from app.models.dto import WorkflowRunRecord
from app.services.workflow_artifact_paths import project_snapshot_path, research_result_path
from app.services.workflow_backend_codex_delegate import execute_delegated_codex_backend
from app.services.workflow_contracts import (
    build_local_research_result_contract,
    load_research_result_contract,
    write_research_result_contract,
)
from app.services.workflow_context_policy import PROJECT_PROJECTION_EXCLUDES
from app.services.workflow_reuse import infer_reuse_decision
from app.services.workflow_run_store import append_log
from app.services.workflow_run_store import step_lookup


def _top_level_entries(project_path: Path, limit: int = 60) -> list[str]:
    entries: list[str] = []
    for child in sorted(project_path.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))[:limit]:
        if child.name in PROJECT_PROJECTION_EXCLUDES:
            continue
        suffix = "/" if child.is_dir() else ""
        entries.append(f"{child.name}{suffix}")
    return entries


def _local_research_result(record: WorkflowRunRecord, settings: Settings) -> str:
    decision, matched_run_id, confidence, reason, delta_hint, delta_scope = infer_reuse_decision(record, settings)
    contract = build_local_research_result_contract(
        record,
        top_level_entries=_top_level_entries(Path(record.project_path)),
        decision=decision,
        matched_run_id=matched_run_id,
        confidence=confidence,
        reason=reason,
        delta_hint=delta_hint,
        delta_scope=delta_scope,
    )
    write_research_result_contract(record, contract)
    return contract.summary


def _research_prompt(record: WorkflowRunRecord) -> str:
    return "\n".join(
        [
            "You are the research backend for an Agents Team workflow.",
            "Produce a single JSON object and nothing else.",
            "Do not discover historical workflow files. Focus on repo shape, relevant hotspots, continuity notes from selected memory summaries, and whether a recent successful run already satisfies this task.",
            "",
            f"Run id: {record.id}",
            f"Task: {record.task}",
            "",
            "Read `.agents-context/repo-snapshot.json`, `.agents-context/run-state.json`, `.agents-context/step-context.json`, `.agents-context/selected-memory.json`, and `.agents-context/recent-runs.json` first.",
            "",
            "Output schema:",
            "{",
            '  "decision": "continue" | "stop_as_duplicate" | "stop_as_already_satisfied" | "continue_with_delta",',
            '  "matched_run_id": string | null,',
            '  "confidence": number,',
            '  "reason": string,',
            '  "delta_hint": string,',
            '  "delta_scope": {"focus_paths": string[], "matched_run_changed_files": string[], "current_diff_files": string[], "verification_focus": "all"|"tests"|"build"|"docs", "scope_summary": string} | null,',
            '  "run_id": string,',
            '  "task": string,',
            '  "project_root": string,',
            '  "top_level_entries": string[],',
            '  "relevant_hotspots": string[],',
            '  "continuity_notes": string[],',
            '  "suggested_next_attention_areas": string[],',
            '  "summary": string',
            "}",
        ]
    )


def execute_research_backend(
    record: WorkflowRunRecord,
    settings: Settings,
    should_cancel: Callable[[], bool],
    set_active_process: Callable[[subprocess.Popen[str] | None], None],
) -> str:
    step_run = step_lookup(record, "research")
    summary = execute_delegated_codex_backend(
        record=record,
        step_run=step_run,
        settings=settings,
        backend_label="Research backend",
        artifact_path=research_result_path(record),
        prompt=_research_prompt(record),
        should_cancel=should_cancel,
        set_active_process=set_active_process,
        fallback=lambda: _local_research_result(record, settings),
    )
    try:
        contract = load_research_result_contract(record)
    except Exception as exc:  # noqa: BLE001
        append_log(record, f"Research backend produced an invalid JSON contract; falling back to local contract generation: {exc}")
        return _local_research_result(record, settings)
    if contract is None:
        return _local_research_result(record, settings)
    write_research_result_contract(record, contract)
    return summary
