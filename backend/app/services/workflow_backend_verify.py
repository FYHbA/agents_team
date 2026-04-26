from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from app.config import Settings
from app.models.dto import WorkflowRunRecord, WorkflowStepRun
from app.services.workflow_artifact_paths import verification_brief_path
from app.services.workflow_backend_codex_delegate import execute_delegated_codex_backend
from app.services.workflow_backend_exceptions import WorkflowExecutionError
from app.services.workflow_backend_runtime import run_command, verification_commands

VERIFY_TIMEOUT_SECONDS = 60 * 10


def _write_local_verification_brief(record: WorkflowRunRecord, executed: list[str]) -> None:
    executed_lines = [f"- {item}" for item in executed] or ["- No verification commands were detected."]
    verification_brief_path(record).write_text(
        "\n".join(
            [
                f"# Verification Brief for {record.id}",
                "",
                "## Executed Commands",
                "",
                *executed_lines,
                "",
                "## Verification Scope",
                "",
                f"Task: {record.task}",
                "",
                "## Notes",
                "",
                *([f"- {item}" for item in record.memory_guidance.reviewer] or ["- No reviewer memory checklist was available."]),
                "",
            ]
        ),
        encoding="utf-8",
    )


def _verification_focus(step_run: WorkflowStepRun) -> str:
    if step_run.step_id == "verify_tests":
        return "tests"
    if step_run.step_id == "verify_build":
        return "build"
    return "all"


def _local_verify(
    record: WorkflowRunRecord,
    step_run: WorkflowStepRun,
    should_cancel: Callable[[], bool],
    set_active_process: Callable[[subprocess.Popen[str] | None], None],
) -> str:
    commands = verification_commands(Path(record.project_path), focus=_verification_focus(step_run))
    if not commands:
        _write_local_verification_brief(record, [])
        return f"Verify backend found no standard verification commands for `{step_run.step_id}`, but still wrote a local verification brief."

    executed: list[str] = []
    for label, argv in commands:
        completed = run_command(
            argv,
            settings=settings,
            cwd=record.project_path,
            timeout=VERIFY_TIMEOUT_SECONDS,
            log_prefix=label,
            record=record,
            should_cancel=should_cancel,
            set_active_process=set_active_process,
        )
        if completed.returncode != 0:
            raise WorkflowExecutionError(f"Verification command failed: {label}")
        executed.append(label)

    _write_local_verification_brief(record, executed)
    return f"Verify backend completed {len(executed)} local verification command(s) for `{step_run.step_id}`: {', '.join(executed)}."


def _verify_prompt(record: WorkflowRunRecord, step_run: WorkflowStepRun) -> str:
    return "\n".join(
        [
            "You are the verify backend for an Agents Team workflow.",
            "In read-only mode, run or reason through the project's standard verification commands and produce a markdown verification brief.",
            "Do not edit project files. Focus on command coverage, outcomes, and reusable validation risks.",
            "",
            f"Run id: {record.id}",
            f"Verify step id: {step_run.step_id}",
            f"Task: {record.task}",
            "",
            "Reviewer memory checklist:",
            *([f"- {item}" for item in record.memory_guidance.reviewer] or ["- No reviewer checklist was generated."]),
            "",
            "Output sections:",
            "- Executed Commands",
            "- Result Summary",
            "- Validation Risks",
            "- Follow-up Checks",
        ]
    )


def execute_verify_backend(
    record: WorkflowRunRecord,
    step_run: WorkflowStepRun,
    settings: Settings,
    should_cancel: Callable[[], bool],
    set_active_process: Callable[[subprocess.Popen[str] | None], None],
) -> str:
    return execute_delegated_codex_backend(
        record=record,
        settings=settings,
        backend_label="Verify backend",
        artifact_path=verification_brief_path(record),
        prompt=_verify_prompt(record, step_run),
        should_cancel=should_cancel,
        set_active_process=set_active_process,
        fallback=lambda: _local_verify(record, step_run, should_cancel, set_active_process),
    )
