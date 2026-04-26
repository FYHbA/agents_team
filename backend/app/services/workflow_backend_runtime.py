from __future__ import annotations

import json
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from queue import Empty, Queue
from uuid import uuid4

from app.config import Settings
from app.models.dto import WorkflowCommandPreview
from app.models.dto import WorkflowRunRecord
from app.services.workflow_agent_sessions import append_agent_session_event
from app.services.workflow_context_audit import record_forbidden_source_attempt, update_context_audit_usage
from app.services.workflow_context_policy import FORBIDDEN_SOURCE_MARKERS
from app.services.workflow_backend_exceptions import WorkflowCancellationRequested, WorkflowExecutionError
from app.services.workflow_run_store import append_log

POLL_INTERVAL_SECONDS = 0.25


def _looks_like_codex_exec(argv: list[str]) -> bool:
    return len(argv) >= 2 and argv[0] == "codex" and argv[1] == "exec"


def _enqueue_stream_lines(
    stream,
    source: str,
    queue: Queue[tuple[str, str | None]],
) -> None:
    if stream is None:
        queue.put((source, None))
        return
    try:
        for line in iter(stream.readline, ""):
            queue.put((source, line))
    finally:
        try:
            stream.close()
        except OSError:
            pass
        queue.put((source, None))


def _record_plain_command_event(
    *,
    settings: Settings,
    record: WorkflowRunRecord,
    command_id: str,
    label: str,
    command: str,
    status: str,
    output: str = "",
    exit_code: int | None = None,
) -> None:
    append_agent_session_event(
        settings=settings,
        event_type="command_execution",
        payload={
            "command_id": command_id,
            "label": label,
            "command": command,
            "status": status,
            "output": output,
            "exit_code": exit_code,
        },
    )


def _looks_forbidden_source(command: str) -> bool:
    lowered = command.lower()
    return any(marker.lower() in lowered for marker in FORBIDDEN_SOURCE_MARKERS)


def _usage_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _capture_codex_usage_event(settings: Settings, payload: dict) -> bool:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return False
    input_tokens = _usage_int(usage.get("input_tokens"))
    cached_tokens = _usage_int(usage.get("cached_input_tokens"))
    if cached_tokens is None:
        cached_tokens = _usage_int(usage.get("cached_tokens"))
    output_tokens = _usage_int(usage.get("output_tokens"))
    if input_tokens is None and cached_tokens is None and output_tokens is None:
        return False
    update_context_audit_usage(
        settings=settings,
        input_tokens=input_tokens,
        cached_tokens=cached_tokens,
        output_tokens=output_tokens,
    )
    return True


def _capture_codex_stream_event(settings: Settings, record: WorkflowRunRecord, line: str) -> None:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return
    if not isinstance(payload, dict):
        return
    if _capture_codex_usage_event(settings, payload):
        return

    item = payload.get("item")
    if not isinstance(item, dict):
        return

    item_type = item.get("type")
    if item_type == "agent_message" and isinstance(item.get("text"), str):
        append_agent_session_event(
            settings=settings,
            event_type="agent_message",
            payload={
                "item_id": str(item.get("id") or ""),
                "status": str(item.get("status") or ""),
                "text": item["text"],
            },
        )
        return

    if item_type == "command_execution" and isinstance(item.get("command"), str):
        command_text = item["command"]
        if _looks_forbidden_source(command_text):
            if record_forbidden_source_attempt(settings, command_text):
                append_log(record, f"context-audit: forbidden source access attempt detected in command `{command_text}`")
        append_agent_session_event(
            settings=settings,
            event_type="command_execution",
            payload={
                "command_id": str(item.get("id") or ""),
                "label": str(item.get("command") or ""),
                "command": command_text,
                "status": str(item.get("status") or ""),
                "output": str(item.get("aggregated_output") or ""),
                "exit_code": item.get("exit_code"),
            },
        )


