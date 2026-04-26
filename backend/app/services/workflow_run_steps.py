from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from app.config import Settings
from app.models.dto import WorkflowRunRecord, WorkflowStepRun
from app.services.workflow_backend_exceptions import WorkflowCancellationRequested, WorkflowExecutionError
from app.services.workflow_agent_sessions import set_agent_runtime_metadata
from app.services.workflow_backend_planner import execute_planner_backend
from app.services.workflow_backend_research import execute_research_backend
from app.services.workflow_backend_registry import backend_for_step, step_family
from app.services.workflow_backend_reporter import execute_reporter_backend
from app.services.workflow_backend_reviewer import execute_reviewer_backend
from app.services.workflow_backend_runtime import run_command
from app.services.workflow_backend_verify import execute_verify_backend
from app.services.codex import get_codex_capabilities
from app.services.workflow_run_store import append_log, trim_summary

RUN_TIMEOUT_SECONDS = 60 * 45


def build_codex_prompt(record: WorkflowRunRecord) -> str:
    rules = [
        "- Work only inside the provided project directory.",
        "- Make the requested file changes directly when needed.",
        "- Do not create Git commits or push changes.",
        "- Finish with a concise summary of changed files, verification performed, and remaining risks.",
    ]
    if record.allow_network:
        rules.append("- Network lookups are allowed only if the current Codex execution mode supports them.")
    else:
        rules.append("- Do not use network search or remote lookups.")
    if record.allow_installs:
        rules.append("- Package installs are allowed only if strictly necessary.")
    else:
        rules.append("- Do not install new packages or dependencies.")
    rules.append("- Avoid destructive commands because this run is non-interactive.")

    step_lines = [f"- {step.id}: {step.title} ({step.agent_role}) -> {step.goal}" for step in record.steps]
    project_memory_lines = [
        f"- {entry.title}: {entry.summary}" for entry in record.memory_context.recalled_project
    ] or ["- No project memory recalled."]
    global_memory_lines = [
        f"- {entry.title}: {entry.summary}" for entry in record.memory_context.recalled_global
    ] or ["- No global memory recalled."]
    return "\n".join(
        [
            "You are executing an Agents Team workflow run.",
            f"Run id: {record.id}",
            f"Task: {record.task}",
            "",
            "Workflow steps:",
            *step_lines,
            "",
            "Execution rules:",
            *rules,
            "",
            "Project memory recall:",
            *project_memory_lines,
            "",
            "Global memory recall:",
            *global_memory_lines,
        ]
    )


def _codex_exec_argv(record: WorkflowRunRecord, settings: Settings) -> tuple[list[str], str, str, str | None]:
    capabilities = get_codex_capabilities(settings)
    if not capabilities.codex_cli_available:
        raise WorkflowExecutionError("Codex CLI is not available on PATH.")

    argv = [
        "codex",
        "exec",
        "-C",
        record.project_path,
        "-s",
        "workspace-write" if record.direct_file_editing else "read-only",
        "--skip-git-repo-check",
        "--json",
        "-o",
        record.last_message_path or str(Path(record.run_path) / "last-message.md"),
    ]

    prompt = build_codex_prompt(record)
    if record.codex_session_id and capabilities.exec_resume_available:
        argv.extend(["resume", record.codex_session_id, prompt])
        return argv, "Resumed the selected Codex session in non-interactive mode.", "codex_exec_resume", record.codex_session_id

    if record.codex_session_id and not capabilities.exec_resume_available:
        append_log(
            record,
            "Requested Codex session resume, but `codex exec resume` is unavailable. Falling back to a fresh non-interactive run.",
        )

    argv.append(prompt)
    return argv, "Started a fresh Codex non-interactive run.", "codex_exec_fresh", None


def execute_codex_step(
    record: WorkflowRunRecord,
    settings: Settings,
    should_cancel: Callable[[], bool],
    set_active_process: Callable[[subprocess.Popen[str] | None], None],
) -> str:
    argv, summary_prefix, provider, session_ref = _codex_exec_argv(record, settings)
    completed = run_command(
        argv,
        settings=settings,
        cwd=record.project_path,
        timeout=RUN_TIMEOUT_SECONDS,
        log_prefix="codex",
        record=record,
        should_cancel=should_cancel,
        set_active_process=set_active_process,
    )
    if completed.returncode != 0:
        raise WorkflowExecutionError(f"Codex execution failed with exit code {completed.returncode}.")

    set_agent_runtime_metadata(provider=provider, session_ref=session_ref)
    final_message = ""
    if record.last_message_path:
        last_message_path = Path(record.last_message_path)
        if last_message_path.exists():
            final_message = last_message_path.read_text(encoding="utf-8").strip()
    return trim_summary(f"{summary_prefix} {trim_summary(final_message) or ''}".strip()) or summary_prefix

def execute_step(
    record: WorkflowRunRecord,
    step_run: WorkflowStepRun,
    settings: Settings,
    should_cancel: Callable[[], bool],
    set_active_process: Callable[[subprocess.Popen[str] | None], None],
) -> str:
    expected_backend = backend_for_step(step_run.step_id)
    if step_run.backend != expected_backend:
        raise WorkflowExecutionError(
            f"Step `{step_run.step_id}` expected backend `{expected_backend}`, but the run recorded `{step_run.backend}`."
        )

    family = step_family(step_run.step_id)

    if family == "plan":
        return execute_planner_backend(record, settings, should_cancel, set_active_process)
    if family == "research":
        return execute_research_backend(record, settings, should_cancel, set_active_process)
    if family == "implement":
        return execute_codex_step(record, settings, should_cancel, set_active_process)
    if family == "verify":
        return execute_verify_backend(record, step_run, settings, should_cancel, set_active_process)
    if family == "review":
        return execute_reviewer_backend(record, settings, should_cancel, set_active_process)
    if family == "report":
        return execute_reporter_backend(record, settings, should_cancel, set_active_process)
    return f"No execution handler is registered for step `{step_run.step_id}`."
