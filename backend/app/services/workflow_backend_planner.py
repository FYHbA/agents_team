from __future__ import annotations

import subprocess
from collections.abc import Callable

from app.config import Settings
from app.models.dto import WorkflowRunRecord
from app.services.workflow_artifact_paths import planning_brief_path
from app.services.workflow_backend_codex_delegate import execute_delegated_codex_backend
from app.services.workflow_run_store import step_lookup


def _local_planning_brief(record: WorkflowRunRecord) -> str:
    brief_lines = [
        f"# Planning Brief for {record.id}",
        "",
        f"Task: {record.task}",
        f"Project: `{record.project_path}`",
        "",
        "## Planner Memory Guidance",
        "",
        *([f"- {item}" for item in record.memory_guidance.planner] or ["- No planner guidance was generated."]),
        "",
        "## Workflow Steps",
        "",
        *[f"- `{step.id}` via `{step.backend}`: {step.goal}" for step in record.steps],
        "",
    ]
    planning_brief_path(record).write_text("\n".join(brief_lines), encoding="utf-8")

    planner_count = len(record.memory_guidance.planner)
    if planner_count:
        return (
            f"Planner backend locked a workflow with {len(record.agents)} agent role(s), {len(record.steps)} step(s), "
            f"and {planner_count} planner memory cue(s) using the local fallback."
        )
    return f"Planner backend locked a workflow with {len(record.agents)} agent role(s) and {len(record.steps)} step(s) using the local fallback."


def _planner_prompt(record: WorkflowRunRecord) -> str:
    return "\n".join(
        [
            "You are the planner backend for an Agents Team workflow.",
            "Produce a markdown planning brief for the run.",
            "Use the structured files in `.agents-context/` as your only workflow context source.",
            "Focus on sequencing, continuity risks, recalled memory summaries, and explicit handoff expectations.",
            "",
            f"Run id: {record.id}",
            f"Task: {record.task}",
            "",
            "Read `.agents-context/project-summary.json`, `.agents-context/run-state.json`, `.agents-context/step-context.json`, and `.agents-context/selected-memory.json` first.",
            "",
            "Output sections:",
            "- Objective",
            "- Continuity Risks",
            "- Step Plan",
            "- Approval And Validation Notes",
        ]
    )


def execute_planner_backend(
    record: WorkflowRunRecord,
    settings: Settings,
    should_cancel: Callable[[], bool],
    set_active_process: Callable[[subprocess.Popen[str] | None], None],
) -> str:
    step_run = step_lookup(record, "plan")
    return execute_delegated_codex_backend(
        record=record,
        step_run=step_run,
        settings=settings,
        backend_label="Planner backend",
        artifact_path=planning_brief_path(record),
        prompt=_planner_prompt(record),
        should_cancel=should_cancel,
        set_active_process=set_active_process,
        fallback=lambda: _local_planning_brief(record),
    )