def run_command(
    argv: list[str],
    *,
    settings: Settings,
    cwd: str,
    timeout: int,
    log_prefix: str,
    record: WorkflowRunRecord,
    should_cancel: Callable[[], bool],
    set_active_process: Callable[[subprocess.Popen[str] | None], None],
) -> subprocess.CompletedProcess[str]:
    append_log(record, f"{log_prefix}: {' '.join(argv)}")
    looks_like_codex_stream = _looks_like_codex_exec(argv)
    plain_command_event_id = f"cmd-{uuid4().hex[:10]}"
    plain_command = " ".join(argv)
    if not looks_like_codex_stream:
        _record_plain_command_event(
            settings=settings,
            record=record,
            command_id=plain_command_event_id,
            label=log_prefix,
            command=plain_command,
            status="running",
        )
    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except FileNotFoundError as exc:
        raise WorkflowExecutionError(f"Command not found: {argv[0]}") from exc

    set_active_process(process)
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    deadline = time.monotonic() + timeout
    queue: Queue[tuple[str, str | None]] = Queue()
    stdout_thread = threading.Thread(
        target=_enqueue_stream_lines,
        args=(process.stdout, "stdout", queue),
        daemon=True,
        name=f"workflow-stdout-{plain_command_event_id}",
    )
    stderr_thread = threading.Thread(
        target=_enqueue_stream_lines,
        args=(process.stderr, "stderr", queue),
        daemon=True,
        name=f"workflow-stderr-{plain_command_event_id}",
    )
    stdout_thread.start()
    stderr_thread.start()
    stdout_closed = False
    stderr_closed = False
    cancelled = False
    timed_out = False
    cancellation_message = f"Workflow execution was cancelled while running `{log_prefix}`."

    try:
        while True:
            if process.poll() is not None and stdout_closed and stderr_closed:
                break

            if should_cancel():
                process.terminate()
                cancelled = True

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                timed_out = True

            try:
                source, line = queue.get(timeout=POLL_INTERVAL_SECONDS)
            except Empty:
                continue
            if line is None:
                if source == "stdout":
                    stdout_closed = True
                else:
                    stderr_closed = True
                continue
            if source == "stdout":
                stdout_chunks.append(line)
                if looks_like_codex_stream:
                    _capture_codex_stream_event(settings, record, line)
            else:
                stderr_chunks.append(line)
    finally:
        if process.poll() is None:
            process.wait(timeout=5)
        stdout_thread.join(timeout=1)
        stderr_thread.join(timeout=1)
        set_active_process(None)
        stdout = "".join(stdout_chunks)
        stderr = "".join(stderr_chunks)
        if stdout.strip():
            append_log(record, f"{log_prefix} stdout:\n{stdout.rstrip()}")
        if stderr.strip():
            append_log(record, f"{log_prefix} stderr:\n{stderr.rstrip()}")
        if not looks_like_codex_stream:
            final_output = stdout.strip()
            if stderr.strip():
                final_output = f"{final_output}\n{stderr.strip()}".strip()
            _record_plain_command_event(
                settings=settings,
                record=record,
                command_id=plain_command_event_id,
                label=log_prefix,
                command=plain_command,
                status="cancelled" if cancelled else ("failed" if (timed_out or process.returncode != 0) else "completed"),
                output=final_output,
                exit_code=process.returncode,
            )

    stdout = "".join(stdout_chunks)
    stderr = "".join(stderr_chunks)
    if cancelled:
        raise WorkflowCancellationRequested(cancellation_message)
    if timed_out:
        raise WorkflowExecutionError(f"Command timed out after {timeout} seconds: {log_prefix}")

    return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)


def _load_package_scripts(project_path: Path) -> dict[str, str]:
    package_json = project_path / "package.json"
    if not package_json.exists():
        return {}
    try:
        payload = json.loads(package_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    scripts = payload.get("scripts", {})
    if not isinstance(scripts, dict):
        return {}
    cleaned: dict[str, str] = {}
    for key, value in scripts.items():
        if isinstance(key, str) and isinstance(value, str):
            cleaned[key] = value
    return cleaned


def verification_commands(project_path: Path, *, focus: str = "all") -> list[tuple[str, list[str]]]:
    commands: list[tuple[str, list[str]]] = []
    if focus in {"docs", "none"}:
        return commands

    has_python_tests = (project_path / "tests").exists() or (project_path / "pyproject.toml").exists()
    include_tests = focus in {"all", "tests"}
    include_build = focus in {"all", "build"}

    if has_python_tests and include_tests:
        commands.append(("python -m pytest", ["python", "-m", "pytest"]))

    scripts = _load_package_scripts(project_path)
    build_script = scripts.get("build")
    if build_script and include_build:
        commands.append(("npm run build", ["npm", "run", "build"]))

    test_script = scripts.get("test", "")
    lowered_test_script = test_script.lower()
    if include_tests and test_script and "no test specified" not in lowered_test_script and "exit 1" not in lowered_test_script:
        commands.append(("npm run test", ["npm", "run", "test"]))

    return commands


def verification_command_previews(
    project_path: Path,
    *,
    focus: str = "all",
    step_id: str,
    requires_confirmation: bool = False,
) -> list[WorkflowCommandPreview]:
    return [
        WorkflowCommandPreview(
            command_id=f"{step_id}:{index}",
            label=label,
            argv=argv,
            cwd=str(project_path),
            source="verification",
            requires_confirmation=requires_confirmation,
        )
        for index, (label, argv) in enumerate(verification_commands(project_path, focus=focus), start=1)
    ]
