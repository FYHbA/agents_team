from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from app.config import Settings
from app.models.dto import VerifyCommandResultContract, WorkflowRunRecord, WorkflowStepRun
from app.services.workflow_artifact_paths import verification_brief_path, verify_summary_path
from app.services.workflow_backend_codex_delegate import execute_delegated_codex_backend
from app.services.workflow_backend_exceptions import WorkflowExecutionError
from app.services.workflow_contracts import (
    MAX_VERIFICATION_OUTPUT_EXCERPT,
    build_local_verify_summary_contract,
    load_verify_summary_contract,
    write_verify_summary_contract,
)
from app.services.workflow_backend_runtime import run_command, verification_commands
from app.services.workflow_run_store import append_log, trim_summary

VERIFY_TIMEOUT_SECONDS = 60 * 10


def _verification_focus(step_run: WorkflowStepRun) -> str:
    if step_run.step_id == "verify_tests":
        return "tests"
    if step_run.step_id == "verify_build":
        return "build"
    return "all"


def _resolved_verification_focus(record: WorkflowRunRecord, step_run: WorkflowStepRun) -> str:
    base_focus = _verification_focus(step_run)
    if record.reuse_decision != "continue_with_delta" or record.delta_scope is None:
        return base_focus

    narrowed_focus = record.delta_scope.verification_focus
    if step_run.step_id == "verify_tests":
        return "tests" if narrowed_focus in {"all", "tests"} else "none"
    if step_run.step_id == "verify_build":
        return "build" if narrowed_focus in {"all", "build"} else "none"
    return narrowed_focus


def _delta_scope_follow_up(record: WorkflowRunRecord) -> str | None:
    if record.delta_scope is None:
        return None
    if record.delta_scope.focus_paths:
        return "Delta scope paths: " + ", ".join(record.delta_scope.focus_paths[:4]) + "."
    if record.delta_scope.scope_summary:
        return record.delta_scope.scope_summary
    return None


def _local_verify(
    record: WorkflowRunRecord,
    step_run: WorkflowStepRun,
    settings: Settings,
    should_cancel: Callable[[], bool],
    set_active_process: Callable[[subprocess.Popen[str] | None], None],
) -> str:
    resolved_focus = _resolved_verification_focus(record, step_run)
    commands = verification_commands(Path(record.project_path), focus=resolved_focus)
    if not commands:
        if record.reuse_decision == "continue_with_delta":
            scope_note = _delta_scope_follow_up(record)
            result_summary = (
                f"Verify backend kept `{step_run.step_id}` lightweight because the narrowed delta does not require this verification lane."
                if resolved_focus == "none"
                else f"Verify backend found no standard verification commands for `{step_run.step_id}` inside the narrowed delta scope."
            )
            follow_up_checks = [scope_note] if scope_note else []
            contract = build_local_verify_summary_contract(
                record,
                step_id=step_run.step_id,
                commands=[],
                result_summary=result_summary,
                validation_risks=[],
                follow_up_checks=follow_up_checks,
            )
            write_verify_summary_contract(record, contract)
            return contract.summary
        contract = build_local_verify_summary_contract(
            record,
            step_id=step_run.step_id,
            commands=[],
            result_summary=f"Verify backend found no standard verification commands for `{step_run.step_id}`, but still wrote a local verification brief.",
            validation_risks=["No standard verification commands were detected for this project."],
        )
        write_verify_summary_contract(record, contract)
        return contract.summary

    executed: list[VerifyCommandResultContract] = []
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
        output_excerpt = trim_summary(
            "\n".join(part for part in [completed.stdout.strip(), completed.stderr.strip()] if part),
            limit=MAX_VERIFICATION_OUTPUT_EXCERPT,
        )
        executed.append(
            VerifyCommandResultContract(
                label=label,
                status="completed",
                exit_code=completed.returncode,
                output_excerpt=output_excerpt,
            )
        )

    summary = f"Verify backend completed {len(executed)} local verification command(s) for `{step_run.step_id}`: {', '.join(command.label for command in executed)}."
    contract = build_local_verify_summary_contract(
        record,
        step_id=step_run.step_id,
        commands=executed,
        result_summary=summary,
        validation_risks=[],
    )
    write_verify_summary_contract(record, contract)
    return contract.summary


def _verify_prompt(record: WorkflowRunRecord, step_run: WorkflowStepRun) -> str:
    return "\n".join(
        [
            "You are the verify backend for an Agents Team workflow.",
            "In read-only mode, run or reason through the projected source workspace and produce a single JSON object only.",
            "Use the structured context files in `.agents-context/` instead of reading historical workflow artifacts.",
            "",
            f"Run id: {record.id}",
            f"Verify step id: {step_run.step_id}",
            f"Task: {record.task}",
            "",
            "Read `.agents-context/run-state.json`, `.agents-context/step-context.json`, `.agents-context/selected-memory.json`, `.agents-context/upstream-handoff.json`, and `.agents-context/changed.diff` first.",
            "If the step context includes a narrowed delta scope, keep verification inside that scope and mark unrelated commands as skipped instead of widening the run again.",
            "",
            "Output schema:",
            "{",
            '  "run_id": string,',
            '  "step_id": string,',
            '  "task": string,',
            '  "executed_commands": [{"label": string, "status": "completed"|"failed"|"skipped", "exit_code": number|null, "output_excerpt": string|null}],',
            '  "result_summary": string,',
            '  "validation_risks": string[],',
            '  "follow_up_checks": string[],',
            '  "summary": string',
            "}",
        ]
    )


def execute_verify_backend(
    record: WorkflowRunRecord,
    step_run: WorkflowStepRun,
    settings: Settings,
    should_cancel: Callable[[], bool],
    set_active_process: Callable[[subprocess.Popen[str] | None], None],
) -> str:
    summary = execute_delegated_codex_backend(
        record=record,
        step_run=step_run,
        settings=settings,
        backend_label="Verify backend",
        artifact_path=verify_summary_path(record),
        prompt=_verify_prompt(record, step_run),
        should_cancel=should_cancel,
        set_active_process=set_active_process,
        fallback=lambda: _local_verify(record, step_run, settings, should_cancel, set_active_process),
    )
    try:
        contract = load_verify_summary_contract(record)
    except Exception as exc:  # noqa: BLE001
        append_log(record, f"Verify backend produced an invalid JSON contract; falling back to local contract generation: {exc}")
        return _local_verify(record, step_run, settings, should_cancel, set_active_process)
    if contract is None:
        return _local_verify(record, step_run, settings, should_cancel, set_active_process)
    write_verify_summary_contract(record, contract)
    return summary
